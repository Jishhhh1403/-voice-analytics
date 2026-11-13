from __future__ import annotations

import logging
import threading
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from ..config import Settings
from ..db import loads as _json_loads
from ..intelligence import lexicon
from ..intelligence.clustering import _cluster
from ..intelligence.contracts import CleanFeedback, ExtractedInsight
from ..intelligence.measurement import measure_problems, measurement_inputs
from ..intelligence.prioritization import prioritise_problems
from ..intelligence.providers import build_provider
from ..intelligence.taxonomy import Taxonomy
from ..repository import Repository, now_iso
from ..storage import ObjectStore, build_object_store
from .ingestion import IngestionError, parse_feedback_csv
from .mds import MdsService

logger = logging.getLogger("bci.pipeline")


def _loads_list(value: Any) -> list[Any]:
    loaded = _json_loads(value) if value else []
    return loaded if isinstance(loaded, list) else []


class FeedbackPipelineService:
    def __init__(self, settings: Settings, repo: Repository, store: ObjectStore | None = None) -> None:
        self.settings = settings
        self.repo = repo
        self.store = store or build_object_store(settings)
        self.taxonomy = Taxonomy.load(settings.taxonomy_path)
        self.provider = build_provider(settings)
        self.mds = MdsService(settings, repo)
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
                "duplicate_relationships": len(parsed.duplicate_relationships),
                "duplicate_policy": "linked_not_discarded",
                "pii_types": parsed.pii_types,
                "language_counts": parsed.manifest.get("language_counts", {}),
                "data_quality": parsed.manifest.get("data_quality", {}),
            }
            manifest_id = "MAN-" + uuid.uuid4().hex[:12]
            self.repo.save_manifest(manifest_id, run_id, manifest)
            self.repo.save_feedback(run_id, self.settings.tenant_id, parsed.accepted)
            self.repo.save_quarantine(run_id, parsed.rejected)
            self.repo.save_duplicate_candidates(run_id, parsed.duplicate_relationships)
            self.repo.save_quality_report(run_id, parsed.quality_checks)
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
            self.repo.save_model_execution(
                run_id,
                stage,
                provider=self.provider.model_id,
                model_id=self.provider.model_id,
                prompt_version=getattr(self.provider, "prompt_version", "rules-2.0"),
                input_count=len(records),
                output_count=len(insights),
                metadata={"model": self.provider.model_id},
            )
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
            self.repo.save_model_execution(
                run_id,
                stage,
                provider=self.settings.embedding_provider,
                model_id=model_version,
                prompt_version=None,
                input_count=len(insights),
                output_count=len(cluster_output.problems),
                metadata={"clustering_provider": self.settings.clustering_provider},
            )
            self.repo.save_problems(run_id, cluster_output.problems, model_version, self.taxonomy.version)
            self.repo.save_problem_symptoms(run_id, cluster_output.problems)
            self.repo.save_clusters(run_id, cluster_output.clusters)
            self.repo.replace_evidence(run_id, cluster_output.evidence)
            relationships = self._cooccurrence_relationships(cluster_output.problems, cluster_output.evidence)
            self.repo.save_problem_relationships(run_id, relationships)
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
                    "relationships": len(relationships),
                    "embedding_model": model_version,
                },
            )

            stage = "module_d_map"
            self.repo.stage(run_id, stage, "running")
            self.repo.save_taxonomy(self.taxonomy.rows())
            self.repo.save_mappings(cluster_output.mappings)
            self.repo.save_problem_journey_mappings(run_id, cluster_output.mappings, self.taxonomy)
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

            stage = "measurement_engine"
            self.repo.stage(run_id, stage, "running")
            measurement = measure_problems(
                cluster_output.problems,
                cluster_output.evidence,
                window_days=self.settings.measurement_window_days,
                baseline_days=self.settings.trend_baseline_days,
                current_days=self.settings.trend_current_days,
                duplicate_links=parsed.duplicate_relationships,
            )
            if self.settings.enable_measurement_engine:
                self.repo.save_measurement(run_id, measurement, self.settings.scoring_methodology_version)
            metric_status = Counter(item["status"] for item in measurement.snapshots)
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=len(cluster_output.problems),
                succeeded=len(cluster_output.problems),
                message=f"{len(measurement.snapshots)} measurement snapshots",
                metrics={
                    "metrics": len(measurement.snapshots),
                    "daily_rows": len(measurement.daily),
                    "status": dict(metric_status),
                    "window_days": self.settings.measurement_window_days,
                    "enabled": self.settings.enable_measurement_engine,
                },
            )

            stage = "priority_engine"
            self.repo.stage(run_id, stage, "running")
            priority = prioritise_problems(
                self.settings,
                cluster_output.problems,
                cluster_output.evidence,
                measurement_inputs(measurement),
                duplicate_links=parsed.duplicate_relationships,
                measurement_window_start=measurement.window_start,
                measurement_window_end=measurement.window_end,
            )
            if self.settings.enable_priority_engine:
                self.repo.save_priorities(run_id, priority)
            escalations = sum(1 for item in priority.scores if item["escalation_status"] == "ESCALATE")
            self.repo.stage(
                run_id,
                stage,
                "succeeded",
                processed=len(cluster_output.problems),
                succeeded=len(priority.scores),
                message=f"{len(priority.scores)} problems prioritised, {escalations} escalated",
                metrics={
                    "prioritised": len(priority.scores),
                    "escalations": escalations,
                    "weights": priority.weights,
                    "methodology_version": self.settings.scoring_methodology_version,
                    "enabled": self.settings.enable_priority_engine,
                },
            )

            stage = "mds_engine"
            self.repo.stage(run_id, stage, "running")
            theme_map: dict[str, Any] = {}
            try:
                if self.settings.enable_mds:
                    theme_map = self.mds.recompute(run_id)
                    mds_status = "succeeded" if theme_map.get("status") == "OK" else "skipped"
                    self.repo.stage(
                        run_id,
                        stage,
                        mds_status,
                        processed=len(cluster_output.problems),
                        succeeded=theme_map.get("n_themes", 0),
                        message=(
                            f"{theme_map.get('n_themes', 0)} themes mapped"
                            if mds_status == "succeeded"
                            else f"Theme map {theme_map.get('status', 'unavailable').lower()}"
                        ),
                        metrics={
                            "enabled": True,
                            "status": theme_map.get("status"),
                            "themes": theme_map.get("n_themes", 0),
                            "stress": theme_map.get("stress"),
                            "normalized_stress": theme_map.get("normalized_stress"),
                            "stress_status": theme_map.get("stress_status"),
                            "methodology_version": self.settings.mds_methodology_version,
                        },
                    )
                else:
                    self.repo.stage(
                        run_id,
                        stage,
                        "skipped",
                        message="MDS theme map disabled",
                        metrics={"enabled": False},
                    )
            except Exception as exc:  # noqa: BLE001 - theme map must not fail the feedback pipeline
                logger.exception("MDS theme map failed", extra={"run_id": run_id})
                self.repo.stage(
                    run_id,
                    stage,
                    "failed",
                    failed=1,
                    message=f"{type(exc).__name__}: theme map failed",
                    metrics={"enabled": True, "status": "FAILED"},
                )

            stage = "module_e_publish"
            self.repo.stage(run_id, stage, "running")
            self.repo.rebuild_daily_analytics(run_id)
            summary = {
                "accepted_feedback": len(parsed.accepted),
                "rejected_feedback": len(parsed.rejected),
                "duplicate_feedback": len(parsed.duplicates),
                "near_duplicate_links": parsed.manifest.get("near_duplicate_rows", 0),
                "repeat_complaint_links": parsed.manifest.get("repeat_complaint_rows", 0),
                "duplicate_policy": "linked_not_discarded",
                "language_counts": parsed.manifest.get("language_counts", {}),
                "data_quality_status": parsed.manifest.get("data_quality", {}).get("status_counts", {}),
                "data_quality_failures": parsed.manifest.get("data_quality", {}).get("has_failures", False),
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
                "measurement_snapshots": len(measurement.snapshots),
                "prioritised_problems": len(priority.scores),
                "escalations": escalations,
                "scoring_methodology_version": self.settings.scoring_methodology_version,
                "theme_map_status": theme_map.get("status", "DISABLED" if not self.settings.enable_mds else "UNAVAILABLE"),
                "themes_mapped": theme_map.get("n_themes", 0),
                "theme_map_stress": theme_map.get("stress"),
                "theme_map_stress_status": theme_map.get("stress_status"),
                "mds_methodology_version": self.settings.mds_methodology_version,
                "priority_top": [
                    {"problem_id": item["problem_id"], "rank": item["rank"], "score": item["priority_score"]}
                    for item in priority.scores[:5]
                ],
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
    def _cooccurrence_relationships(
        self,
        problems: list[Any],
        evidence: dict[str, list[tuple[Any, Any]]],
    ) -> list[dict[str, Any]]:
        """Record descriptive co-occurrence between problems reported by the same customer.

        This is never presented as a causal relationship.
        """

        customer_problems: dict[str, set[str]] = {}
        for problem in problems:
            for _, record in evidence.get(problem.problem_id, []):
                if record.synthetic_customer_ref:
                    customer_problems.setdefault(record.synthetic_customer_ref, set()).add(problem.problem_id)
        pair_counts: dict[tuple[str, str], int] = {}
        for problem_ids in customer_problems.values():
            ordered = sorted(problem_ids)
            for index, left in enumerate(ordered):
                for right in ordered[index + 1 :]:
                    pair_counts[(left, right)] = pair_counts.get((left, right), 0) + 1
        relationships = []
        for (left, right), count in sorted(pair_counts.items()):
            relationships.append(
                {
                    "relationship_id": "PR-" + uuid.uuid4().hex[:16],
                    "source_problem_id": left,
                    "target_problem_id": right,
                    "relationship_type": "co_occurs_with",
                    "confidence": round(min(0.9, 0.3 + 0.1 * count), 3),
                    "status": "candidate",
                    "rationale": (
                        f"Reported by the same customer in {count} case(s). This is descriptive "
                        "co-occurrence, not evidence of causation."
                    ),
                }
            )
        return relationships

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
                    language_confidence=row.get("language_confidence") or 0.0,
                    synthetic_customer_ref=row["synthetic_customer_ref"],
                    rating=row["rating"],
                    feedback_title=row["feedback_title"] or "",
                    feedback_text_redacted=row["feedback_text_redacted"],
                    feedback_text_original=row.get("feedback_text_original"),
                    content_fingerprint=row["content_fingerprint"],
                    duplicate_group_id=row.get("duplicate_group_id"),
                    duplicate_type=row.get("duplicate_type"),
                    quality_flags=_loads_list(row.get("quality_flags_json")),
                    pii_types=_loads_list(row.get("pii_types_json")),
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
