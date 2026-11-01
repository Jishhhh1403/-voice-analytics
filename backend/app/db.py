from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .schema import SCHEMA_SQL


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
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
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
