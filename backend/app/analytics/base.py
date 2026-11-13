from __future__ import annotations

from typing import Any, Protocol


class AnalyticsBackend(Protocol):
    """Read interface shared by the local SQLite and BigQuery backends.

    SQLite remains the operational write store. BigQuery is an optional read
    backend for cloud analytics and can be introduced without changing the
    pipeline's local-first execution path.
    """

    name: str

    def latest_run(self) -> dict[str, Any] | None: ...

    def problems(self, run_id: str) -> list[dict[str, Any]]: ...

    def priorities(self, run_id: str) -> list[dict[str, Any]]: ...

    def measurement(self, problem_id: str) -> list[dict[str, Any]]: ...

    def coverage(self, report_id: str) -> list[dict[str, Any]]: ...
