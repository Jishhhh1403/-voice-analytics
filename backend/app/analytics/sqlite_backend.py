from __future__ import annotations

from typing import Any

from ..repository import Repository


class SqliteAnalyticsBackend:
    name = "sqlite"

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def latest_run(self) -> dict[str, Any] | None:
        return self.repo.latest_completed_feedback_run()

    def problems(self, run_id: str) -> list[dict[str, Any]]:
        return self.repo.db.query("SELECT * FROM customer_problems WHERE run_id=? ORDER BY evidence_count DESC", (run_id,))

    def priorities(self, run_id: str) -> list[dict[str, Any]]:
        return self.repo.db.query("SELECT * FROM problem_priority_snapshots WHERE run_id=? ORDER BY rank", (run_id,))

    def measurement(self, problem_id: str) -> list[dict[str, Any]]:
        return self.repo.db.query(
            "SELECT * FROM problem_measurement_snapshots WHERE problem_id=? ORDER BY metric_name", (problem_id,)
        )

    def coverage(self, report_id: str) -> list[dict[str, Any]]:
        return self.repo.db.query(
            "SELECT * FROM backlog_coverage_matrix WHERE report_id=? ORDER BY priority_rank", (report_id,)
        )
