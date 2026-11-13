"""Guarded advanced analytics.

These functions intentionally refuse to run when their required inputs are
missing. They never fabricate survival curves or preference utilities from
ordinary feedback because doing so would misrepresent the evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdvancedResult:
    status: str
    reason: str
    estimates: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)


def survival_analysis(events: Iterable[dict[str, Any]] | None) -> AdvancedResult:
    """Survival analysis requires a defined event, time origin and censoring.

    Feedback records do not contain churn or resolution events, so the result is
    NOT_AVAILABLE unless data with explicit ``event`` and ``duration`` fields is
    supplied.
    """

    rows = list(events or [])
    if not rows:
        return AdvancedResult(
            status="NOT_AVAILABLE",
            reason="No event or censoring data was supplied. Sentiment is not a churn event.",
            required_inputs=["event", "duration", "time_origin", "censoring_indicator"],
            assumptions=["Missing event data is not treated as a zero survival time."],
        )
    missing = [field for field in ("event", "duration") if any(field not in row for row in rows)]
    if missing:
        return AdvancedResult(
            status="NOT_AVAILABLE",
            reason="Event data is incomplete.",
            required_inputs=missing,
        )
    return AdvancedResult(
        status="READY",
        reason="Event data is available; survival estimation can run in the analytics layer.",
        estimates={"event_count": len(rows)},
        assumptions=[
            "Censoring must be independent of the event process.",
            "Time origin and duration units must be documented before estimation.",
        ],
    )


def conjoint_analysis(design_rows: Iterable[dict[str, Any]] | None) -> AdvancedResult:
    """Conjoint analysis must not be applied to ordinary feedback.

    It requires an experimental design with controlled attribute levels and
    preference responses. Without that, the correct result is NOT_APPLICABLE.
    """

    rows = list(design_rows or [])
    if not rows:
        return AdvancedResult(
            status="NOT_APPLICABLE",
            reason="Ordinary feedback is not a conjoint experimental design.",
            required_inputs=["experimental_design", "attribute_levels", "choice_responses", "sample_frame"],
            assumptions=["Preference utilities cannot be inferred from complaint text."],
        )
    return AdvancedResult(
        status="READY",
        reason="A controlled design was supplied.",
        estimates={"design_rows": len(rows)},
        assumptions=["Attribute levels must be randomised and balanced."],
    )
