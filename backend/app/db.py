from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

from .schema import SCHEMA_SQL

# Columns added after the initial PoV schema. `CREATE TABLE IF NOT EXISTS`
# cannot extend an existing SQLite file, so apply guarded ALTER TABLE
# statements on startup. This keeps local databases backward compatible.
COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "feedback_records": [
        ("feedback_text_original", "TEXT"),
        ("language_confidence", "REAL"),
        ("duplicate_group_id", "TEXT"),
        ("duplicate_type", "TEXT"),
        ("quality_flags_json", "TEXT"),
        ("pii_types_json", "TEXT"),
    ],
    "extracted_insights": [
        ("intents_json", "TEXT"),
        ("aspects_json", "TEXT"),
        ("technical_root_cause", "TEXT DEFAULT 'unknown'"),
        ("evidence_verified", "INTEGER DEFAULT 1"),
        ("field_confidence_json", "TEXT"),
        ("human_review_status", "TEXT DEFAULT 'unreviewed'"),
        ("cluster_id", "TEXT"),
    ],
    "customer_problems": [
        ("canonical_description", "TEXT"),
        ("validation_status", "TEXT DEFAULT 'candidate'"),
        ("human_review_status", "TEXT DEFAULT 'unreviewed'"),
        ("discovery_confidence", "REAL"),
        ("embedding_ref", "TEXT"),
        ("model_metadata_json", "TEXT"),
        ("symptoms_json", "TEXT"),
        ("parent_problem_id", "TEXT"),
    ],
    "backlog_items": [
        ("intended_outcome", "TEXT"),
        ("customer_intent", "TEXT"),
        ("target_feature", "TEXT"),
        ("target_journey", "TEXT"),
        ("functional_scope", "TEXT"),
        ("organisational_objective", "TEXT"),
        ("profile_json", "TEXT"),
        ("extraction_provider", "TEXT"),
        ("model_version", "TEXT"),
    ],
    "dimension_analysis_runs": [
        ("selected_features_json", "TEXT"),
        ("excluded_features_json", "TEXT"),
        ("configuration_json", "TEXT"),
    ],
    "problem_dimension_scores": [
        ("relative_squared_coordinate_share_pct", "REAL"),
        ("coordinate_rank", "INTEGER"),
    ],
    "dimension_definitions": [
        ("dimension_number", "INTEGER"),
        ("proposed_label", "TEXT"),
        ("business_interpretation", "TEXT"),
        ("interpretation_status", "TEXT DEFAULT 'DRAFT'"),
        ("model_version", "TEXT"),
    ],
}


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=45, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=45000")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            for table, columns in COLUMN_MIGRATIONS.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for name, ddl in columns:
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> None:
        conn = self.connect()
        try:
            conn.execute(sql, params)
        finally:
            conn.close()

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        if not rows:
            return
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(sql, rows)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
        conn = self.connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
        conn = self.connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def insert(self, table: str, values: dict[str, Any], replace: bool = False) -> None:
        columns = list(values.keys())
        placeholders = ", ".join(["?"] * len(columns))
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        self.execute(sql, [values[c] for c in columns])

    def upsert_many(self, table: str, values: list[dict[str, Any]], conflict_cols: list[str]) -> None:
        if not values:
            return
        columns = list(values[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c not in conflict_cols)
        conflict = ", ".join(conflict_cols)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET {updates}"
        )
        self.executemany(sql, [[row.get(c) for c in columns] for row in values])

    def get_meta(self, key: str) -> str | None:
        row = self.query_one("SELECT value FROM app_meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        from datetime import datetime

        now = datetime.now(UTC).isoformat()
        self.execute(
            "INSERT INTO app_meta(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now),
        )


def dumps(value: Any) -> str | None:
    return _json(value)


def loads(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
