from __future__ import annotations

import logging
import threading
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from ..config import Settings
from ..intelligence import lexicon
from ..intelligence.clustering import _cluster
from ..intelligence.contracts import CleanFeedback, ExtractedInsight
from ..intelligence.extractor import extract_insights
from ..intelligence.providers import build_provider
from ..intelligence.taxonomy import Taxonomy
from ..repository import Repository, now_iso
from ..storage import ObjectStore, build_object_store, sha256_bytes
from .ingestion import IngestionError, parse_feedback_csv

logger = logging.getLogger("bci.pipeline")


class FeedbackPipelineService:
    def __init__(self, settings: Settings, repo: Repository, store: ObjectStore | None = None) -> None:
        self.settings = settings
        self.repo = repo
        self.store = store or build_object_store(settings)
        self.taxonomy = Taxonomy.load(settings.taxonomy_path)
        self.provider = build_provider(settings)
        self._threads: dict[str, threading.Thread] = {}

    # ---------------------------------------------------------------- source
    def ensure_default_source(self) -> str:
        if self.settings.default_feedback_uri:
            return self.settings.default_feedback_uri
        if self.settings.object_store.lower() != "local":
            raise IngestionError("DEFAULT_FEEDBACK_URI must be set when OBJECT_STORE=gcs")
        stored = self.store.ensure_sample_source(self.settings.sample_feedback_path, self.settings.gcs_feedback_prefix)  # type: ignore[attr-defined]
        return stored.uri

    def _normalise_input(self, input_uri: str | None) -> str:
        if not input_uri:
            return self.ensure_default_source()
        if input_uri.startswith(("local://", "gs://", "file://")):
            return input_uri
        path = Path(input_uri)
        if path.exists() and path.is_file():
            if self.settings.object_store.lower() != "local":
                raise IngestionError("upload the CSV to GCS first, then pass the gs:// URI")
            key = f"{self.settings.gcs_feedback_prefix}/{path.name}"
            self.store.put_file(key, path, "text/csv")  # type: ignore[attr-defined]
            return f"local://{key}"
        if self.settings.object_store.lower() == "local":
            return f"local://{input_uri.lstrip('/')}"
        return input_uri

    # ---------------------------------------------------------------- start
    def start(
        self,
        input_uri: str | None,
        object_generation: str | None,
        tenant_id: str | None,
        force_rerun: bool = False,
        run_in_thread: bool = True,
    ) -> str:
        uri = self._normalise_input(input_uri)
        stat = self.store.stat(uri, object_generation)
        if not force_rerun:
            existing = self.repo.find_completed_run(uri, stat.generation)
            if existing:
                return existing["run_id"]
        run_id = self.repo.create_run(
            run_type="feedback",
            tenant_id=tenant_id or self.settings.tenant_id,
            input_uri=uri,
            generation=stat.generation,
            source_filename=stat.key.split("/")[-1],
            code_version=self.settings.code_version,
            schema_version=self.settings.schema_version,
            model_version=self.provider.model_id,
            taxonomy_version=self.taxonomy.version,
        )
        if run_in_thread:
            thread = threading.Thread(
                target=self.execute, args=(run_id, uri, stat.generation), name=f"pipeline-{run_id}", daemon=True
            )
            self._threads[run_id] = thread
            thread.start()
        return run_id

    def execute(self, run_id: str, input_uri: str, generation: str | None) -> None:
        self.repo.update_run(run_id, status="running", started_at=now_iso())
        stage = "validate_source"
        try:
            self.repo.stage(run_id, stage, "running")
            data, stat = self.store.read_bytes(input_uri, generation)
            if len(data) > self.settings.max_feedback_bytes:
                raise IngestionError("source object exceeds configured maximum size")
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=1,
                succeeded=1,
                message="Source object resolved",
                metrics={"generation": stat.generation, "size_bytes": stat.size_bytes, "sha256": stat.sha256},
            )

            stage = "module_a_ingest"
            self.repo.stage(run_id, stage, "running")
            parsed = parse_feedback_csv(data, self.settings.tenant_id, self.settings)
            manifest = {
                **stat.to_dict(),
                "original_filename": stat.key.split("/")[-1],
                "accepted_rows": len(parsed.accepted),
                "rejected_rows": len(parsed.rejected),
                "duplicate_rows": len(parsed.duplicates),
                "pii_types": parsed.pii_types,
            }
            manifest_id = "MAN-" + uuid.uuid4().hex[:12]
            self.repo.save_manifest(manifest_id, run_id, manifest)
            self.repo.save_feedback(run_id, self.settings.tenant_id, parsed.accepted)
            self.repo.save_quarantine(run_id, parsed.rejected)
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=parsed.manifest["rows_read"],
                succeeded=len(parsed.accepted),
                failed=len(parsed.rejected),
                message=f"{len(parsed.accepted)} accepted, {len(parsed.rejected)} rejected, {len(parsed.duplicates)} duplicates",
                metrics={**parsed.manifest, "pii_types": parsed.pii_types},
            )

            stage = "module_b_extract"
            self.repo.stage(run_id, stage, "running")
            records = self._records(run_id)
            batch_size = max(1, self.settings.llm_batch_size) if self.provider.model_id != "rules-v1" else 24
            insights: list[ExtractedInsight] = []
            for start in range(0, len(records), batch_size):
                batch = records[start : start + batch_size]
                extracted = self.provider.extract_batch(batch)
                for record in batch:
                    for insight in extracted.get(record.feedback_id, []):
                        self._enrich_insight(insight)
                        insights.append(insight)
            # Deduplicate identical evidence/insight pairs produced by retries or overlapping clauses.
            unique: dict[str, ExtractedInsight] = {}
            for insight in insights:
                unique.setdefault(insight.insight_id, insight)
            insights = list(unique.values())
            self.repo.save_run_insights(run_id, insights)
            sentiment_counts = Counter(item.sentiment for item in insights)
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=len(records),
                succeeded=len(records),
                message=f"{len(insights)} evidence-backed insights extracted",
                metrics={
                    "insights": len(insights),
                    "problem_insights": sum(1 for item in insights if item.is_problem),
                    "sentiment": dict(sentiment_counts),
                    "provider": self.provider.model_id,
                },
            )

            stage = "module_c_discover"
            self.repo.stage(run_id, stage, "running")
            feedback_by_id = {record.feedback_id: record for record in records}
            cluster_output = _cluster(self.taxonomy, self.settings, insights, feedback_by_id)
            model_version = (
                cluster_output.clusters[0]["model_version"] if cluster_output.clusters else self.provider.model_id
            )
            self.repo.save_problems(run_id, cluster_output.problems, model_version, self.taxonomy.version)
            self.repo.save_clusters(run_id, cluster_output.clusters)
            self.repo.replace_evidence(run_id, cluster_output.evidence)
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=len(insights),
                succeeded=len(cluster_output.problems),
                message=f"{len(cluster_output.problems)} canonical customer problems consolidated",
                metrics={
                    "problems": len(cluster_output.problems),
                    "clusters": len(cluster_output.clusters),
                    "embedding_model": model_version,
                },
            )

            stage = "module_d_map"
            self.repo.stage(run_id, stage, "running")
            self.repo.save_taxonomy(self.taxonomy.rows())
            self.repo.save_mappings(cluster_output.mappings)
            self.repo.save_proposals(run_id, cluster_output.proposals)
            mapped = len(cluster_output.mappings)
            unmapped = len(cluster_output.proposals)
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=len(cluster_output.problems),
                succeeded=mapped,
                failed=unmapped,
                message=f"{mapped} mapped, {unmapped} taxonomy proposals",
                metrics={"taxonomy_version": self.taxonomy.version, "proposals": unmapped},
            )

            stage = "module_e_publish"
            self.repo.stage(run_id, stage, "running")
            self.repo.rebuild_daily_analytics(run_id)
            summary = {
                "accepted_feedback": len(parsed.accepted),
                "rejected_feedback": len(parsed.rejected),
                "duplicate_feedback": len(parsed.duplicates),
                "insights": len(insights),
                "problems": len(cluster_output.problems),
                "mapped_problems": mapped,
                "unmapped_problems": unmapped,
                "evidence_links": sum(len(items) for items in cluster_output.evidence.values()),
                "pii_types_redacted": parsed.pii_types,
                "source_generation": stat.generation,
                "taxonomy_version": self.taxonomy.version,
                "model_version": model_version,
                "provider": self.provider.model_id,
                "synthetic": all(record.is_synthetic for record in records) if records else True,
            }
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=len(cluster_output.problems),
                succeeded=len(cluster_output.problems),
                message="Analytics published",
                metrics=summary,
            )
            self.repo.update_run(
                run_id,
                status="completed",
                finished_at=now_iso(),
                summary=summary,
                model_version=model_version,
            )
            logger.info("feedback pipeline completed", extra={"run_id": run_id, **summary})
        except Exception as exc:  # noqa: BLE001 - safe failure boundary for background job
            safe_message = f"{type(exc).__name__}: pipeline stage failed"
            logger.exception("feedback pipeline failed", extra={"run_id": run_id, "stage": stage})
            try:
                self.repo.stage(run_id, stage, "failed", failed=1, message=safe_message)
            except Exception:
                logger.exception("could not update failed stage", extra={"run_id": run_id})
            self.repo.update_run(run_id, status="failed", finished_at=now_iso(), error=safe_message)

    # ---------------------------------------------------------------- helpers
    def _records(self, run_id: str) -> list[CleanFeedback]:
        rows = self.repo.feedback_for_run(run_id)
        records: list[CleanFeedback] = []
        for row in rows:
            records.append(
                CleanFeedback(
                    feedback_id=row["feedback_id"],
                    source_feedback_id=row["source_feedback_id"],
                    submitted_at=row["submitted_at"],
                    source_type=row["source_type"] or "unknown",
                    source_channel=row["source_channel"] or "unknown",
                    platform=row["platform"] or "Unknown",
                    app_version=row["app_version"],
                    language=row["language"] or "en",
                    synthetic_customer_ref=row["synthetic_customer_ref"],
                    rating=row["rating"],
                    feedback_title=row["feedback_title"] or "",
                    feedback_text_redacted=row["feedback_text_redacted"],
                    content_fingerprint=row["content_fingerprint"],
                    is_synthetic=bool(row["is_synthetic"]),
                )
            )
        return records

    def _enrich_insight(self, insight: ExtractedInsight) -> None:
        if insight.journey_node_id:
            return
        aspect = insight.aspect
        if aspect:
            node = next((item.node_id for item in lexicon.ASPECTS if item.key == aspect), None)
            if node:
                insight.journey_node_id = node
                insight.symptom_category = insight.symptom_category or "general"
                return
        text = " ".join(filter(None, [insight.aspect, insight.reported_problem, insight.reported_symptom]))
        if text:
            best, _ = self.taxonomy.best_node(text)
            if best:
                insight.journey_node_id = best.node_id
                if not insight.aspect:
                    insight.aspect = best.node_id.split(".")[-1]

    def run_sync(self, run_id: str, input_uri: str, generation: str | None) -> None:
        self.execute(run_id, input_uri, generation)
