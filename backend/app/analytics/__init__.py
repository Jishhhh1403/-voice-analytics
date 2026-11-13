from __future__ import annotations

from ..config import Settings
from ..repository import Repository
from .base import AnalyticsBackend
from .sqlite_backend import SqliteAnalyticsBackend


def build_analytics_backend(settings: Settings, repo: Repository) -> AnalyticsBackend:
    if settings.analytics_backend.lower() == "bigquery":
        from .bigquery_backend import BigQueryAnalyticsBackend

        return BigQueryAnalyticsBackend(settings)
    return SqliteAnalyticsBackend(repo)


__all__ = ["AnalyticsBackend", "SqliteAnalyticsBackend", "build_analytics_backend"]
