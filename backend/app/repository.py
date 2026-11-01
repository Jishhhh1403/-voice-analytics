from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .db import Database, dumps, loads

STAGES = ["validate_source", "module_a_ingest", "module_b_extract", "module_c_discover", "module_d_map", "module_e_publish"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        run_id = f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
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
                "synthetic_customer_ref": record.synthetic_customer_ref,
                "rating": record.rating,
                "feedback_title": record.feedback_title,
                "feedback_text_redacted": record.feedback_text_redacted,
                "content_fingerprint": record.content_fingerprint,
                "is_synthetic": int(record.is_synthetic),
                "created_at": now_iso(),
            }
            for record in records
        ]
        self.db.executemany(
            "INSERT OR REPLACE INTO feedback_records (run_id, feedback_id, source_feedback_id, tenant_id, submitted_at, "
            "source_type, source_channel, platform, app_version, language, synthetic_customer_ref, rating, feedback_title, "
            "feedback_text_redacted, content_fingerprint, is_synthetic, created_at) VALUES "
            "(:run_id, :feedback_id, :source_feedback_id, :tenant_id, :submitted_at, :source_type, :source_channel, "
            ":platform, :app_version, :language, :synthetic_customer_ref, :rating, :feedback_title, "
            ":feedback_text_redacted, :content_fingerprint, :is_synthetic, :created_at)",
            rows,
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
            "aspect, journey_node_id, reported_problem, reported_symptom, sentiment, sentiment_score, emotion, "
            "customer_effort, reported_outcome, evidence_span, language, model_id, prompt_version, schema_version, "
            "extraction_timestamp, extraction_method, confidence, embedding_json, is_problem) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item.insight_id,
                    item.feedback_id.split("|")[0] if "|" in item.feedback_id else getattr(item, "run_id", None),
                    item.feedback_id,
                    item.sentence_index,
                    item.customer_intent,
                    item.aspect,
                    item.journey_node_id,
                    item.reported_problem,
                    item.reported_symptom,
                    item.sentiment,
                    item.sentiment_score,
                    item.emotion,
                    item.customer_effort,
                    item.reported_outcome,
                    item.evidence_span,
                    item.language,
                    item.model_id,
                    item.prompt_version,
                    item.schema_version,
                    item.extraction_timestamp,
                    item.extraction_method,
                    item.confidence,
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
            "aspect, journey_node_id, reported_problem, reported_symptom, sentiment, sentiment_score, emotion, "
            "customer_effort, reported_outcome, evidence_span, language, model_id, prompt_version, schema_version, "
            "extraction_timestamp, extraction_method, confidence, embedding_json, is_problem) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item.insight_id,
                    run_id,
                    item.feedback_id,
                    item.sentence_index,
                    item.customer_intent,
                    item.aspect,
                    item.journey_node_id,
                    item.reported_problem,
                    item.reported_symptom,
                    item.sentiment,
                    item.sentiment_score,
                    item.emotion,
                    item.customer_effort,
                    item.reported_outcome,
                    item.evidence_span,
                    item.language,
                    item.model_id,
                    item.prompt_version,
                    item.schema_version,
                    item.extraction_timestamp,
                    item.extraction_method,
                    item.confidence,
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
                    "customer_intent": problem.customer_intent,
                    "aspect": problem.aspect,
                    "symptom_category": problem.symptom_category,
                    "journey_node_id": problem.journey_node_id,
                    "status": problem.lifecycle_status,
                    "lifecycle_status": problem.lifecycle_status,
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
            "SELECT insight_id, customer_intent, aspect, reported_symptom, sentiment, emotion, customer_effort, "
            "reported_outcome, confidence FROM extracted_insights WHERE feedback_id IN "
            "(SELECT feedback_id FROM problem_evidence WHERE problem_id=?) ORDER BY confidence DESC LIMIT 50",
            (problem_id,),
        )
        problem["reviews"] = self.db.query(
            "SELECT reviewer, decision, note, created_at FROM review_decisions WHERE entity_type='problem' "
            "AND entity_id=? ORDER BY created_at DESC",
            (problem_id,),
        )
        return problem

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
        self.audit(reviewer, "report_review", "validation_report", report_id, {"decision": decision, "note": note})

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
