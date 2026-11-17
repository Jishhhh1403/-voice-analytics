from __future__ import annotations

from dataclasses import dataclass, field

from .models import VerifiedWhitespace


@dataclass(frozen=True)
class UnifiedMergerResult:
    whitespaces: tuple[VerifiedWhitespace, ...]
    diagnostics: dict[str, object] = field(default_factory=dict)


def merge_whitespaces(
    whitespaces: list[VerifiedWhitespace],
    minimum_score: float = 0.0,
) -> UnifiedMergerResult:
    seen: set[str] = set()
    merged: list[VerifiedWhitespace] = []
    for item in sorted(whitespaces, key=lambda value: (-value.whitespace_score, value.whitespace_id)):
        if item.whitespace_id in seen or item.whitespace_score < minimum_score:
            continue
        seen.add(item.whitespace_id)
        merged.append(item)
    return UnifiedMergerResult(
        whitespaces=tuple(merged),
        diagnostics={
            "candidate_count": len(whitespaces),
            "accepted_count": len(merged),
            "minimum_score": minimum_score,
        },
    )
