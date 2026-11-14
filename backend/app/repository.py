from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .db import Database, dumps, loads

STAGES = [
    "validate_source",
    "module_a_ingest",
    "module_b_extract",
    "module_c_discover",
    "module_d_map",
    "measurement_engine",
    "priority_engine",
    "mds_engine",
    "module_e_publish",
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------------- runs
    def create_run(
        self,
        run_type: str,
        tenant_id: str,
        input_uri: str | None,
        generation: str | None,
        source_filename: str | None,
        code_version: str,
        schema_version: str,
        model_version: str,
        taxonomy_version: str,
    ) -> str:
        run_id = f"RUN-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        correlation_id = f"CORR-{uuid.uuid4().hex[:12]}"
        self.db.insert(
            "pipeline_runs",
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "run_type": run_type,
                "status": "queued",
                "input_uri": input_uri,
                "input_generation": generation,
                "source_filename": source_filename,
                "code_version": code_version,
                "schema_version": schema_version,
                "model_version": model_version,
                "taxonomy_version": taxonomy_version,
                "created_at": now_iso(),
                "correlation_id": correlation_id,
            },
        )
        for stage in STAGES:
            self.db.insert(
                "pipeline_stages",
                {"run_id": run_id, "stage": stage, "status": "pending", "metrics_json": "{}"},
            )
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "summary" in fields:
            fields["summary_json"] = dumps(fields.pop("summary"))
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.db.execute(
            f"UPDATE pipeline_runs SET {assignments} WHERE run_id=?",
            [*fields.values(), run_id],
        )

    def stage(self, run_id: str, stage: str, status: str, **fields: Any) -> None:
        values: dict[str, Any] = {"status": status, **fields}
        if "metrics" in values:
            values["metrics_json"] = dumps(values.pop("metrics"))
        if status == "running":
            values["started_at"] = now_iso()
        if status in ("succeeded", "failed", "cancelled"):
            values["finished_at"] = now_iso()
        assignments = ", ".join(f"{key}=?" for key in values)
        self.db.execute(
            f"UPDATE pipeline_stages SET {assignments} WHERE run_id=? AND stage=?",
            [*values.values(), run_id, stage],
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.db.query_one("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,))
        if not run:
            return None
        run["summary"] = loads(run.pop("summary_json", None), {})
        run["stages"] = self.db.query(
            "SELECT stage, status, started_at, finished_at, processed, succeeded, failed, message, metrics_json "
            "FROM pipeline_stages WHERE run_id=? ORDER BY id",
            (run_id,),
        )
        for stage in run["stages"]:
            stage["metrics"] = loads(stage.pop("metrics_json", None), {})
        run["is_terminal"] = run["status"] in ("completed", "failed", "cancelled")
        return run

    def list_runs(self, run_type: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        if run_type:
            rows = self.db.query(
                "SELECT * FROM pipeline_runs WHERE run_type=? ORDER BY created_at DESC LIMIT ?",
                (run_type, limit),
            )
        else:
            rows = self.db.query("SELECT * FROM pipeline_runs ORDER BY created_at DESC LIMIT ?", (limit,))
        for row in rows:
            row["summary"] = loads(row.pop("summary_json", None), {})
            row["is_terminal"] = row["status"] in ("completed", "failed", "cancelled")
            row["stages"] = self.db.query(
                "SELECT stage, status, processed, message, started_at, finished_at "
                "FROM pipeline_stages WHERE run_id=? ORDER BY id",
                (row["run_id"],),
            )
        return rows

    def latest_completed_feedback_run(self) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM pipeline_runs WHERE run_type='feedback' AND status='completed' "
            "ORDER BY finished_at DESC LIMIT 1"
        )

    def find_completed_run(self, input_uri: str, generation: str | None) -> dict[str, Any] | None:
        if generation:
            return self.db.query_one(
                "SELECT * FROM pipeline_runs WHERE run_type='feedback' AND status='completed' "
                "AND input_uri=? AND input_generation=? ORDER BY finished_at DESC LIMIT 1",
                (input_uri, generation),
            )
        return self.db.query_one(
            "SELECT * FROM pipeline_runs WHERE run_type='feedback' AND status='completed' AND input_uri=? "
            "ORDER BY finished_at DESC LIMIT 1",
            (input_uri,),
        )

    def resolve_run_id(self, run_id: str | None = None) -> str | None:
        if run_id:
            return run_id
        run = self.latest_completed_feedback_run()
        return run["run_id"] if run else None

    # ---------------------------------------------------------------- ingestion
    def save_manifest(self, manifest_id: str, run_id: str, manifest: dict[str, Any]) -> None:
        self.db.insert(
            "ingestion_manifests",
            {
                "manifest_id": manifest_id,
                "run_id": run_id,
                "bucket": manifest.get("bucket"),
                "object_key": manifest.get("key"),
                "source_uri": manifest.get("uri"),
                "generation": manifest.get("generation"),
                "size_bytes": manifest.get("size_bytes"),
                "sha256": manifest.get("sha256"),
                "uploaded_at": manifest.get("uploaded_at"),
                "original_filename": manifest.get("original_filename"),
                "accepted_rows": manifest.get("accepted_rows", 0),
                "rejected_rows": manifest.get("rejected_rows", 0),
                "duplicate_rows": manifest.get("duplicate_rows", 0),
                "created_at": now_iso(),
            },
        )

    def save_feedback(self, run_id: str, tenant_id: str, records: list[Any]) -> None:
        rows = [
            {
                "run_id": run_id,
                "feedback_id": record.feedback_id,
                "source_feedback_id": record.source_feedback_id,
                "tenant_id": tenant_id,
                "submitted_at": record.submitted_at,
                "source_type": record.source_type,
                "source_channel": record.source_channel,
                "platform": record.platform,
                "app_version": record.app_version,
                "language": record.language,
                "language_confidence": record.language_confidence,
                "synthetic_customer_ref": record.synthetic_customer_ref,
                "rating": record.rating,
                "feedback_title": record.feedback_title,
                "feedback_text_redacted": record.feedback_text_redacted,
                "feedback_text_original": record.feedback_text_original,
                "content_fingerprint": record.content_fingerprint,
                "duplicate_group_id": record.duplicate_group_id,
                "duplicate_type": record.duplicate_type,
                "quality_flags_json": dumps(record.quality_flags),
                "pii_types_json": dumps(record.pii_types),
                "is_synthetic": int(record.is_synthetic),
                "created_at": now_iso(),
            }
            for record in records
        ]
        self.db.executemany(
            "INSERT OR REPLACE INTO feedback_records (run_id, feedback_id, source_feedback_id, tenant_id, submitted_at, "
            "source_type, source_channel, platform, app_version, language, language_confidence, synthetic_customer_ref, "
            "rating, feedback_title, feedback_text_redacted, feedback_text_original, content_fingerprint, "
            "duplicate_group_id, duplicate_type, quality_flags_json, pii_types_json, is_synthetic, created_at) VALUES "
            "(:run_id, :feedback_id, :source_feedback_id, :tenant_id, :submitted_at, :source_type, :source_channel, "
            ":platform, :app_version, :language, :language_confidence, :synthetic_customer_ref, :rating, "
            ":feedback_title, :feedback_text_redacted, :feedback_text_original, :content_fingerprint, "
            ":duplicate_group_id, :duplicate_type, :quality_flags_json, :pii_types_json, :is_synthetic, :created_at)",
            rows,
        )

    def save_duplicate_candidates(self, run_id: str, relationships: list[dict[str, Any]]) -> None:
        if not relationships:
            return
        detected_at = now_iso()
        self.db.executemany(
            "INSERT OR REPLACE INTO feedback_duplicate_candidates "
            "(candidate_id, run_id, feedback_id, candidate_feedback_id, duplicate_type, similarity, customer_ref, "
            "detected_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"DUP-{uuid.uuid4().hex[:16]}",
                    run_id,
                    item.get("feedback_id"),
                    item.get("candidate_feedback_id"),
                    item.get("duplicate_type"),
                    item.get("similarity"),
                    (item.get("metadata") or {}).get("customer_ref"),
                    detected_at,
                    dumps(item.get("metadata") or {}),
                )
                for item in relationships
            ],
        )

    def save_quality_report(self, run_id: str, checks: list[dict[str, Any]]) -> None:
        created_at = now_iso()
        self.db.executemany(
            "INSERT INTO data_quality_reports "
            "(run_id, check_name, status, severity, affected_rows, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    check.get("check_name"),
                    check.get("status"),
                    check.get("severity"),
                    check.get("affected_rows", 0),
                    dumps(check.get("detail") or {}),
                    created_at,
                )
                for check in checks
            ],
        )

    def save_quarantine(self, run_id: str, rows: list[dict[str, Any]]) -> None:
        self.db.executemany(
            "INSERT INTO feedback_quarantine (run_id, row_number, source_feedback_id, error_reason, raw_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    row.get("row_number"),
                    row.get("source_feedback_id"),
                    row.get("error_reason"),
                    dumps(row.get("raw")),
                    now_iso(),
                )
                for row in rows
            ],
        )

    def feedback_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM feedback_records WHERE run_id=?", (run_id,))

    # ---------------------------------------------------------------- intelligence
    def save_insights(self, insights: list[Any]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO extracted_insights (insight_id, run_id, feedback_id, sentence_index, customer_intent, "
            "intents_json, aspect, aspects_json, journey_node_id, reported_problem, reported_symptom, sentiment, "
            "sentiment_score, emotion, customer_effort, reported_outcome, evidence_span, evidence_verified, "
            "technical_root_cause, language, model_id, prompt_version, schema_version, extraction_timestamp, "
            "extraction_method, confidence, field_confidence_json, human_review_status, cluster_id, embedding_json, "
            "is_problem) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item.insight_id,
                    item.feedback_id.split("|")[0] if "|" in item.feedback_id else getattr(item, "run_id", None),
                    item.feedback_id,
                    item.sentence_index,
                    item.customer_intent,
                    dumps(item.intents),
                    item.aspect,
                    dumps(item.aspects),
                    item.journey_node_id,
                    item.reported_problem,
                    item.reported_symptom,
                    item.sentiment,
                    item.sentiment_score,
                    item.emotion,
                    item.customer_effort,
                    item.reported_outcome,
                    item.evidence_span,
                    int(item.evidence_verified),
                    item.technical_root_cause,
                    item.language,
                    item.model_id,
                    item.prompt_version,
                    item.schema_version,
                    item.extraction_timestamp,
                    item.extraction_method,
                    item.confidence,
                    dumps(item.field_confidence),
                    item.human_review_status,
                    item.cluster_id,
                    item.embedding_json,
                    int(item.is_problem),
                )
                for item in insights
            ],
        )

    def save_run_insights(self, run_id: str, insights: list[Any]) -> None:
        """Persist insights with the correct run id (contracts do not carry it)."""
        self.db.executemany(
            "INSERT OR REPLACE INTO extracted_insights (insight_id, run_id, feedback_id, sentence_index, customer_intent, "
            "intents_json, aspect, aspects_json, journey_node_id, reported_problem, reported_symptom, sentiment, "
            "sentiment_score, emotion, customer_effort, reported_outcome, evidence_span, evidence_verified, "
            "technical_root_cause, language, model_id, prompt_version, schema_version, extraction_timestamp, "
            "extraction_method, confidence, field_confidence_json, human_review_status, cluster_id, embedding_json, "
            "is_problem) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item.insight_id,
                    run_id,
                    item.feedback_id,
                    item.sentence_index,
                    item.customer_intent,
                    dumps(item.intents),
                    item.aspect,
                    dumps(item.aspects),
                    item.journey_node_id,
                    item.reported_problem,
                    item.reported_symptom,
                    item.sentiment,
                    item.sentiment_score,
                    item.emotion,
                    item.customer_effort,
                    item.reported_outcome,
                    item.evidence_span,
                    int(item.evidence_verified),
                    item.technical_root_cause,
                    item.language,
                    item.model_id,
                    item.prompt_version,
                    item.schema_version,
                    item.extraction_timestamp,
                    item.extraction_method,
                    item.confidence,
                    dumps(item.field_confidence),
                    item.human_review_status,
                    item.cluster_id,
                    item.embedding_json,
                    int(item.is_problem),
                )
                for item in insights
            ],
        )

    def save_taxonomy(self, rows: list[dict[str, Any]]) -> None:
        self.db.upsert_many("taxonomy_nodes", rows, ["node_id", "version"])

    def save_problems(self, run_id: str, problems: list[Any], model_version: str, taxonomy_version: str) -> None:
        now = now_iso()
        self.db.upsert_many(
            "customer_problems",
            [
                {
                    "problem_id": problem.problem_id,
                    "run_id": run_id,
                    "signature": problem.signature,
                    "title": problem.title,
                    "problem_statement": problem.problem_statement,
                    "canonical_description": problem.canonical_description or problem.problem_statement,
                    "customer_intent": problem.customer_intent,
                    "aspect": problem.aspect,
                    "symptom_category": problem.symptom_category,
                    "journey_node_id": problem.journey_node_id,
                    "status": problem.lifecycle_status,
                    "lifecycle_status": problem.lifecycle_status,
                    "validation_status": problem.validation_status,
                    "human_review_status": problem.human_review_status,
                    "discovery_confidence": problem.discovery_confidence,
                    "symptoms_json": dumps(problem.symptoms),
                    "parent_problem_id": problem.parent_problem_id,
                    "embedding_ref": problem.embedding_ref,
                    "model_metadata_json": dumps(problem.model_metadata),
                    "evidence_count": problem.evidence_count,
                    "distinct_customers": problem.distinct_customers,
                    "negative_count": problem.negative_count,
                    "first_seen": problem.first_seen,
                    "last_seen": problem.last_seen,
                    "cluster_id": problem.cluster_id,
                    "model_version": model_version,
                    "taxonomy_version": taxonomy_version,
                    "created_at": now,
                    "updated_at": now,
                }
                for problem in problems
            ],
            ["problem_id"],
        )

    def save_problem_symptoms(self, run_id: str, problems: list[Any]) -> None:
        rows = []
        seen: set[tuple[str, str]] = set()
        for problem in problems:
            for symptom in problem.symptoms or []:
                key = (problem.problem_id, symptom.strip().lower())
                if not key[1] or key in seen:
                    continue
                seen.add(key)
                rows.append(
                    (
                        problem.problem_id,
                        symptom.lower().replace(" ", "_")[:80],
                        symptom,
                        problem.symptom_category or "general",
                        0.6,
                        now_iso(),
                    )
                )
        if rows:
            self.db.executemany(
                "INSERT OR REPLACE INTO problem_symptoms (problem_id, symptom_key, symptom_label, symptom_category, confidence, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def save_problem_relationships(self, run_id: str, relationships: list[dict[str, Any]]) -> None:
        if not relationships:
            return
        self.db.executemany(
            "INSERT OR REPLACE INTO problem_relationships (relationship_id, run_id, source_problem_id, "
            "target_problem_id, relationship_type, confidence, status, rationale, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item["relationship_id"],
                    run_id,
                    item["source_problem_id"],
                    item["target_problem_id"],
                    item["relationship_type"],
                    item.get("confidence", 0.5),
                    item.get("status", "candidate"),
                    item.get("rationale"),
                    now_iso(),
                )
                for item in relationships
            ],
        )

    def replace_evidence(self, run_id: str, evidence_by_problem: dict[str, list[tuple[Any, Any]]]) -> None:
        rows = []
        for problem_id, members in evidence_by_problem.items():
            for insight, record in members:
                rows.append(
                    (
                        problem_id,
                        run_id,
                        insight.insight_id,
                        record.feedback_id,
                        insight.evidence_span,
                        record.submitted_at,
                        record.source_type,
                        record.source_channel,
                        record.platform,
                        record.rating,
                        record.synthetic_customer_ref,
                        1.0,
                        now_iso(),
                    )
                )
        self.db.executemany(
            "INSERT INTO problem_evidence (problem_id, run_id, insight_id, feedback_id, evidence_span, submitted_at, "
            "source_type, source_channel, platform, rating, synthetic_customer_ref, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(problem_id, feedback_id, evidence_span) DO UPDATE SET "
            "run_id=excluded.run_id, insight_id=excluded.insight_id, submitted_at=excluded.submitted_at, "
            "source_type=excluded.source_type, source_channel=excluded.source_channel, platform=excluded.platform, "
            "rating=excluded.rating, synthetic_customer_ref=excluded.synthetic_customer_ref",
            rows,
        )

    def save_clusters(self, run_id: str, clusters: list[dict[str, Any]]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO problem_clusters (cluster_id, run_id, label, description, algorithm, params_json, "
            "model_version, member_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    cluster["cluster_id"],
                    run_id,
                    cluster.get("label"),
                    cluster.get("description"),
                    cluster.get("algorithm"),
                    cluster.get("params_json"),
                    cluster.get("model_version"),
                    cluster.get("member_count", 0),
                    now_iso(),
                )
                for cluster in clusters
            ],
        )

    def save_mappings(self, mappings: list[dict[str, Any]]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO problem_mappings (mapping_id, problem_id, node_id, mapping_type, confidence, "
            "rationale, status, taxonomy_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item["mapping_id"],
                    item["problem_id"],
                    item["node_id"],
                    item["mapping_type"],
                    item["confidence"],
                    item["rationale"],
                    item.get("status", "candidate"),
                    item["taxonomy_version"],
                    now_iso(),
                )
                for item in mappings
            ],
        )

    def save_problem_journey_mappings(self, run_id: str, mappings: list[dict[str, Any]], taxonomy: Any) -> None:
        rows = []
        for item in mappings:
            node_id = item.get("node_id")
            chain = taxonomy.ancestors(node_id) if node_id else []
            module_id = next((node.node_id for node in chain if node.node_type == "module"), None)
            feature_id = node_id if node_id and node_id != module_id else None
            rows.append(
                (
                    item["mapping_id"],
                    item["problem_id"],
                    module_id,
                    feature_id,
                    None,
                    item["confidence"],
                    item["rationale"],
                    item.get("status", "candidate"),
                    item["taxonomy_version"],
                    now_iso(),
                )
            )
        if rows:
            self.db.executemany(
                "INSERT OR REPLACE INTO problem_journey_mappings (mapping_id, problem_id, module_id, feature_id, "
                "journey_stage_id, mapping_confidence, explanation, status, taxonomy_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def save_proposals(self, run_id: str, proposals: list[dict[str, Any]]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO taxonomy_proposals (proposal_id, run_id, problem_id, suggested_name, "
            "parent_candidate, description, example_evidence, reason, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            [
                (
                    item["proposal_id"],
                    run_id,
                    item.get("problem_id"),
                    item["suggested_name"],
                    item.get("parent_candidate"),
                    item.get("description"),
                    item.get("example_evidence"),
                    item.get("reason"),
                    now_iso(),
                )
                for item in proposals
            ],
        )

    def rebuild_daily_analytics(self, run_id: str) -> None:
        self.db.execute("DELETE FROM analytics_problem_daily WHERE run_id=?", (run_id,))
        rows = self.db.query(
            "SELECT problem_id, substr(submitted_at, 1, 10) AS day, "
            "COUNT(*) AS feedback_count, "
            "SUM(CASE WHEN rating IS NOT NULL AND rating <= 2 THEN 1 ELSE 0 END) AS negative_count, "
            "SUM(CASE WHEN rating IS NOT NULL AND rating >= 4 THEN 1 ELSE 0 END) AS positive_count, "
            "SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) AS neutral_count, "
            "COUNT(DISTINCT synthetic_customer_ref) AS unique_customers "
            "FROM problem_evidence WHERE run_id=? AND submitted_at IS NOT NULL "
            "GROUP BY problem_id, day",
            (run_id,),
        )
        self.db.executemany(
            "INSERT OR REPLACE INTO analytics_problem_daily (run_id, problem_id, day, feedback_count, negative_count, "
            "positive_count, neutral_count, unique_customers) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    row["problem_id"],
                    row["day"],
                    row["feedback_count"] or 0,
                    row["negative_count"] or 0,
                    row["positive_count"] or 0,
                    row["neutral_count"] or 0,
                    row["unique_customers"] or 0,
                )
                for row in rows
            ],
        )

    # ---------------------------------------------------------------- read APIs
    def filters_sql(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        source_type: str | None = None,
        platform: str | None = None,
        journey: str | None = None,
        alias: str = "e",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if start_date:
            clauses.append(f"substr({alias}.submitted_at,1,10) >= ?")
            params.append(start_date)
        if end_date:
            clauses.append(f"substr({alias}.submitted_at,1,10) <= ?")
            params.append(end_date)
        if source_type:
            clauses.append(f"{alias}.source_type = ?")
            params.append(source_type)
        if platform:
            clauses.append(f"{alias}.platform = ?")
            params.append(platform)
        if journey:
            clauses.append(f"({alias}.journey_node_id = ? OR {alias}.journey_node_id LIKE ?)")
            params.extend([journey, journey + ".%"])
        return (" AND " + " AND ".join(clauses)) if clauses else "", params

    def summary(
        self,
        run_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        source_type: str | None = None,
        platform: str | None = None,
        journey: str | None = None,
    ) -> dict[str, Any]:
        run_id = self.resolve_run_id(run_id)
        if not run_id:
            return {
                "run_id": None,
                "total_feedback": 0,
                "total_insights": 0,
                "total_problems": 0,
                "unmapped_problems": 0,
                "synthetic": True,
                "message": "No completed feedback pipeline run yet.",
                "trend": [],
                "sentiment_by_journey": [],
                "top_problems": [],
                "source_mix": [],
                "platform_mix": [],
                "rating_mix": [],
                "journey_breakdown": [],
            }

        where, params = self.filters_sql(start_date, end_date, source_type, platform, journey, "e")
        feedback_where, feedback_params = self.filters_sql(start_date, end_date, source_type, platform, None, "e")
        if journey:
            feedback_where += (
                " AND EXISTS (SELECT 1 FROM extracted_insights i WHERE i.run_id=e.run_id "
                "AND i.feedback_id=e.feedback_id AND (i.journey_node_id=? OR i.journey_node_id LIKE ?))"
            )
            feedback_params.extend([journey, journey + ".%"])
        total_feedback = self.db.scalar(
            f"SELECT COUNT(*) FROM feedback_records e WHERE e.run_id=?{feedback_where}", [run_id, *feedback_params]
        ) or 0
        total_insights = self.db.scalar(
            f"SELECT COUNT(*) FROM extracted_insights e WHERE e.run_id=?{where}", [run_id, *params]
        ) or 0
        problem_where, problem_params = self.filters_sql(
            start_date, end_date, source_type, platform, journey, "e"
        )
        total_problems = self.db.scalar(
            "SELECT COUNT(DISTINCT p.problem_id) FROM customer_problems p "
            "LEFT JOIN problem_evidence e ON e.problem_id=p.problem_id AND e.run_id=p.run_id "
            f"WHERE p.run_id=?{problem_where}",
            [run_id, *problem_params],
        ) or 0
        unmapped = self.db.scalar(
            "SELECT COUNT(*) FROM customer_problems WHERE run_id=? AND (journey_node_id IS NULL OR journey_node_id='')",
            (run_id,),
        ) or 0
        synthetic = self.db.scalar("SELECT MAX(is_synthetic) FROM feedback_records WHERE run_id=?", (run_id,)) or 0

        trend = self.db.query(
            "SELECT substr(e.submitted_at,1,7) AS period, COUNT(*) AS total, "
            "SUM(CASE WHEN e.rating IS NOT NULL AND e.rating <= 2 THEN 1 ELSE 0 END) AS low_rating "
            "FROM feedback_records e WHERE e.run_id=? AND e.submitted_at IS NOT NULL"
            + feedback_where
            + " GROUP BY period ORDER BY period",
            [run_id, *feedback_params],
        )

        sentiment_by_journey = self.db.query(
            "SELECT COALESCE(NULLIF(e.journey_node_id,''), 'unmapped') AS journey_node_id, e.sentiment, COUNT(*) AS total "
            "FROM extracted_insights e WHERE e.run_id=?" + where + " GROUP BY journey_node_id, e.sentiment",
            [run_id, *params],
        )

        top_problems = self.db.query(
            "SELECT p.problem_id, p.title, p.journey_node_id, p.symptom_category, COUNT(e.id) AS evidence_count, "
            "p.distinct_customers, p.last_seen FROM customer_problems p "
            "JOIN problem_evidence e ON e.problem_id=p.problem_id AND e.run_id=p.run_id "
            f"WHERE p.run_id=?{where} GROUP BY p.problem_id ORDER BY evidence_count DESC, p.last_seen DESC LIMIT 8",
            [run_id, *params],
        )

        source_mix = self.db.query(
            "SELECT source_type AS name, COUNT(*) AS total FROM feedback_records e WHERE e.run_id=?"
            + feedback_where
            + " GROUP BY source_type ORDER BY total DESC",
            [run_id, *feedback_params],
        )
        platform_mix = self.db.query(
            "SELECT platform AS name, COUNT(*) AS total FROM feedback_records e WHERE e.run_id=?"
            + feedback_where
            + " GROUP BY platform ORDER BY total DESC",
            [run_id, *feedback_params],
        )
        rating_mix = self.db.query(
            "SELECT COALESCE(CAST(rating AS TEXT),'none') AS rating, COUNT(*) AS total FROM feedback_records e "
            "WHERE e.run_id=?" + feedback_where + " GROUP BY rating ORDER BY rating",
            [run_id, *feedback_params],
        )
        journey_breakdown = self.db.query(
            "SELECT COALESCE(NULLIF(p.journey_node_id,''),'unmapped') AS journey_node_id, COUNT(*) AS problems, "
            "SUM(p.evidence_count) AS evidence FROM customer_problems p WHERE p.run_id=? "
            "GROUP BY journey_node_id ORDER BY evidence DESC",
            (run_id,),
        )
        latest_run = self.db.query_one(
            "SELECT run_id, status, created_at, finished_at, input_uri, input_generation, source_filename "
            "FROM pipeline_runs WHERE run_id=?",
            (run_id,),
        )
        return {
            "run_id": run_id,
            "latest_run": latest_run,
            "total_feedback": total_feedback,
            "total_insights": total_insights,
            "total_problems": total_problems,
            "unmapped_problems": unmapped,
            "synthetic": bool(synthetic),
            "trend": trend,
            "sentiment_by_journey": sentiment_by_journey,
            "top_problems": top_problems,
            "source_mix": source_mix,
            "platform_mix": platform_mix,
            "rating_mix": rating_mix,
            "journey_breakdown": journey_breakdown,
        }

    def filters_options(self, run_id: str | None = None) -> dict[str, Any]:
        run_id = self.resolve_run_id(run_id)
        if not run_id:
            return {"sources": [], "platforms": [], "journeys": [], "date_range": {}}
        sources = [row["source_type"] for row in self.db.query(
            "SELECT DISTINCT source_type FROM feedback_records WHERE run_id=? ORDER BY source_type", (run_id,)
        )]
        platforms = [row["platform"] for row in self.db.query(
            "SELECT DISTINCT platform FROM feedback_records WHERE run_id=? ORDER BY platform", (run_id,)
        )]
        journeys = self.db.query(
            "SELECT node_id, display_name, parent_id, node_type FROM taxonomy_nodes WHERE version="
            "(SELECT taxonomy_version FROM pipeline_runs WHERE run_id=?) ORDER BY display_name",
            (run_id,),
        )
        date_range = self.db.query_one(
            "SELECT MIN(submitted_at) AS min_date, MAX(submitted_at) AS max_date FROM feedback_records WHERE run_id=?",
            (run_id,),
        )
        return {"sources": sources, "platforms": platforms, "journeys": journeys, "date_range": date_range}

    def list_problems(
        self,
        run_id: str | None = None,
        search: str | None = None,
        journey: str | None = None,
        status: str | None = None,
        sort: str = "evidence",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        run_id = self.resolve_run_id(run_id)
        if not run_id:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        clauses = ["p.run_id=?"]
        params: list[Any] = [run_id]
        if search:
            clauses.append("(p.title LIKE ? OR p.problem_statement LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if journey:
            clauses.append("(p.journey_node_id=? OR p.journey_node_id LIKE ?)")
            params.extend([journey, journey + ".%"])
        if status:
            clauses.append("p.lifecycle_status=?")
            params.append(status)
        where = " AND ".join(clauses)
        total = self.db.scalar(f"SELECT COUNT(*) FROM customer_problems p WHERE {where}", params) or 0
        order = {
            "evidence": "p.evidence_count DESC, p.last_seen DESC",
            "recent": "p.last_seen DESC, p.evidence_count DESC",
            "negative": "p.negative_count DESC, p.evidence_count DESC",
            "title": "p.title ASC",
        }.get(sort, "p.evidence_count DESC")
        offset = max(0, (page - 1) * page_size)
        items = self.db.query(
            "SELECT p.problem_id, p.title, p.problem_statement, p.customer_intent, p.aspect, p.symptom_category, "
            "p.journey_node_id, p.lifecycle_status, p.evidence_count, p.distinct_customers, p.negative_count, "
            "p.first_seen, p.last_seen, p.cluster_id, "
            "(SELECT display_name FROM taxonomy_nodes t WHERE t.node_id=p.journey_node_id ORDER BY t.version DESC LIMIT 1) "
            "AS journey_name FROM customer_problems p "
            f"WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_problem(self, problem_id: str) -> dict[str, Any] | None:
        problem = self.db.query_one("SELECT * FROM customer_problems WHERE problem_id=?", (problem_id,))
        if not problem:
            return None
        problem["mappings"] = self.db.query(
            "SELECT m.*, t.display_name, t.description AS node_description FROM problem_mappings m "
            "LEFT JOIN taxonomy_nodes t ON t.node_id=m.node_id AND t.version=m.taxonomy_version "
            "WHERE m.problem_id=? ORDER BY m.mapping_type, m.confidence DESC",
            (problem_id,),
        )
        problem["evidence"] = self.db.query(
            "SELECT feedback_id, evidence_span, submitted_at, source_type, source_channel, platform, rating, "
            "synthetic_customer_ref FROM problem_evidence WHERE problem_id=? ORDER BY submitted_at DESC LIMIT 100",
            (problem_id,),
        )
        problem["insights"] = self.db.query(
            "SELECT feedback_id, insight_id, customer_intent, aspect, intents_json, aspects_json, "
            "reported_problem, reported_symptom, sentiment, sentiment_score, emotion, customer_effort, "
            "reported_outcome, evidence_span, language, technical_root_cause, evidence_verified, "
            "field_confidence_json, human_review_status, confidence FROM extracted_insights WHERE feedback_id IN "
            "(SELECT feedback_id FROM problem_evidence WHERE problem_id=?) ORDER BY confidence DESC LIMIT 200",
            (problem_id,),
        )
        for insight in problem["insights"]:
            insight["intents"] = loads(insight.pop("intents_json", None), [])
            insight["aspects"] = loads(insight.pop("aspects_json", None), [])
            insight["field_confidence"] = loads(insight.pop("field_confidence_json", None), {})
        insights_by_feedback: dict[str, list[dict[str, Any]]] = {}
        for insight in problem["insights"]:
            insights_by_feedback.setdefault(str(insight.get("feedback_id")), []).append(insight)
        for evidence in problem["evidence"]:
            evidence["insights"] = insights_by_feedback.get(str(evidence.get("feedback_id")), [])
        problem["reviews"] = self.db.query(
            "SELECT reviewer, decision, note, created_at FROM review_decisions WHERE entity_type='problem' "
            "AND entity_id=? ORDER BY created_at DESC",
            (problem_id,),
        )
        return problem

    def _record_human_review(
        self,
        entity_type: str,
        entity_id: str,
        reviewer: str,
        decision: str,
        note: str,
        original_value: str | None = None,
        corrected_value: str | None = None,
    ) -> None:
        self.db.insert(
            "human_review_decisions",
            {
                "review_id": "HR-" + uuid.uuid4().hex[:16],
                "entity_type": entity_type,
                "entity_id": entity_id,
                "reviewer": reviewer,
                "decision": decision,
                "original_value": original_value,
                "corrected_value": corrected_value,
                "note": note,
                "methodology_version": None,
                "created_at": now_iso(),
            },
        )

    def review_problem(self, problem_id: str, reviewer: str, decision: str, note: str, new_title: str | None) -> None:
        status_map = {
            "accept": "accepted",
            "reject": "rejected",
            "merge": "merged",
            "split": "split",
            "rename": "accepted",
            "mark_in_review": "in_review",
            "deprecate": "deprecated",
        }
        status = status_map.get(decision, "in_review")
        if new_title and decision == "rename":
            self.db.execute(
                "UPDATE customer_problems SET title=?, lifecycle_status=?, updated_at=? WHERE problem_id=?",
                (new_title, status, now_iso(), problem_id),
            )
        else:
            self.db.execute(
                "UPDATE customer_problems SET lifecycle_status=?, updated_at=? WHERE problem_id=?",
                (status, now_iso(), problem_id),
            )
        self.db.insert(
            "review_decisions",
            {
                "entity_type": "problem",
                "entity_id": problem_id,
                "reviewer": reviewer,
                "decision": decision,
                "note": note,
                "created_at": now_iso(),
            },
        )
        self._record_human_review("problem", problem_id, reviewer, decision, note, corrected_value=new_title)
        self.audit(reviewer, "problem_review", "problem", problem_id, {"decision": decision, "note": note})

    def travel_metadata(self, run_id: str | None = None) -> dict[str, Any]:
        run_id = self.resolve_run_id(run_id)
        if not run_id:
            return {"run_id": None, "taxonomy_version": None, "model_version": None, "node_counts": []}
        run = self.db.query_one(
            "SELECT taxonomy_version, model_version, code_version, schema_version FROM pipeline_runs WHERE run_id=?",
            (run_id,),
        )
        counts = self.db.query(
            "SELECT p.journey_node_id, COUNT(*) AS problems, SUM(p.evidence_count) AS evidence "
            "FROM customer_problems p WHERE p.run_id=? GROUP BY p.journey_node_id",
            (run_id,),
        )
        return {**(run or {}), "run_id": run_id, "node_counts": counts}

    def proposals(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.db.query(
                "SELECT * FROM taxonomy_proposals WHERE status=? ORDER BY created_at DESC", (status,)
            )
        return self.db.query("SELECT * FROM taxonomy_proposals ORDER BY created_at DESC")

    def review_proposal(self, proposal_id: str, reviewer: str, decision: str, note: str) -> None:
        self.db.execute(
            "UPDATE taxonomy_proposals SET status=? WHERE proposal_id=?",
            ("approved" if decision == "approve" else "rejected", proposal_id),
        )
        self._record_human_review("taxonomy_proposal", proposal_id, reviewer, decision, note)
        self.audit(reviewer, "taxonomy_proposal_review", "taxonomy_proposal", proposal_id, {"decision": decision, "note": note})

    # ---------------------------------------------------------------- backlog
    def create_backlog_upload(
        self, upload_id: str, tenant_id: str, filename: str, source_uri: str, generation: str,
        sha256: str, size_bytes: int, status: str, total_rows: int, valid_rows: int,
        invalid_rows: int, errors: list[dict[str, Any]], warnings: list[str], items: list[dict[str, Any]],
    ) -> None:
        now = now_iso()
        object_key = source_uri.replace("local://", "").replace("gs://", "", 1)
        self.db.insert(
            "backlog_uploads",
            {
                "upload_id": upload_id,
                "tenant_id": tenant_id,
                "filename": filename,
                "object_key": object_key,
                "source_uri": source_uri,
                "generation": generation,
                "sha256": sha256,
                "size_bytes": size_bytes,
                "status": status,
                "total_rows": total_rows,
                "valid_rows": valid_rows,
                "invalid_rows": invalid_rows,
                "errors_json": dumps(errors),
                "warnings_json": dumps(warnings),
                "created_at": now,
                "updated_at": now,
            },
        )
        self.db.executemany(
            "INSERT OR REPLACE INTO backlog_items (item_pk, upload_id, backlog_id, row_number, title, description, "
            "acceptance_criteria, product_area, priority, business_goal, source_system, structured_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"{upload_id}:{item['backlog_id']}",
                    upload_id,
                    item["backlog_id"],
                    item["row_number"],
                    item["title"],
                    item["description"],
                    item.get("acceptance_criteria", ""),
                    item.get("product_area"),
                    item.get("priority"),
                    item.get("business_goal"),
                    item.get("source_system"),
                    dumps(item.get("structured")),
                    now,
                )
                for item in items
            ],
        )

    def get_backlog_upload(self, upload_id: str) -> dict[str, Any] | None:
        upload = self.db.query_one("SELECT * FROM backlog_uploads WHERE upload_id=?", (upload_id,))
        if not upload:
            return None
        upload["errors"] = loads(upload.pop("errors_json", None), [])
        upload["warnings"] = loads(upload.pop("warnings_json", None), [])
        upload["items"] = self.db.query(
            "SELECT backlog_id, row_number, title, description, acceptance_criteria, product_area, priority, "
            "business_goal, source_system FROM backlog_items WHERE upload_id=? ORDER BY row_number",
            (upload_id,),
        )
        upload["validation_runs"] = self.db.query(
            "SELECT run_id, status, report_id, created_at, finished_at FROM validation_runs WHERE upload_id=? "
            "ORDER BY created_at DESC",
            (upload_id,),
        )
        return upload

    def list_backlog_uploads(self, limit: int = 25) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM backlog_uploads ORDER BY created_at DESC LIMIT ?", (limit,))
        for row in rows:
            row["errors"] = loads(row.pop("errors_json", None), [])
            row["warnings"] = loads(row.pop("warnings_json", None), [])
        return rows

    def backlog_items(self, upload_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM backlog_items WHERE upload_id=? ORDER BY row_number", (upload_id,)
        )

    def create_validation_run(self, run_id: str, upload_id: str) -> None:
        self.db.insert(
            "validation_runs",
            {
                "run_id": run_id,
                "upload_id": upload_id,
                "status": "queued",
                "stage_json": dumps([{"stage": "module_f_normalise", "status": "pending"}, {"stage": "module_g_validate", "status": "pending"}]),
                "created_at": now_iso(),
            },
        )
        self.db.execute("UPDATE backlog_uploads SET status='validating', updated_at=? WHERE upload_id=?", (now_iso(), upload_id))

    def update_validation_run(self, run_id: str, status: str, stage_json: list[dict[str, Any]] | None = None, report_id: str | None = None, error: str | None = None) -> None:
        fields: dict[str, Any] = {"status": status, "error": error}
        if stage_json is not None:
            fields["stage_json"] = dumps(stage_json)
        if report_id:
            fields["report_id"] = report_id
        if status in ("completed", "failed"):
            fields["finished_at"] = now_iso()
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.db.execute(
            f"UPDATE validation_runs SET {assignments} WHERE run_id=?",
            [*fields.values(), run_id],
        )

    def get_validation_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.db.query_one("SELECT * FROM validation_runs WHERE run_id=?", (run_id,))
        if not run:
            return None
        run["stages"] = loads(run.pop("stage_json", None), [])
        return run

    def save_model_execution(
        self,
        run_id: str,
        stage: str,
        provider: str,
        model_id: str,
        prompt_version: str | None,
        input_count: int,
        output_count: int,
        status: str = "succeeded",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        self.db.insert(
            "model_execution_history",
            {
                "execution_id": "ME-" + uuid.uuid4().hex[:16],
                "run_id": run_id,
                "stage": stage,
                "provider": provider,
                "model_id": model_id,
                "prompt_version": prompt_version,
                "input_count": input_count,
                "output_count": output_count,
                "status": status,
                "error": error,
                "metadata_json": dumps(metadata or {}),
                "started_at": started_at,
                "finished_at": finished_at or now_iso(),
            },
        )

    def save_measurement(self, run_id: str, measurement: Any, methodology_version: str) -> None:
        if measurement.daily:
            self.db.executemany(
                "INSERT OR REPLACE INTO problem_metrics_daily (run_id, problem_id, day, metric_name, metric_value, "
                "unit, status, methodology_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["problem_id"],
                        item["day"],
                        item["metric_name"],
                        item.get("metric_value"),
                        item.get("unit"),
                        item.get("status", "OK"),
                        methodology_version,
                    )
                    for item in measurement.daily
                ],
            )
        if measurement.snapshots:
            self.db.executemany(
                "INSERT OR REPLACE INTO problem_measurement_snapshots (snapshot_id, run_id, problem_id, metric_name, "
                "metric_value, metric_text_value, unit, status, calculation_method, measurement_window_start, "
                "measurement_window_end, input_record_count, source_availability, quality_indicator, calculated_at, "
                "methodology_version, dimensions_json, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "MS-" + uuid.uuid4().hex[:16],
                        run_id,
                        item["problem_id"],
                        item["metric_name"],
                        item.get("metric_value"),
                        None,
                        item.get("unit"),
                        item["status"],
                        item.get("calculation_method"),
                        item.get("window_start"),
                        item.get("window_end"),
                        item.get("input_record_count", 0),
                        item.get("source_availability", "available"),
                        item.get("quality_indicator"),
                        now_iso(),
                        methodology_version,
                        dumps(item.get("dimensions") or {}),
                        dumps(item.get("metadata") or {}),
                    )
                    for item in measurement.snapshots
                ],
            )

    def save_priorities(self, run_id: str, result: Any) -> None:
        now = now_iso()
        version = result.scores[0]["methodology_version"] if result.scores else "priority-1.0.0"
        self.db.insert(
            "scoring_methodology_versions",
            {
                "version": version,
                "description": "Transparent weighted prioritisation of customer problems.",
                "weights_json": dumps(result.weights),
                "created_at": now,
            },
            replace=True,
        )
        if not result.scores:
            return
        self.db.executemany(
            "INSERT OR REPLACE INTO problem_priority_snapshots (snapshot_id, run_id, problem_id, "
            "customer_impact_score, business_risk_score, operational_impact_score, trend_score, strategic_score, "
            "priority_score, rank, escalation_status, escalation_reasons_json, missing_metrics_json, "
            "supporting_evidence_json, methodology_version, measurement_window_start, measurement_window_end, "
            "calculated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "PS-" + uuid.uuid4().hex[:16],
                    run_id,
                    item["problem_id"],
                    item["customer_impact_score"],
                    item["business_risk_score"],
                    item["operational_impact_score"],
                    item["trend_score"],
                    item["strategic_score"],
                    item["priority_score"],
                    item["rank"],
                    item["escalation_status"],
                    dumps(item["escalation_reasons"]),
                    dumps(item["missing_metrics"]),
                    dumps(item["supporting_evidence"]),
                    item["methodology_version"],
                    item.get("measurement_window_start"),
                    item.get("measurement_window_end"),
                    now,
                )
                for item in result.scores
            ],
        )

    def replace_mds_result(self, run_id: str, result: Any) -> str:
        """Persist one MDS snapshot per run, replacing any previous snapshot."""
        mds_id = "MDS-" + uuid.uuid4().hex[:16]
        created_at = now_iso()
        self.db.execute("DELETE FROM problem_mds_neighbors WHERE run_id=?", (run_id,))
        self.db.execute("DELETE FROM problem_mds_points WHERE run_id=?", (run_id,))
        self.db.execute("DELETE FROM problem_mds_runs WHERE run_id=?", (run_id,))
        self.db.execute("DELETE FROM problem_theme_vectors WHERE run_id=?", (run_id,))
        self.db.insert(
            "problem_mds_runs",
            {
                "mds_id": mds_id,
                "run_id": run_id,
                "status": result.status,
                "methodology_version": getattr(result, "methodology_version", "mds-1.0.0"),
                "embedding_model": result.embedding_model,
                "distance_metric": (result.params or {}).get("distance_metric", "cosine"),
                "n_themes": len(result.points),
                "stress": result.stress,
                "normalized_stress": result.normalized_stress,
                "stress_status": result.stress_status,
                "params_json": dumps(result.params),
                "created_at": created_at,
            },
        )
        if result.theme_vectors:
            self.db.executemany(
                "INSERT OR REPLACE INTO problem_theme_vectors "
                "(run_id, problem_id, model_name, dimensions, vector_json, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["problem_id"],
                        item["model_name"],
                        item["dimensions"],
                        item["vector_json"],
                        item["source"],
                        created_at,
                    )
                    for item in result.theme_vectors
                ],
            )
        if result.points:
            self.db.executemany(
                "INSERT OR REPLACE INTO problem_mds_points "
                "(mds_id, run_id, problem_id, x, y, display_x, display_y, vector_source, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        mds_id,
                        run_id,
                        item["problem_id"],
                        item["x"],
                        item["y"],
                        item["display_x"],
                        item["display_y"],
                        item.get("vector_source"),
                        dumps({}),
                    )
                    for item in result.points
                ],
            )
        if result.neighbors:
            self.db.executemany(
                "INSERT OR REPLACE INTO problem_mds_neighbors "
                "(mds_id, run_id, problem_id, neighbor_problem_id, rank, cosine_similarity, cosine_distance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        mds_id,
                        run_id,
                        item["problem_id"],
                        item["neighbor_problem_id"],
                        item["rank"],
                        item["cosine_similarity"],
                        item["cosine_distance"],
                    )
                    for item in result.neighbors
                ],
            )
        return mds_id

    def latest_mds(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM problem_mds_runs WHERE run_id=? ORDER BY created_at DESC LIMIT 1", (run_id,)
        )
        if not row:
            return None
        row["params"] = loads(row.pop("params_json", None), {})
        return row

    def mds_points(self, mds_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM problem_mds_points WHERE mds_id=? ORDER BY problem_id", (mds_id,))

    def mds_neighbors(self, mds_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM problem_mds_neighbors WHERE mds_id=? ORDER BY problem_id, rank", (mds_id,)
        )

    def latest_coverage_for_feedback_run(self, run_id: str) -> dict[str, dict[str, Any]]:
        """Return the latest backlog coverage per problem for a feedback run.

        Validation reports store the feedback run id inside the report payload;
        parse recent reports rather than adding a cross-store foreign key.
        """
        reports = self.db.query(
            "SELECT report_id, report_json FROM validation_reports ORDER BY created_at DESC LIMIT 100"
        )
        for report in reports:
            payload = loads(report.get("report_json"), {})
            if payload.get("feedback_run_id") != run_id:
                continue
            rows = self.db.query(
                "SELECT problem_id, coverage_type, relationship FROM backlog_coverage_matrix "
                "WHERE report_id=? AND problem_id IS NOT NULL",
                (report["report_id"],),
            )
            rank = {
                "full": 0,
                "partial": 1,
                "related": 2,
                "needs_review": 3,
                "uncovered": 4,
                "out_of_scope": 5,
            }
            coverage: dict[str, dict[str, Any]] = {}
            for row in rows:
                problem_id = row["problem_id"]
                existing = coverage.get(problem_id)
                if existing is None or rank.get(row["coverage_type"], 9) < rank.get(existing["coverage_status"], 9):
                    coverage[problem_id] = {
                        "coverage_status": row["coverage_type"],
                        "coverage_relationship": row["relationship"],
                        "coverage_report_id": report["report_id"],
                    }
            return coverage
        return {}

    def save_report(self, report_id: str, upload_id: str, run_id: str, summary: dict[str, Any], report: dict[str, Any], findings: list[dict[str, Any]]) -> None:
        self.db.insert(
            "validation_reports",
            {
                "report_id": report_id,
                "upload_id": upload_id,
                "run_id": run_id,
                "summary_json": dumps(summary),
                "report_json": dumps(report),
                "reviewer_status": "pending",
                "created_at": now_iso(),
            },
        )
        self.db.executemany(
            "INSERT OR REPLACE INTO validation_findings (finding_id, report_id, backlog_id, problem_id, relationship, "
            "rationale, alignment_score, supporting_feedback_count, evidence_json, journey_node_id, ac_coverage, "
            "ac_gaps_json, uncertainty) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item["finding_id"],
                    report_id,
                    item["backlog_id"],
                    item.get("problem_id"),
                    item["relationship"],
                    item.get("rationale"),
                    item.get("alignment_score", 0),
                    item.get("supporting_feedback_count", 0),
                    dumps(item.get("evidence", [])),
                    item.get("journey_node_id"),
                    item.get("ac_coverage", 0),
                    dumps(item.get("ac_gaps", [])),
                    item.get("uncertainty"),
                )
                for item in findings
            ],
        )

    def save_coverage_matrix(self, report_id: str, report: dict[str, Any]) -> None:
        created_at = now_iso()
        rows: list[tuple[Any, ...]] = []
        candidate_rows: list[tuple[Any, ...]] = []
        for index, item in enumerate(report.get("backlog_items", []), start=1):
            findings = item.get("findings") or []
            best = findings[0] if findings else None
            relationship = best["relationship"] if best else "NO_CLEAR_RELATIONSHIP"
            coverage_type = {
                "ADDRESSES": "full",
                "PARTIALLY_ADDRESSES": "partial",
                "RELATED_BUT_NOT_SOLVING": "related",
                "NEEDS_REVIEW": "needs_review",
                "CONTRADICTS_OR_OUT_OF_SCOPE": "out_of_scope",
                "COVERS": "full",
                "PARTIALLY_COVERS": "partial",
                "RELATED": "related",
                "NOT_COVERED": "uncovered",
            }.get(relationship, "uncovered")
            rows.append(
                (
                    report_id,
                    item["backlog_id"],
                    best.get("problem_id") if best else None,
                    relationship,
                    coverage_type,
                    best.get("alignment_score", 0.0) if best else 0.0,
                    item.get("priority_alignment_score"),
                    item.get("backlog_priority_rank", index),
                    created_at,
                )
            )
            for rank, finding in enumerate(findings[:10], start=1):
                problem_id = finding.get("problem_id")
                if not problem_id:
                    continue
                candidate_rows.append(
                    (
                        f"BPC-{uuid.uuid4().hex[:16]}",
                        report_id,
                        report.get("validation_run_id"),
                        item["backlog_id"],
                        problem_id,
                        finding.get("embedding_similarity"),
                        finding.get("sparse_similarity"),
                        finding.get("alignment_score", 0.0),
                        finding.get("fused_similarity"),
                        rank,
                        dumps(
                            {
                                "relationship": finding.get("relationship"),
                                "rationale": finding.get("rationale"),
                                "factor_id": finding.get("factor_id"),
                                "factor_name": finding.get("factor_name"),
                                "embedding_distance": finding.get("embedding_distance"),
                            }
                        ),
                        created_at,
                    )
                )
        if rows:
            self.db.executemany(
                "INSERT INTO backlog_coverage_matrix (report_id, backlog_id, problem_id, relationship, coverage_type, "
                "alignment_score, priority_score, priority_rank, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        if candidate_rows:
            self.db.executemany(
                "INSERT OR REPLACE INTO backlog_problem_candidates (candidate_id, report_id, validation_run_id, "
                "backlog_id, problem_id, dense_score, sparse_score, fused_score, rerank_score, rank, reasons_json, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                candidate_rows,
            )

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM validation_reports WHERE report_id=?", (report_id,))
        if not row:
            return None
        report = loads(row.pop("report_json", None), {})
        row["summary"] = loads(row.pop("summary_json", None), {})
        row["report"] = report
        row["reviews"] = self.db.query(
            "SELECT reviewer, decision, note, created_at FROM report_reviews WHERE report_id=? ORDER BY created_at DESC",
            (report_id,),
        )
        return row

    def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT r.report_id, r.upload_id, r.run_id, r.reviewer_status, r.created_at, u.filename "
            "FROM validation_reports r LEFT JOIN backlog_uploads u ON u.upload_id=r.upload_id "
            "ORDER BY r.created_at DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            summary = self.db.query_one("SELECT summary_json FROM validation_reports WHERE report_id=?", (row["report_id"],))
            row["summary"] = loads(summary.get("summary_json") if summary else None, {})
        return rows

    def review_report(self, report_id: str, reviewer: str, decision: str, note: str, backlog_id: str | None) -> None:
        self.db.insert(
            "report_reviews",
            {
                "report_id": report_id,
                "backlog_id": backlog_id,
                "reviewer": reviewer,
                "decision": decision,
                "note": note,
                "created_at": now_iso(),
            },
        )
        self.db.execute("UPDATE validation_reports SET reviewer_status=? WHERE report_id=?", (decision, report_id))
        self._record_human_review("validation_report", report_id, reviewer, decision, note)
        self.audit(reviewer, "report_review", "validation_report", report_id, {"decision": decision, "note": note})

    # ------------------------------------------------------ problem dimensions
    def save_feature_snapshot(self, snapshot_id: str, build: Any) -> None:
        rows = [
            {
                "snapshot_id": snapshot_id,
                "feedback_run_id": build.feedback_run_id,
                "canonical_problem_id": row.problem_id,
                "as_of_date": build.as_of_date,
                "feature_schema_version": build.feature_schema_version,
                "feature_values_json": dumps(row.values),
                "feature_types_json": dumps({spec.name: spec.kind for spec in build.specs}),
                "source_measurement_ids_json": dumps(row.sources),
                "quality_flags_json": dumps(row.quality_flags),
                "created_at": now_iso(),
            }
            for row in build.rows
        ]
        self.db.executemany(
            "INSERT INTO problem_feature_snapshots (snapshot_id, feedback_run_id, canonical_problem_id, as_of_date, "
            "feature_schema_version, feature_values_json, feature_types_json, source_measurement_ids_json, "
            "quality_flags_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    row["snapshot_id"],
                    row["feedback_run_id"],
                    row["canonical_problem_id"],
                    row["as_of_date"],
                    row["feature_schema_version"],
                    row["feature_values_json"],
                    row["feature_types_json"],
                    row["source_measurement_ids_json"],
                    row["quality_flags_json"],
                    row["created_at"],
                ]
                for row in rows
            ],
        )

    def get_feature_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        rows = self.db.query(
            "SELECT * FROM problem_feature_snapshots WHERE snapshot_id=? ORDER BY canonical_problem_id",
            (snapshot_id,),
        )
        if not rows:
            return None
        for row in rows:
            row["features"] = loads(row.pop("feature_values_json", None), {})
            row["feature_types"] = loads(row.pop("feature_types_json", None), {})
            row["source_measurement_ids"] = loads(row.pop("source_measurement_ids_json", None), {})
            row["quality_flags"] = loads(row.pop("quality_flags_json", None), [])
        return {"snapshot_id": snapshot_id, "feedback_run_id": rows[0]["feedback_run_id"], "rows": rows}

    def create_dimension_run(self, values: dict[str, Any]) -> None:
        self.db.insert("dimension_analysis_runs", values)

    def update_dimension_run(self, run_id: str, **fields: Any) -> None:
        for key in (
            "parameters",
            "diagnostics",
            "feature_quality",
            "feature_dictionary",
            "selected_features",
            "excluded_features",
            "configuration",
        ):
            if key in fields:
                fields[f"{key}_json"] = dumps(fields.pop(key))
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.db.execute(
            f"UPDATE dimension_analysis_runs SET {assignments} WHERE run_id=?",
            [*fields.values(), run_id],
        )

    def get_dimension_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM dimension_analysis_runs WHERE run_id=?", (run_id,))
        if not row:
            return None
        row["parameters"] = loads(row.pop("parameters_json", None), {})
        row["diagnostics"] = loads(row.pop("diagnostics_json", None), {})
        row["feature_quality"] = loads(row.pop("feature_quality_json", None), [])
        row["feature_dictionary"] = loads(row.pop("feature_dictionary_json", None), [])
        row["selected_features"] = loads(row.pop("selected_features_json", None), [])
        row["excluded_features"] = loads(row.pop("excluded_features_json", None), [])
        row["configuration"] = loads(row.pop("configuration_json", None), {})
        row["definitions"] = self.get_dimension_definitions(run_id)
        return row

    def list_dimension_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT run_id, method, method_version, method_library_version, input_snapshot_id, feedback_run_id, "
            "feature_schema_version, status, stage, code_version, created_at, started_at, completed_at, error "
            "FROM dimension_analysis_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    def find_reusable_dimension_run(
        self,
        feedback_run_id: str,
        feature_schema_version: str,
        method: str,
    ) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM dimension_analysis_runs WHERE feedback_run_id=? AND feature_schema_version=? "
            "AND method=? AND status NOT IN ('FAILED', 'REJECTED') ORDER BY created_at DESC LIMIT 1",
            (feedback_run_id, feature_schema_version, method),
        )

    def save_dimension_results(
        self,
        run_id: str,
        definitions: list[dict[str, Any]],
        contributions: list[dict[str, Any]],
        scores: list[dict[str, Any]],
        memberships: list[dict[str, Any]],
        trends: list[dict[str, Any]],
        equations: list[dict[str, Any]] | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM dimension_definitions WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM dimension_variable_contributions WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM problem_dimension_scores WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM problem_dimension_equations WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM dimension_problem_membership WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM dimension_trends WHERE run_id=?", (run_id,))
            conn.executemany(
                "INSERT INTO dimension_definitions (run_id, dimension_id, dimension_number, analyst_name, "
                "proposed_label, description, business_interpretation, interpretation_status, model_version, "
                "top_variables_json, representative_problem_ids_json, review_status, nomenclature_source, "
                "prompt_version, model_name, llm_analysis_run_id, taxonomy_version, generated_at, short_name, "
                "banking_domain, journey_scope, core_customer_experience, supporting_variables_json, "
                "supporting_categories_json, contradictory_problem_ids_json, distinguishing_characteristics, "
                "nomenclature_status, confidence, confidence_explanation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["dimension_id"],
                        item.get("dimension_number"),
                        item["analyst_name"],
                        item.get("proposed_label"),
                        item.get("description"),
                        item.get("business_interpretation"),
                        item.get("interpretation_status", "DRAFT"),
                        item.get("model_version"),
                        dumps(item.get("top_variables")),
                        dumps(item.get("representative_problem_ids")),
                        item.get("review_status", "DRAFT"),
                        item.get("nomenclature_source"),
                        item.get("prompt_version"),
                        item.get("model_name"),
                        item.get("llm_analysis_run_id"),
                        item.get("taxonomy_version"),
                        item.get("generated_at"),
                        item.get("short_name"),
                        item.get("banking_domain"),
                        item.get("journey_scope"),
                        item.get("core_customer_experience"),
                        dumps(item.get("supporting_variables")),
                        dumps(item.get("supporting_categories")),
                        dumps(item.get("contradictory_problem_ids")),
                        item.get("distinguishing_characteristics"),
                        item.get("nomenclature_status"),
                        item.get("confidence"),
                        item.get("confidence_explanation"),
                    )
                    for item in definitions
                ],
            )
            conn.executemany(
                "INSERT INTO dimension_variable_contributions (run_id, dimension_id, variable_name, category_level, "
                "contribution, coordinate, direction_summary, rank) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["dimension_id"],
                        item["variable_name"],
                        item.get("category_level") or "",
                        item["contribution"],
                        item.get("coordinate"),
                        item.get("direction_summary"),
                        item.get("rank"),
                    )
                    for item in contributions
                ],
            )
            conn.executemany(
                "INSERT INTO problem_dimension_scores (run_id, canonical_problem_id, dimension_id, coordinate, "
                "relative_squared_coordinate_share_pct, coordinate_rank, contribution_metadata_json, score_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["problem_id"],
                        item["dimension_id"],
                        item["coordinate"],
                        item.get("relative_squared_coordinate_share_pct"),
                        item.get("coordinate_rank"),
                        dumps(item.get("contribution_metadata")),
                        item.get("score_status", "OK"),
                    )
                    for item in scores
                ],
            )
            if equations:
                conn.executemany(
                    "INSERT INTO problem_dimension_equations (run_id, canonical_problem_id, equation_text, "
                    "number_of_dimensions, coefficient_representation_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            run_id,
                            item["problem_id"],
                            item["equation_text"],
                            item["number_of_dimensions"],
                            dumps(item.get("coefficient_representation")),
                            now_iso(),
                        )
                        for item in equations
                    ],
                )
            conn.executemany(
                "INSERT INTO dimension_problem_membership (run_id, canonical_problem_id, dimension_id, membership_type, "
                "score, margin, is_ambiguous) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["problem_id"],
                        item["dimension_id"],
                        item["membership_type"],
                        item["score"],
                        item.get("margin"),
                        1 if item.get("is_ambiguous") else 0,
                    )
                    for item in memberships
                ],
            )
            conn.executemany(
                "INSERT INTO dimension_trends (run_id, dimension_id, time_window, metric_name, metric_value, "
                "denominator, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["dimension_id"],
                        item["time_window"],
                        item["metric_name"],
                        item.get("metric_value"),
                        item.get("denominator"),
                        item.get("status", "OK"),
                    )
                    for item in trends
                ],
            )

    def get_dimension_definitions(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM dimension_definitions WHERE run_id=? "
            "ORDER BY COALESCE(dimension_number, 9999), dimension_id",
            (run_id,),
        )
        for row in rows:
            row["top_variables"] = loads(row.pop("top_variables_json", None), [])
            row["representative_problem_ids"] = loads(row.pop("representative_problem_ids_json", None), [])
            row["supporting_variables"] = loads(row.pop("supporting_variables_json", None), [])
            row["supporting_categories"] = loads(row.pop("supporting_categories_json", None), [])
            row["contradictory_problem_ids"] = loads(row.pop("contradictory_problem_ids_json", None), [])
        return rows

    def review_dimension(
        self,
        run_id: str,
        dimension_id: str,
        reviewer: str,
        decision: str,
        name: str | None,
        description: str | None,
        note: str,
    ) -> dict[str, Any] | None:
        existing = self.db.query_one(
            "SELECT * FROM dimension_definitions WHERE run_id=? AND dimension_id=?",
            (run_id, dimension_id),
        )
        if not existing:
            return None
        status_map = {
            "approve": "APPROVED",
            "rename": "APPROVED",
            "reject": "REJECTED",
            "request_revision": "DRAFT",
        }
        fields: dict[str, Any] = {
            "review_status": status_map[decision],
            "reviewer": reviewer,
            "review_note": note,
            "reviewed_at": now_iso(),
        }
        if name:
            fields["analyst_name"] = name
        if description is not None:
            fields["description"] = description
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.db.execute(
            f"UPDATE dimension_definitions SET {assignments} WHERE run_id=? AND dimension_id=?",
            [*fields.values(), run_id, dimension_id],
        )
        self._record_human_review(
            "problem_dimension",
            f"{run_id}:{dimension_id}",
            reviewer,
            decision,
            note,
            original_value=existing.get("analyst_name"),
            corrected_value=name,
        )
        self.audit(
            reviewer,
            "dimension_review",
            "dimension_definition",
            f"{run_id}:{dimension_id}",
            {"decision": decision, "note": note},
        )
        return self.get_dimension_definitions(run_id) and next(
            (item for item in self.get_dimension_definitions(run_id) if item["dimension_id"] == dimension_id),
            None,
        )

    def publish_dimension_run(self, run_id: str, published_by: str, note: str) -> str:
        publication_id = f"DPUB-{uuid.uuid4().hex[:16]}"
        self.db.insert(
            "dimension_publications",
            {
                "publication_id": publication_id,
                "run_id": run_id,
                "action": "publish",
                "published_by": published_by,
                "note": note,
                "created_at": now_iso(),
            },
        )
        self.update_dimension_run(run_id, status="PUBLISHED")
        self.audit(
            published_by,
            "dimension_publish",
            "dimension_run",
            run_id,
            {"publication_id": publication_id, "note": note},
        )
        return publication_id

    def latest_dimension_publication(self) -> dict[str, Any] | None:
        publication = self.db.query_one(
            "SELECT * FROM dimension_publications WHERE action='publish' ORDER BY created_at DESC, rowid DESC LIMIT 1"
        )
        if not publication:
            return None
        run = self.get_dimension_run(publication["run_id"])
        return {"publication": publication, "run": run} if run else None

    def get_dimension_contributions(self, run_id: str, dimension_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        where = "run_id=?"
        if dimension_id:
            where += " AND dimension_id=?"
            params.append(dimension_id)
        return self.db.query(
            f"SELECT * FROM dimension_variable_contributions WHERE {where} ORDER BY dimension_id, rank",
            params,
        )

    def save_dimension_narrative_serialization(
        self,
        run_id: str,
        payload: dict[str, Any],
        *,
        status: str,
        prompt_version: str,
        agent_version: str | None,
        model_name: str | None,
        content_hash: str,
        error: str | None = None,
    ) -> str:
        serialization_id = f"NAR-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.db.insert(
            "dimension_narrative_serializations",
            {
                "serialization_id": serialization_id,
                "run_id": run_id,
                "status": status,
                "prompt_version": prompt_version,
                "agent_version": agent_version,
                "model_name": model_name,
                "content_hash": content_hash,
                "payload_json": dumps(payload),
                "error": error,
                "created_at": now_iso(),
            },
        )
        return serialization_id

    def get_latest_dimension_narrative_serialization(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM dimension_narrative_serializations WHERE run_id=? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        if not row:
            return None
        row["payload"] = loads(row.pop("payload_json", None), {})
        return row

    def get_latest_completed_dimension_narrative_serialization(
        self, run_id: str
    ) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM dimension_narrative_serializations WHERE run_id=? AND status='COMPLETED' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        if not row:
            return None
        row["payload"] = loads(row.pop("payload_json", None), {})
        return row

    def latest_dimension_narrative_nomenclature(self, run_id: str) -> list[dict[str, Any]]:
        record = self.get_latest_completed_dimension_narrative_serialization(run_id)
        if not record:
            return []
        rows: list[dict[str, Any]] = []
        for factor in (record.get("payload") or {}).get("factors") or []:
            dimension_id = str(factor.get("dimension_id") or "")
            factor_id = str(factor.get("factor_id") or "")
            if not dimension_id and factor_id.startswith("F") and factor_id[1:].isdigit():
                dimension_id = f"D{factor_id[1:]}"
            if not dimension_id:
                continue
            rows.append(
                {
                    "dimension_id": dimension_id,
                    "factor_id": factor_id or None,
                    "factor_name": factor.get("name"),
                    "short_name": factor.get("short_name"),
                    "description": factor.get("description"),
                    "business_interpretation": factor.get("business_interpretation"),
                    "source": "dimension_narrative_serialization",
                    "serialization_id": record.get("serialization_id"),
                    "model_name": record.get("model_name"),
                    "prompt_version": record.get("prompt_version"),
                }
            )
        return rows

    def get_dimension_scores(self, run_id: str, dimension_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM problem_dimension_scores WHERE run_id=? AND dimension_id=? ORDER BY coordinate DESC",
            (run_id, dimension_id),
        )
        for row in rows:
            row["contribution_metadata"] = loads(row.pop("contribution_metadata_json", None), {})
        return rows

    def get_dimension_trends(self, run_id: str, dimension_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        where = "run_id=?"
        if dimension_id:
            where += " AND dimension_id=?"
            params.append(dimension_id)
        return self.db.query(
            f"SELECT * FROM dimension_trends WHERE {where} ORDER BY dimension_id, metric_name",
            params,
        )

    def get_problem_dimension_scores(self, run_id: str, problem_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT s.*, d.analyst_name, d.description, d.review_status, "
            "m.membership_type, m.margin, m.is_ambiguous "
            "FROM problem_dimension_scores s "
            "LEFT JOIN dimension_definitions d ON d.run_id=s.run_id AND d.dimension_id=s.dimension_id "
            "LEFT JOIN dimension_problem_membership m ON m.run_id=s.run_id "
            "AND m.canonical_problem_id=s.canonical_problem_id AND m.dimension_id=s.dimension_id "
            "WHERE s.run_id=? AND s.canonical_problem_id=? ORDER BY ABS(s.coordinate) DESC",
            (run_id, problem_id),
        )
        for row in rows:
            row["contribution_metadata"] = loads(row.pop("contribution_metadata_json", None), {})
        return rows

    def get_dimension_coefficient_matrix(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT s.canonical_problem_id AS problem_id, s.dimension_id, s.coordinate AS coefficient, "
            "s.relative_squared_coordinate_share_pct, s.coordinate_rank, d.dimension_number, "
            "d.analyst_name AS factor_name, d.proposed_label, d.review_status AS factor_review_status "
            "FROM problem_dimension_scores s "
            "LEFT JOIN dimension_definitions d ON d.run_id=s.run_id AND d.dimension_id=s.dimension_id "
            "WHERE s.run_id=? "
            "ORDER BY s.canonical_problem_id, COALESCE(d.dimension_number, 9999), s.dimension_id",
            (run_id,),
        )

    def get_problem_dimension_profile(self, run_id: str, problem_id: str) -> dict[str, Any] | None:
        equation = self.db.query_one(
            "SELECT * FROM problem_dimension_equations WHERE run_id=? AND canonical_problem_id=?",
            (run_id, problem_id),
        )
        scores = self.get_problem_dimension_scores(run_id, problem_id)
        if not scores and not equation:
            return None
        if equation:
            equation["coefficient_representation"] = loads(
                equation.pop("coefficient_representation_json", None), []
            )
        return {
            "run_id": run_id,
            "problem_id": problem_id,
            "equation": equation,
            "coefficients": scores,
        }

    def get_dimension_variables(self, run_id: str, dimension_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        where = "run_id=?"
        if dimension_id:
            where += " AND dimension_id=?"
            params.append(dimension_id)
        return self.db.query(
            f"SELECT * FROM dimension_variable_contributions WHERE {where} ORDER BY dimension_id, rank",
            params,
        )

    # ------------------------------------------------- LLM factor interpretation
    def update_dimension_definition(self, run_id: str, dimension_id: str, **fields: Any) -> None:
        if not fields:
            return
        for key in (
            "top_variables",
            "representative_problem_ids",
            "supporting_variables",
            "supporting_categories",
            "contradictory_problem_ids",
        ):
            if key in fields:
                fields[f"{key}_json"] = dumps(fields.pop(key))
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.db.execute(
            f"UPDATE dimension_definitions SET {assignments} WHERE run_id=? AND dimension_id=?",
            [*fields.values(), run_id, dimension_id],
        )

    def save_problem_interpretation(
        self,
        run_id: str,
        dimension_id: str,
        problem_id: str,
        *,
        status: str,
        observation: dict[str, Any] | None,
        prompt_version: str | None,
        model_name: str | None,
        error: str | None = None,
    ) -> None:
        now = now_iso()
        self.db.execute(
            "INSERT INTO dimension_problem_interpretations (run_id, dimension_id, canonical_problem_id, status, "
            "observation_json, prompt_version, model_name, error, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, dimension_id, canonical_problem_id) DO UPDATE SET status=excluded.status, "
            "observation_json=excluded.observation_json, prompt_version=excluded.prompt_version, "
            "model_name=excluded.model_name, error=excluded.error, updated_at=excluded.updated_at",
            (
                run_id,
                dimension_id,
                problem_id,
                status,
                dumps(observation),
                prompt_version,
                model_name,
                error,
                now,
                now,
            ),
        )

    def get_problem_interpretations(
        self,
        run_id: str,
        dimension_id: str,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [run_id, dimension_id]
        where = "run_id=? AND dimension_id=?"
        if status:
            where += " AND status=?"
            params.append(status)
        rows = self.db.query(
            f"SELECT * FROM dimension_problem_interpretations WHERE {where} "
            "ORDER BY canonical_problem_id",
            params,
        )
        for row in rows:
            row["observation"] = loads(row.pop("observation_json", None), None)
        return rows

    def save_dimension_aggregation(
        self,
        run_id: str,
        dimension_id: str,
        *,
        status: str,
        aggregation: dict[str, Any] | None,
        prompt_version: str | None,
        model_name: str | None,
        error: str | None = None,
    ) -> None:
        now = now_iso()
        self.db.execute(
            "INSERT INTO dimension_evidence_aggregations (run_id, dimension_id, status, aggregation_json, "
            "prompt_version, model_name, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, dimension_id) DO UPDATE SET status=excluded.status, "
            "aggregation_json=excluded.aggregation_json, prompt_version=excluded.prompt_version, "
            "model_name=excluded.model_name, error=excluded.error, updated_at=excluded.updated_at",
            (run_id, dimension_id, status, dumps(aggregation), prompt_version, model_name, error, now, now),
        )

    def get_dimension_aggregation(self, run_id: str, dimension_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM dimension_evidence_aggregations WHERE run_id=? AND dimension_id=?",
            (run_id, dimension_id),
        )
        if not row:
            return None
        row["aggregation"] = loads(row.pop("aggregation_json", None), None)
        return row

    def save_nomenclature_proposal(
        self,
        run_id: str,
        dimension_id: str,
        factor_id: str,
        *,
        status: str,
        proposal: dict[str, Any] | None,
        original_proposal: dict[str, Any] | None = None,
        cross_review: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        prompt_version: str | None,
        model_name: str | None,
    ) -> None:
        now = now_iso()
        self.db.execute(
            "INSERT INTO dimension_nomenclature_proposals (run_id, dimension_id, factor_id, status, proposal_json, "
            "original_proposal_json, cross_review_json, validation_json, prompt_version, model_name, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, dimension_id) DO UPDATE SET factor_id=excluded.factor_id, status=excluded.status, "
            "proposal_json=excluded.proposal_json, original_proposal_json=excluded.original_proposal_json, "
            "cross_review_json=excluded.cross_review_json, validation_json=excluded.validation_json, "
            "prompt_version=excluded.prompt_version, model_name=excluded.model_name, updated_at=excluded.updated_at",
            (
                run_id,
                dimension_id,
                factor_id,
                status,
                dumps(proposal),
                dumps(original_proposal if original_proposal is not None else proposal),
                dumps(cross_review),
                dumps(validation),
                prompt_version,
                model_name,
                now,
                now,
            ),
        )

    def get_nomenclature_proposals(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM dimension_nomenclature_proposals WHERE run_id=? ORDER BY factor_id",
            (run_id,),
        )
        for row in rows:
            row["proposal"] = loads(row.pop("proposal_json", None), None)
            row["original_proposal"] = loads(row.pop("original_proposal_json", None), None)
            row["cross_review"] = loads(row.pop("cross_review_json", None), None)
            row["validation"] = loads(row.pop("validation_json", None), None)
        return rows

    def get_nomenclature_proposal(self, run_id: str, dimension_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM dimension_nomenclature_proposals WHERE run_id=? AND dimension_id=?",
            (run_id, dimension_id),
        )
        if not row:
            return None
        row["proposal"] = loads(row.pop("proposal_json", None), None)
        row["original_proposal"] = loads(row.pop("original_proposal_json", None), None)
        row["cross_review"] = loads(row.pop("cross_review_json", None), None)
        row["validation"] = loads(row.pop("validation_json", None), None)
        return row

    def update_dimension_llm_processing(self, run_id: str, dimension_id: str, **fields: Any) -> None:
        now = now_iso()
        existing = self.db.query_one(
            "SELECT run_id FROM dimension_llm_processing WHERE run_id=? AND dimension_id=?",
            (run_id, dimension_id),
        )
        if existing:
            fields["updated_at"] = now
            assignments = ", ".join(f"{key}=?" for key in fields)
            self.db.execute(
                f"UPDATE dimension_llm_processing SET {assignments} WHERE run_id=? AND dimension_id=?",
                [*fields.values(), run_id, dimension_id],
            )
            return
        values = {
            "run_id": run_id,
            "dimension_id": dimension_id,
            "stage": fields.pop("stage", "QUEUED"),
            "status": fields.pop("status", "QUEUED"),
            "total_problems": fields.pop("total_problems", 0),
            "processed_problems": fields.pop("processed_problems", 0),
            "failed_problems": fields.pop("failed_problems", 0),
            "error": fields.pop("error", None),
            "prompt_version": fields.pop("prompt_version", None),
            "model_name": fields.pop("model_name", None),
            "started_at": fields.pop("started_at", None),
            "completed_at": fields.pop("completed_at", None),
            "updated_at": now,
            **fields,
        }
        self.db.insert("dimension_llm_processing", values)

    def list_dimension_llm_processing(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM dimension_llm_processing WHERE run_id=? ORDER BY dimension_id",
            (run_id,),
        )

    def get_dimension_llm_processing(self, run_id: str, dimension_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM dimension_llm_processing WHERE run_id=? AND dimension_id=?",
            (run_id, dimension_id),
        )

    def get_all_problem_scores(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM problem_dimension_scores WHERE run_id=? "
            "ORDER BY canonical_problem_id, dimension_id",
            (run_id,),
        )
        for row in rows:
            row["contribution_metadata"] = loads(row.pop("contribution_metadata_json", None), {})
        return rows

    def get_run_problems(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM customer_problems WHERE run_id=? ORDER BY problem_id",
            (run_id,),
        )
        for row in rows:
            row["symptoms"] = loads(row.pop("symptoms_json", None), [])
        return rows

    def get_problem_journey_mappings(self, problem_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not problem_ids:
            return {}
        placeholders = ", ".join("?" for _ in problem_ids)
        rows = self.db.query(
            "SELECT * FROM problem_journey_mappings WHERE problem_id IN "
            f"({placeholders}) ORDER BY mapping_confidence DESC",
            problem_ids,
        )
        mappings: dict[str, dict[str, Any]] = {}
        for row in rows:
            mappings.setdefault(row["problem_id"], row)
        return mappings

    def get_taxonomy_nodes(self, version: str | None) -> list[dict[str, Any]]:
        if not version:
            return []
        rows = self.db.query(
            "SELECT * FROM taxonomy_nodes WHERE version=? ORDER BY node_id",
            (version,),
        )
        for row in rows:
            row["synonyms"] = loads(row.pop("synonyms_json", None), [])
            row["aliases"] = loads(row.pop("aliases_json", None), [])
        return rows

    # ------------------------------------------------- problem portfolio narrative
    def latest_usable_dimension_run(self, feedback_run_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM dimension_analysis_runs WHERE feedback_run_id=? "
            "AND status IN ('APPROVED', 'PUBLISHED') "
            "ORDER BY COALESCE(completed_at, created_at) DESC, created_at DESC LIMIT 1",
            (feedback_run_id,),
        )

    def get_mds_run(self, mds_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM problem_mds_runs WHERE mds_id=?", (mds_id,))
        if row:
            row["params"] = loads(row.pop("params_json", None), {})
        return row

    def create_portfolio_run(self, values: dict[str, Any]) -> None:
        self.db.insert("problem_portfolio_analysis_runs", values)

    def update_portfolio_run(self, run_id: str, **fields: Any) -> None:
        for key in ("parameters", "summary"):
            if key in fields:
                fields[f"{key}_json"] = dumps(fields.pop(key))
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.db.execute(
            f"UPDATE problem_portfolio_analysis_runs SET {assignments} WHERE run_id=?",
            [*fields.values(), run_id],
        )

    def get_portfolio_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM problem_portfolio_analysis_runs WHERE run_id=?", (run_id,))
        if not row:
            return None
        row["parameters"] = loads(row.pop("parameters_json", None), {})
        row["summary"] = loads(row.pop("summary_json", None), {})
        return row

    def list_portfolio_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM problem_portfolio_analysis_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            row["parameters"] = loads(row.pop("parameters_json", None), {})
            row["summary"] = loads(row.pop("summary_json", None), {})
        return rows

    def find_reusable_portfolio_run(
        self,
        feedback_run_id: str,
        dimension_run_id: str,
        serialization_version: str,
    ) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM problem_portfolio_analysis_runs WHERE feedback_run_id=? AND dimension_run_id=? "
            "AND serialization_version=? AND status IN ('COMPLETED', 'SERIALIZED') "
            "ORDER BY created_at DESC LIMIT 1",
            (feedback_run_id, dimension_run_id, serialization_version),
        )

    def save_portfolio_serialization(
        self,
        *,
        serialization_id: str,
        run_id: str,
        schema_version: str,
        content_hash: str,
        payload: dict[str, Any],
    ) -> None:
        self.db.execute("DELETE FROM problem_portfolio_serializations WHERE run_id=?", (run_id,))
        self.db.insert(
            "problem_portfolio_serializations",
            {
                "serialization_id": serialization_id,
                "run_id": run_id,
                "schema_version": schema_version,
                "content_hash": content_hash,
                "payload_json": dumps(payload),
                "created_at": now_iso(),
            },
        )

    def get_portfolio_serialization(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM problem_portfolio_serializations WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
        if not row:
            return None
        row["payload"] = loads(row.pop("payload_json", None), {})
        return row

    def get_portfolio_serialization_by_id(self, serialization_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM problem_portfolio_serializations WHERE serialization_id=?",
            (serialization_id,),
        )
        if not row:
            return None
        row["payload"] = loads(row.pop("payload_json", None), {})
        return row

    def save_factor_nomenclature(self, run_id: str, rows: list[dict[str, Any]]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM problem_factor_nomenclature WHERE run_id=?", (run_id,))
            conn.executemany(
                "INSERT INTO problem_factor_nomenclature (run_id, factor_id, dimension_id, dimension_number, "
                "business_name, description, review_status, source, provisional, aliases_json, top_variables_json, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["factor_id"],
                        item["dimension_id"],
                        item.get("dimension_number"),
                        item["business_name"],
                        item.get("description"),
                        item["review_status"],
                        item.get("source", "dimension_definition"),
                        1 if item.get("provisional") else 0,
                        dumps(item.get("aliases") or []),
                        dumps(item.get("top_variables") or []),
                        now_iso(),
                    )
                    for item in rows
                ],
            )

    def get_factor_nomenclature(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM problem_factor_nomenclature WHERE run_id=? ORDER BY dimension_number, factor_id",
            (run_id,),
        )
        for row in rows:
            row["aliases"] = loads(row.pop("aliases_json", None), [])
            row["top_variables"] = loads(row.pop("top_variables_json", None), [])
            row["provisional"] = bool(row.get("provisional"))
        return rows

    def latest_factor_nomenclature_for_dimension_run(self, dimension_run_id: str) -> list[dict[str, Any]]:
        run = self.db.query_one(
            "SELECT r.run_id FROM problem_portfolio_analysis_runs r "
            "WHERE r.dimension_run_id=? AND EXISTS ("
            "SELECT 1 FROM problem_factor_nomenclature n WHERE n.run_id=r.run_id"
            ") ORDER BY r.created_at DESC, r.rowid DESC LIMIT 1",
            (dimension_run_id,),
        )
        return self.get_factor_nomenclature(run["run_id"]) if run else []

    def save_factor_profiles(self, run_id: str, rows: list[dict[str, Any]]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM problem_factor_profiles WHERE run_id=?", (run_id,))
            conn.executemany(
                "INSERT INTO problem_factor_profiles (run_id, factor_id, dimension_id, dimension_number, eigenvalue, "
                "explained_variance, cumulative_variance, problem_count, problem_share_pct, mean_abs_coefficient, "
                "max_abs_coefficient, top_variables_json, top_categories_json, representative_problem_ids_json, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["factor_id"],
                        item["dimension_id"],
                        item.get("dimension_number"),
                        item.get("eigenvalue"),
                        item.get("explained_variance"),
                        item.get("cumulative_variance"),
                        item.get("problem_count", 0),
                        item.get("problem_share_pct"),
                        item.get("mean_abs_coefficient"),
                        item.get("max_abs_coefficient"),
                        dumps(item.get("top_variables") or []),
                        dumps(item.get("top_categories") or []),
                        dumps(item.get("representative_problem_ids") or []),
                        now_iso(),
                    )
                    for item in rows
                ],
            )

    def get_factor_profiles(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM problem_factor_profiles WHERE run_id=? ORDER BY dimension_number, factor_id",
            (run_id,),
        )
        for row in rows:
            row["top_variables"] = loads(row.pop("top_variables_json", None), [])
            row["top_categories"] = loads(row.pop("top_categories_json", None), [])
            row["representative_problem_ids"] = loads(row.pop("representative_problem_ids_json", None), [])
        return rows

    def save_portfolio_narrative(
        self,
        *,
        narrative_id: str,
        run_id: str,
        serialization_id: str,
        provider: str,
        model_id: str | None,
        prompt_version: str,
        status: str,
        narrative: dict[str, Any] | None,
        generation_attempts: int,
        error: str | None = None,
    ) -> None:
        self.db.insert(
            "problem_portfolio_narratives",
            {
                "narrative_id": narrative_id,
                "run_id": run_id,
                "serialization_id": serialization_id,
                "provider": provider,
                "model_id": model_id,
                "prompt_version": prompt_version,
                "status": status,
                "narrative_json": dumps(narrative),
                "generation_attempts": generation_attempts,
                "error": error,
                "created_at": now_iso(),
            },
        )

    def get_latest_portfolio_narrative(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM problem_portfolio_narratives WHERE run_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        if not row:
            return None
        row["narrative"] = loads(row.pop("narrative_json", None), None)
        return row

    def save_narrative_validation(
        self,
        *,
        validation_id: str,
        run_id: str,
        narrative_id: str,
        result: dict[str, Any],
    ) -> None:
        self.db.insert(
            "problem_narrative_validation",
            {
                "validation_id": validation_id,
                "run_id": run_id,
                "narrative_id": narrative_id,
                "status": result["status"],
                "checks_json": dumps(result.get("checks") or []),
                "errors_json": dumps(result.get("errors") or []),
                "warnings_json": dumps(result.get("warnings") or []),
                "created_at": now_iso(),
            },
        )

    def get_latest_narrative_validation(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM problem_narrative_validation WHERE run_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        if not row:
            return None
        row["checks"] = loads(row.pop("checks_json", None), [])
        row["errors"] = loads(row.pop("errors_json", None), [])
        row["warnings"] = loads(row.pop("warnings_json", None), [])
        return row

    # ------------------------------------------------- factor prioritisation
    def create_factor_prioritisation_run(self, values: dict[str, Any]) -> None:
        self.db.insert("factor_prioritisation_runs", values)

    def update_factor_prioritisation_run(self, run_id: str, **fields: Any) -> None:
        for key in ("weight_configuration", "summary"):
            if key in fields:
                fields[f"{key}_json"] = dumps(fields.pop(key))
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.db.execute(
            f"UPDATE factor_prioritisation_runs SET {assignments} WHERE prioritisation_run_id=?",
            [*fields.values(), run_id],
        )

    def get_factor_prioritisation_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM factor_prioritisation_runs WHERE prioritisation_run_id=?",
            (run_id,),
        )
        if not row:
            return None
        row["weight_configuration"] = loads(row.pop("weight_configuration_json", None), {})
        row["summary"] = loads(row.pop("summary_json", None), {})
        return row

    def list_factor_prioritisation_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM factor_prioritisation_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            row["weight_configuration"] = loads(row.pop("weight_configuration_json", None), {})
            row["summary"] = loads(row.pop("summary_json", None), {})
        return rows

    def find_reusable_factor_prioritisation_run(
        self,
        famd_run_id: str,
        scoring_model_version: str,
        weight_configuration_json: str,
    ) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM factor_prioritisation_runs WHERE famd_run_id=? AND scoring_model_version=? "
            "AND weight_configuration_json=? AND status='COMPLETED' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (famd_run_id, scoring_model_version, weight_configuration_json),
        )

    def save_factor_prioritisation_results(
        self,
        run_id: str,
        *,
        scores: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        semantic_assessments: list[dict[str, Any]],
    ) -> None:
        now = now_iso()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM factor_prioritisation_scores WHERE prioritisation_run_id=?", (run_id,))
            conn.execute("DELETE FROM factor_prioritisation_evidence WHERE prioritisation_run_id=?", (run_id,))
            conn.execute("DELETE FROM factor_semantic_assessments WHERE prioritisation_run_id=?", (run_id,))
            conn.executemany(
                "INSERT INTO factor_prioritisation_scores (prioritisation_run_id, factor_id, dimension_id, "
                "dimension_number, factor_name, prevalence_score, statistical_importance_score, "
                "representation_strength_score, semantic_coherence_score, final_priority_score, evidence_coverage, "
                "eligibility_status, score_status, rank, weights_json, explanation_json, calculated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["factor_id"],
                        item["dimension_id"],
                        item.get("dimension_number"),
                        item.get("factor_name"),
                        item.get("prevalence_score"),
                        item.get("statistical_importance_score"),
                        item.get("representation_strength_score"),
                        item.get("semantic_coherence_score"),
                        item.get("final_priority_score"),
                        item.get("evidence_coverage"),
                        item["eligibility_status"],
                        item["score_status"],
                        item.get("rank"),
                        dumps(item.get("weights")),
                        dumps(item.get("explanation")),
                        now,
                    )
                    for item in scores
                ],
            )
            conn.executemany(
                "INSERT INTO factor_prioritisation_evidence (prioritisation_run_id, factor_id, component_name, "
                "component_label, component_weight, component_score, weighted_contribution, raw_value_json, "
                "normalised_value, calculation_method, rule_version, source_table, assessment_status, explanation, "
                "evidence_reference_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        item["factor_id"],
                        item["component_name"],
                        item["component_label"],
                        item.get("component_weight"),
                        item.get("component_score"),
                        item.get("weighted_contribution"),
                        dumps(item.get("raw_value")),
                        item.get("normalised_value"),
                        item["calculation_method"],
                        item["rule_version"],
                        item.get("source_table"),
                        item["assessment_status"],
                        item["explanation"],
                        dumps(item.get("evidence_reference")),
                        now,
                    )
                    for item in evidence
                ],
            )
            conn.executemany(
                "INSERT INTO factor_semantic_assessments (assessment_id, prioritisation_run_id, factor_id, "
                "famd_run_id, semantic_evaluation_json, supporting_problem_ids_json, contradictory_problem_ids_json, "
                "assessment_status, coverage, reviewer_id, review_status, review_note, reviewed_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["assessment_id"],
                        run_id,
                        item["factor_id"],
                        item["famd_run_id"],
                        dumps(item.get("semantic_evaluation")),
                        dumps(item.get("supporting_problem_ids")),
                        dumps(item.get("contradictory_problem_ids")),
                        item["assessment_status"],
                        item.get("coverage"),
                        item.get("reviewer_id"),
                        item.get("review_status", "UNREVIEWED"),
                        item.get("review_note"),
                        item.get("reviewed_at"),
                        now,
                    )
                    for item in semantic_assessments
                ],
            )

    def get_factor_prioritisation_scores(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM factor_prioritisation_scores WHERE prioritisation_run_id=? "
            "ORDER BY COALESCE(rank, 9999), final_priority_score DESC, factor_id",
            (run_id,),
        )
        for row in rows:
            row["weights"] = loads(row.pop("weights_json", None), {})
            row["explanation"] = loads(row.pop("explanation_json", None), {})
        return rows

    def get_factor_prioritisation_score(self, run_id: str, factor_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM factor_prioritisation_scores WHERE prioritisation_run_id=? AND factor_id=?",
            (run_id, factor_id),
        )
        if not row:
            return None
        row["weights"] = loads(row.pop("weights_json", None), {})
        row["explanation"] = loads(row.pop("explanation_json", None), {})
        return row

    def get_factor_prioritisation_evidence(
        self,
        run_id: str,
        factor_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        where = "prioritisation_run_id=?"
        if factor_id:
            where += " AND factor_id=?"
            params.append(factor_id)
        rows = self.db.query(
            f"SELECT * FROM factor_prioritisation_evidence WHERE {where} "
            "ORDER BY factor_id, component_name",
            params,
        )
        for row in rows:
            row["raw_value"] = loads(row.pop("raw_value_json", None), {})
            row["evidence_reference"] = loads(row.pop("evidence_reference_json", None), {})
        return rows

    def get_factor_semantic_assessments(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM factor_semantic_assessments WHERE prioritisation_run_id=? ORDER BY factor_id",
            (run_id,),
        )
        for row in rows:
            row["semantic_evaluation"] = loads(row.pop("semantic_evaluation_json", None), {})
            row["supporting_problem_ids"] = loads(row.pop("supporting_problem_ids_json", None), [])
            row["contradictory_problem_ids"] = loads(row.pop("contradictory_problem_ids_json", None), [])
        return rows

    def get_factor_semantic_assessment(self, run_id: str, factor_id: str) -> dict[str, Any] | None:
        rows = self.get_factor_semantic_assessments(run_id)
        return next((item for item in rows if item["factor_id"] == factor_id), None)

    def update_factor_semantic_review(
        self,
        run_id: str,
        factor_id: str,
        *,
        reviewer_id: str,
        review_status: str,
        review_note: str = "",
    ) -> None:
        self.db.execute(
            "UPDATE factor_semantic_assessments SET reviewer_id=?, review_status=?, review_note=?, reviewed_at=? "
            "WHERE prioritisation_run_id=? AND factor_id=?",
            (reviewer_id, review_status, review_note, now_iso(), run_id, factor_id),
        )

    def latest_factor_prioritisation_run(self) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM factor_prioritisation_runs WHERE status='COMPLETED' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1"
        )
        return self.get_factor_prioritisation_run(row["prioritisation_run_id"]) if row else None

    def latest_prioritisable_dimension_run(self, feedback_run_id: str | None = None) -> dict[str, Any] | None:
        params: list[Any] = []
        where = "status IN ('PENDING_REVIEW', 'APPROVED', 'PUBLISHED')"
        if feedback_run_id:
            where += " AND feedback_run_id=?"
            params.append(feedback_run_id)
        return self.db.query_one(
            f"SELECT * FROM dimension_analysis_runs WHERE {where} "
            "ORDER BY COALESCE(completed_at, created_at) DESC, created_at DESC LIMIT 1",
            params,
        )

    # ---------------------------------------------------------------- admin
    def audit(self, actor: str, action: str, entity_type: str, entity_id: str, detail: dict[str, Any] | None = None) -> None:
        self.db.insert(
            "audit_log",
            {
                "actor": actor,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "detail_json": dumps(detail),
                "created_at": now_iso(),
            },
        )

    def admin_overview(self) -> dict[str, Any]:
        return {
            "runs": self.list_runs(limit=20),
            "backlog_uploads": self.list_backlog_uploads(limit=10),
            "reports": self.list_reports(limit=10),
            "quarantine": self.db.query(
                "SELECT run_id, row_number, source_feedback_id, error_reason, created_at FROM feedback_quarantine "
                "ORDER BY id DESC LIMIT 25"
            ),
            "audit": self.db.query(
                "SELECT actor, action, entity_type, entity_id, created_at FROM audit_log ORDER BY id DESC LIMIT 25"
            ),
        }

    def get_manifest(self, run_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ingestion_manifests WHERE run_id=? ORDER BY created_at DESC LIMIT 1", (run_id,))
