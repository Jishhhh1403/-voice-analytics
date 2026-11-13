from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..intelligence.contracts import CleanFeedback
from ..intelligence.duplicates import detect_duplicate_relationships
from ..intelligence.language import detect_language
from ..intelligence.pii import redact_pii_enhanced
from ..intelligence.quality import run_data_quality_checks, summarize_checks
from ..intelligence.text import normalize_text

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
    duplicate_relationships: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    pii_types: list[str] = field(default_factory=list)
    quality_checks: list[dict[str, Any]] = field(default_factory=list)


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
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


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
    raw_rows: list[dict[str, Any]] = []
    row_count = 0

    for row_number, raw_row in enumerate(reader, start=2):
        row_count += 1
        if row_count > settings.pipeline_max_rows:
            raise IngestionError(f"row count exceeds configured maximum of {settings.pipeline_max_rows}")
        row = {str(key).strip(): (value or "").strip() for key, value in raw_row.items() if key is not None}
        raw_rows.append(row)
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
            redaction = redact_pii_enhanced(
                raw_text,
                provider=settings.pii_provider,
                language=row.get("language") or settings.pii_presidio_language,
            )
            redacted_text = redaction.text
            if len(redacted_text) < 3:
                raise ValueError("feedback_text is too short after normalisation")
            pii_types.update(redaction.labels)
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

        supplied_language = (row.get("language") or "").lower() or None
        if settings.detect_language:
            detected = detect_language(redacted_text, settings.language_detection_provider)
            language = detected.language
            language_confidence = detected.confidence
        else:
            language = supplied_language or "en"
            language_confidence = 0.0

        fingerprint = _fingerprint(redacted_text)
        duplicate_group_id = None
        duplicate_type = None
        if fingerprint in seen_fingerprints:
            duplicate_group_id = fingerprint[:16]
            duplicate_type = "exact"
            result.duplicates.append(
                {
                    "row_number": row_number,
                    "source_feedback_id": source_feedback_id,
                    "duplicate_of": seen_fingerprints[fingerprint],
                }
            )
            result.duplicate_relationships.append(
                {
                    "feedback_id": source_feedback_id or "",
                    "candidate_feedback_id": seen_fingerprints[fingerprint],
                    "duplicate_type": "exact",
                    "similarity": 1.0,
                    "metadata": {"linked_not_discarded": True},
                }
            )

        feedback_id = source_feedback_id or (
            "FB-" + hashlib.sha1(f"{row.get('source_type')}|{submitted_at}|{fingerprint}".encode()).hexdigest()[:16]
        )
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
        seen_fingerprints.setdefault(fingerprint, feedback_id)

        quality_flags: list[str] = []
        if len(redacted_text) > settings.data_quality_max_chars:
            quality_flags.append("unexpected_length_long")
        if language not in {"en", "hi", "hinglish", "ta", "te", "bn", "mr"}:
            quality_flags.append("unsupported_language")

        result.accepted.append(
            CleanFeedback(
                feedback_id=feedback_id,
                source_feedback_id=source_feedback_id or None,
                submitted_at=submitted_at,
                source_type=row.get("source_type") or "unknown",
                source_channel=row.get("source_channel") or "unknown",
                platform=row.get("platform") or "Unknown",
                app_version=row.get("app_version") or None,
                language=language,
                language_confidence=language_confidence,
                synthetic_customer_ref=row.get("synthetic_customer_ref") or None,
                rating=rating,
                feedback_title=row.get("feedback_title") or "",
                feedback_text_redacted=redacted_text,
                feedback_text_original=normalize_text(raw_text),
                content_fingerprint=fingerprint,
                duplicate_group_id=duplicate_group_id,
                duplicate_type=duplicate_type,
                quality_flags=quality_flags,
                pii_types=redaction.labels,
                is_synthetic=_parse_bool(row.get("is_synthetic", "true")),
            )
        )

    # Near-duplicate and repeat-complaint relationships are additive. They never
    # remove a customer's feedback record.
    detected = detect_duplicate_relationships(
        result.accepted,
        threshold=settings.near_duplicate_threshold,
        min_tokens=settings.near_duplicate_min_tokens,
        window_days=settings.repeat_complaint_window_days,
    )
    for relationship in detected:
        if relationship.duplicate_type == "exact":
            continue
        result.duplicate_relationships.append(
            {
                "feedback_id": relationship.feedback_id,
                "candidate_feedback_id": relationship.candidate_feedback_id,
                "duplicate_type": relationship.duplicate_type,
                "similarity": relationship.similarity,
                "metadata": relationship.metadata,
            }
        )

    result.pii_types = sorted(pii_types)
    result.quality_checks = run_data_quality_checks(
        raw_rows,
        result.accepted,
        result.rejected,
        result.duplicates,
        min_chars=settings.data_quality_min_chars,
        max_chars=settings.data_quality_max_chars,
    )
    quality_summary = summarize_checks(result.quality_checks)
    result.manifest = {
        "rows_read": row_count,
        "accepted_rows": len(result.accepted),
        "rejected_rows": len(result.rejected),
        "duplicate_rows": len(result.duplicates),
        "near_duplicate_rows": sum(
            1 for item in result.duplicate_relationships if item.get("duplicate_type") == "near"
        ),
        "repeat_complaint_rows": sum(
            1 for item in result.duplicate_relationships if item.get("duplicate_type") == "repeat"
        ),
        "duplicate_policy": "linked_not_discarded",
        "language_counts": {
            language: sum(1 for record in result.accepted if record.language == language)
            for language in sorted({record.language for record in result.accepted})
        },
        "pii_provider": settings.pii_provider,
        "language_provider": settings.language_detection_provider,
        "data_quality": quality_summary,
    }
    return result
