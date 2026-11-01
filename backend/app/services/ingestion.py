from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..intelligence.contracts import CleanFeedback
from ..intelligence.text import normalize_text, redact_pii

REQUIRED_COLUMNS = [
    "feedback_id",
    "submitted_at",
    "source_type",
    "source_channel",
    "platform",
    "app_version",
    "language",
    "synthetic_customer_ref",
    "rating_1_to_5",
    "feedback_title",
    "feedback_text",
    "is_synthetic",
]
MANDATORY_VALUES = ["feedback_text"]


class IngestionError(Exception):
    pass


@dataclass
class IngestionResult:
    accepted: list[CleanFeedback] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    pii_types: list[str] = field(default_factory=list)


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _parse_timestamp(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("missing submitted_at")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("malformed submitted_at") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_rating(value: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        rating = int(float(raw))
    except ValueError as exc:
        raise ValueError("rating is not an integer") from exc
    if rating < 1 or rating > 5:
        raise ValueError("rating must be between 1 and 5")
    return rating


def _fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_text(text).lower().encode("utf-8")).hexdigest()


def parse_feedback_csv(data: bytes, tenant_id: str, settings: Settings) -> IngestionResult:
    if not data:
        raise IngestionError("source object is empty")
    if len(data) > settings.max_feedback_bytes:
        raise IngestionError("source object exceeds the configured maximum size")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError("source CSV must be UTF-8 (with optional BOM)") from exc

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [header.strip() for header in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise IngestionError("missing required columns: " + ", ".join(missing))

    result = IngestionResult()
    seen_fingerprints: dict[str, str] = {}
    seen_ids: set[str] = set()
    pii_types: set[str] = set()
    row_count = 0

    for row_number, raw_row in enumerate(reader, start=2):
        row_count += 1
        if row_count > settings.pipeline_max_rows:
            raise IngestionError(f"row count exceeds configured maximum of {settings.pipeline_max_rows}")
        row = {str(key).strip(): (value or "").strip() for key, value in raw_row.items() if key is not None}
        source_feedback_id = row.get("feedback_id", "")
        raw_text = row.get("feedback_text", "")
        if not raw_text:
            result.rejected.append(
                {
                    "row_number": row_number,
                    "source_feedback_id": source_feedback_id,
                    "error_reason": "missing feedback_text",
                    "raw": {k: row.get(k) for k in ("feedback_id", "source_type", "platform", "language")},
                }
            )
            continue
        try:
            submitted_at = _parse_timestamp(row.get("submitted_at", ""))
            rating = _parse_rating(row.get("rating_1_to_5", ""))
            redacted_text, pii = redact_pii(raw_text)
            if len(redacted_text) < 3:
                raise ValueError("feedback_text is too short after normalisation")
            pii_types.update(pii)
        except ValueError as exc:
            result.rejected.append(
                {
                    "row_number": row_number,
                    "source_feedback_id": source_feedback_id,
                    "error_reason": str(exc),
                    "raw": {
                        "feedback_id": source_feedback_id,
                        "source_type": row.get("source_type"),
                        "platform": row.get("platform"),
                        "language": row.get("language"),
                    },
                }
            )
            continue

        fingerprint = _fingerprint(redacted_text)
        if fingerprint in seen_fingerprints:
            result.duplicates.append(
                {
                    "row_number": row_number,
                    "source_feedback_id": source_feedback_id,
                    "duplicate_of": seen_fingerprints[fingerprint],
                }
            )
            continue

        feedback_id = source_feedback_id or ("FB-" + hashlib.sha1(
            f"{row.get('source_type')}|{submitted_at}|{fingerprint}".encode("utf-8")
        ).hexdigest()[:16])
        if feedback_id in seen_ids:
            result.rejected.append(
                {
                    "row_number": row_number,
                    "source_feedback_id": source_feedback_id,
                    "error_reason": "duplicate feedback_id within upload",
                    "raw": {"feedback_id": feedback_id},
                }
            )
            continue
        seen_ids.add(feedback_id)
        seen_fingerprints[fingerprint] = feedback_id

        result.accepted.append(
            CleanFeedback(
                feedback_id=feedback_id,
                source_feedback_id=source_feedback_id or None,
                submitted_at=submitted_at,
                source_type=row.get("source_type") or "unknown",
                source_channel=row.get("source_channel") or "unknown",
                platform=row.get("platform") or "Unknown",
                app_version=row.get("app_version") or None,
                language=(row.get("language") or "en").lower(),
                synthetic_customer_ref=row.get("synthetic_customer_ref") or None,
                rating=rating,
                feedback_title=row.get("feedback_title") or "",
                feedback_text_redacted=redacted_text,
                content_fingerprint=fingerprint,
                is_synthetic=_parse_bool(row.get("is_synthetic", "true")),
            )
        )

    result.pii_types = sorted(pii_types)
    result.manifest = {
        "rows_read": row_count,
        "accepted_rows": len(result.accepted),
        "rejected_rows": len(result.rejected),
        "duplicate_rows": len(result.duplicates),
    }
    return result
