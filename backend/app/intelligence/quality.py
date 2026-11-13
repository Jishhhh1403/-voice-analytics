"""Module A data-quality profiling.

Checks are intentionally additive and never block ingestion. Each check returns
an explicit status (PASS, WARN, FAIL, NOT_AVAILABLE) so downstream consumers can
tell the difference between clean data and a metric that could not be computed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from .contracts import CleanFeedback
from .language import SUPPORTED_LANGUAGES

_CORRUPTION = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")


def _check(
    name: str,
    status: str,
    severity: str,
    affected_rows: int = 0,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "check_name": name,
        "status": status,
        "severity": severity,
        "affected_rows": affected_rows,
        "detail": detail or {},
    }


def run_data_quality_checks(
    raw_rows: Iterable[dict[str, Any]],
    accepted: list[CleanFeedback],
    rejected: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    min_chars: int = 3,
    max_chars: int = 5000,
) -> list[dict[str, Any]]:
    raw = list(raw_rows)
    checks: list[dict[str, Any]] = []

    empty = sum(1 for row in raw if not str(row.get("feedback_text") or "").strip())
    checks.append(
        _check(
            "empty_feedback",
            "FAIL" if empty else "PASS",
            "high",
            empty,
            {"rows_checked": len(raw)},
        )
    )

    too_short = sum(1 for record in accepted if len(record.feedback_text_redacted) < min_chars)
    too_long = sum(1 for record in accepted if len(record.feedback_text_redacted) > max_chars)
    checks.append(
        _check(
            "unexpected_text_length",
            "WARN" if (too_short or too_long) else "PASS",
            "medium",
            too_short + too_long,
            {"too_short": too_short, "too_long": too_long, "max_chars": max_chars},
        )
    )

    corrupted = sum(1 for record in accepted if _CORRUPTION.search(record.feedback_text_redacted))
    checks.append(
        _check(
            "corrupted_text",
            "WARN" if corrupted else "PASS",
            "high",
            corrupted,
            {"replacement_or_control_characters": True},
        )
    )

    missing_timestamps = sum(1 for row in rejected if "submitted_at" in str(row.get("error_reason") or ""))
    checks.append(
        _check(
            "missing_or_invalid_timestamps",
            "FAIL" if missing_timestamps else "PASS",
            "high",
            missing_timestamps,
        )
    )

    sources = Counter(record.source_type for record in accepted)
    dominant_source = sources.most_common(1)[0] if sources else ("none", 0)
    dominant_share = round(dominant_source[1] / len(accepted), 3) if accepted else 0.0
    checks.append(
        _check(
            "source_distribution",
            "WARN" if accepted and dominant_share >= 0.9 and len(sources) > 1 else "PASS",
            "low",
            0,
            {
                "counts": dict(sources),
                "dominant_source": dominant_source[0],
                "dominant_share": dominant_share,
            },
        )
    )

    unsupported = sum(1 for record in accepted if (record.language or "unknown") not in SUPPORTED_LANGUAGES)
    checks.append(
        _check(
            "unsupported_language",
            "WARN" if unsupported else "PASS",
            "medium",
            unsupported,
            {"supported_languages": sorted(SUPPORTED_LANGUAGES)},
        )
    )

    duplicate_rate = round(len(duplicates) / (len(accepted) + len(duplicates)), 3) if (accepted or duplicates) else 0.0
    checks.append(
        _check(
            "duplicate_rate",
            "WARN" if duplicate_rate >= 0.25 else "PASS",
            "low",
            len(duplicates),
            {"duplicate_rate": duplicate_rate, "policy": "linked_not_discarded"},
        )
    )

    invalid_encoding = sum(1 for row in rejected if "utf-8" in str(row.get("error_reason") or "").lower())
    checks.append(
        _check(
            "invalid_encoding",
            "FAIL" if invalid_encoding else "PASS",
            "high",
            invalid_encoding,
        )
    )
    return checks


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(check["status"] for check in checks)
    return {
        "total_checks": len(checks),
        "status_counts": dict(counts),
        "has_failures": counts.get("FAIL", 0) > 0,
        "checks": checks,
    }
