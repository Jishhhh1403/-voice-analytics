"""Duplicate and repeat-complaint detection.

Three distinct mechanisms are intentionally kept separate:

1. Exact duplicates: SHA-256 content fingerprint.
2. Near-duplicate candidates: MinHash + locality-sensitive hashing (LSH).
3. Repeat complaints: same customer reference, same problem identity and a
   configurable reporting time window.

Complaints are never discarded by this module. It only returns relationship
records so two different customers reporting the same problem remain separate
customer experiences.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .contracts import CleanFeedback

_MERSENNE_PRIME = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1


@dataclass(frozen=True)
class DuplicateRelationship:
    feedback_id: str
    candidate_feedback_id: str | None
    duplicate_type: str
    similarity: float
    metadata: dict[str, Any]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'-]*", (text or "").lower())


def _shingles(tokens: list[str], size: int = 3) -> set[str]:
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def _hash(token: str, seed: int) -> int:
    digest = hashlib.blake2b(f"{seed}:{token}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % _MERSENNE_PRIME


def _minhash(shingles: set[str], permutations: int = 64) -> tuple[int, ...]:
    if not shingles:
        return tuple([0] * permutations)
    return tuple(min(_hash(shingle, seed) for shingle in shingles) for seed in range(permutations))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _norm_problem_identity(text: str) -> str:
    """Cheap problem identity proxy used for repeat complaints.

    This is deliberately lexical and stable. A semantic problem identity is
    attached later by Module C/D once canonical problems exist.
    """

    tokens = sorted({token for token in _tokens(text) if len(token) > 3})
    return " ".join(tokens[:24])


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def detect_duplicate_relationships(
    records: Iterable[CleanFeedback],
    threshold: float = 0.85,
    min_tokens: int = 5,
    window_days: int = 30,
    permutations: int = 64,
    bands: int = 16,
) -> list[DuplicateRelationship]:
    items = list(records)
    relationships: dict[tuple[str, str, str], DuplicateRelationship] = {}

    # ---------------------------------------------------------- exact duplicates
    by_fingerprint: dict[str, list[CleanFeedback]] = defaultdict(list)
    for record in items:
        by_fingerprint[record.content_fingerprint].append(record)
    for group in by_fingerprint.values():
        anchor = group[0]
        for record in group[1:]:
            key = (record.feedback_id, anchor.feedback_id, "exact")
            relationships[key] = DuplicateRelationship(
                feedback_id=record.feedback_id,
                candidate_feedback_id=anchor.feedback_id,
                duplicate_type="exact",
                similarity=1.0,
                metadata={"same_customer": record.synthetic_customer_ref == anchor.synthetic_customer_ref},
            )

    # ----------------------------------------------------- near-duplicate candidates
    signatures: dict[str, tuple[int, ...]] = {}
    shingle_sets: dict[str, set[str]] = {}
    for record in items:
        tokens = _tokens(record.feedback_text_redacted)
        if len(tokens) < min_tokens:
            continue
        shingles = _shingles(tokens)
        shingle_sets[record.feedback_id] = shingles
        signatures[record.feedback_id] = _minhash(shingles, permutations)

    rows_per_band = max(1, permutations // bands)
    buckets: dict[tuple[int, tuple[int, ...]], list[str]] = defaultdict(list)
    for feedback_id, signature in signatures.items():
        for band in range(bands):
            start = band * rows_per_band
            bucket_key = (band, signature[start : start + rows_per_band])
            buckets[bucket_key].append(feedback_id)

    seen_pairs: set[tuple[str, str]] = set()
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        for index, left in enumerate(bucket):
            for right in bucket[index + 1 :]:
                pair = tuple(sorted((left, right)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                similarity = _jaccard(shingle_sets[left], shingle_sets[right])
                if similarity < threshold:
                    continue
                if similarity >= 1.0:
                    continue  # already captured as exact
                key = (right, left, "near")
                relationships.setdefault(
                    key,
                    DuplicateRelationship(
                        feedback_id=right,
                        candidate_feedback_id=left,
                        duplicate_type="near",
                        similarity=round(similarity, 4),
                        metadata={"method": "minhash_lsh", "threshold": threshold},
                    ),
                )

    # ------------------------------------------------------- repeat complaints
    grouped: dict[tuple[str, str], list[CleanFeedback]] = defaultdict(list)
    for record in items:
        if not record.synthetic_customer_ref:
            continue
        identity = _norm_problem_identity(record.feedback_text_redacted)
        if identity:
            grouped[(record.synthetic_customer_ref, identity)].append(record)
    window_seconds = max(0, window_days) * 86400
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: item.submitted_at or "")
        for index, record in enumerate(ordered):
            record_time = _parse_time(record.submitted_at)
            if record_time is None:
                continue
            for previous in reversed(ordered[:index]):
                previous_time = _parse_time(previous.submitted_at)
                if previous_time is None:
                    continue
                if (record_time - previous_time).total_seconds() <= window_seconds:
                    key = (record.feedback_id, previous.feedback_id, "repeat")
                    relationships.setdefault(
                        key,
                        DuplicateRelationship(
                            feedback_id=record.feedback_id,
                            candidate_feedback_id=previous.feedback_id,
                            duplicate_type="repeat",
                            similarity=1.0,
                            metadata={"window_days": window_days, "customer_ref": record.synthetic_customer_ref},
                        ),
                    )
                    break

    return sorted(
        relationships.values(),
        key=lambda item: (item.feedback_id, item.duplicate_type, item.candidate_feedback_id or ""),
    )
