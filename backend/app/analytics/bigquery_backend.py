from __future__ import annotations

from typing import Any

from ..config import Settings


class BigQueryAnalyticsBackend:
    """Read-only BigQuery analytics backend.

    The adapter is intentionally thin and fails closed when the optional Google
    Cloud libraries or configuration are absent. SQLite continues to own writes
    and local execution, so enabling this backend never changes pipeline output.
    """

    name = "bigquery"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.project = settings.bigquery_project
        self.prefix = settings.bigquery_dataset_prefix
        self.client = self._client()

    def _client(self):
        if not self.project:
            raise RuntimeError("BIGQUERY_PROJECT must be configured when ANALYTICS_BACKEND=bigquery")
        try:
            from google.cloud import bigquery  # type: ignore
        except ImportError as exc:
            raise RuntimeError("google-cloud-bigquery is not installed") from exc
        return bigquery.Client(project=self.project)

    def _table(self, name: str) -> str:
        dataset = f"{self.prefix}_{name.split('.')[0]}" if self.prefix else name.split(".")[0]
        return f"`{self.project}.{dataset}.{name.split('.')[-1]}`"

    def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        from google.cloud import bigquery  # type: ignore

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter(f"p{index}", "STRING", value) for index, value in enumerate(params)]
        )
        return [dict(row.items()) for row in self.client.query(sql, job_config=job_config).result()]

    def latest_run(self) -> dict[str, Any] | None:
        rows = self._query(
            f"SELECT * FROM {self._table('ops.pipeline_runs')} WHERE status='completed' "
            "ORDER BY finished_at DESC LIMIT 1",
            [],
        )
        return rows[0] if rows else None

    def problems(self, run_id: str) -> list[dict[str, Any]]:
        return self._query(
            f"SELECT * FROM {self._table('intelligence.customer_problems')} WHERE run_id=@p0 ORDER BY evidence_count DESC",
            [run_id],
        )

    def priorities(self, run_id: str) -> list[dict[str, Any]]:
        return self._query(
            f"SELECT * FROM {self._table('intelligence.problem_priority_snapshots')} WHERE run_id=@p0 ORDER BY rank",
            [run_id],
        )

    def measurement(self, problem_id: str) -> list[dict[str, Any]]:
        return self._query(
            f"SELECT * FROM {self._table('intelligence.problem_measurement_snapshots')} "
            "WHERE problem_id=@p0 ORDER BY metric_name",
            [problem_id],
        )

    def coverage(self, report_id: str) -> list[dict[str, Any]]:
        return self._query(
            f"SELECT * FROM {self._table('validation.backlog_coverage_matrix')} "
            "WHERE report_id=@p0 ORDER BY priority_rank",
            [report_id],
        )
