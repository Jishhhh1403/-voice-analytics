from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace

from ..config import Settings
from .llm_client import LLMUnavailable, StructuredLLMClient, StructuredResponse

logger = logging.getLogger(__name__)

PROMPT_VERSION = "canonical-problem-1.0"

PROMPT = """You define one canonical customer problem for a cluster of closely related banking feedback.
You are given the top problem statements closest to the cluster medoid, ordered by similarity.

Framework:
- Cover the shared failure mode across the supplied statements, not just the medoid.
- Keep the journey step and observable symptom that are common to the statements.
- Do not invent root causes, technical architecture, severity, churn, revenue or compliance claims.
- Do not introduce facts absent from the supplied statements.
- Treat the medoid as an anchor, but the canonical problem must represent the combination.
- Return source_problem_ids only from the supplied ids.

Return strict JSON with keys:
{"title": string (max 120 chars), "description": string (max 200 chars),
 "problem_statement": string (max 350 chars), "rationale": string (max 300 chars),
 "source_problem_ids": string[]}
"""

BATCH_PROMPT = """You define canonical customer problems for multiple clusters of closely related banking feedback.
For every cluster you receive the top problem statements closest to that cluster medoid, ordered by similarity.

Framework (apply independently to each cluster):
- Cover the shared failure mode across that cluster's supplied statements, not just its medoid.
- Keep the journey step and observable symptom common to that cluster's statements.
- Do not invent root causes, technical architecture, severity, churn, revenue or compliance claims.
- Do not introduce facts absent from that cluster's supplied statements.
- Treat each medoid as an anchor, but every canonical problem must represent the combination of its cluster.
- Return source_problem_ids only from the ids supplied for that cluster.
- Return exactly one result for every supplied cluster index, in any order.

Return strict JSON with key "results" whose value is an array:
[{"index": integer (copied from the supplied cluster), "title": string (max 120 chars),
  "description": string (max 200 chars), "problem_statement": string (max 350 chars),
  "rationale": string (max 300 chars), "source_problem_ids": string[]}]
"""


@dataclass
class CanonicalProblem:
    title: str
    description: str
    problem_statement: str
    rationale: str
    source_problem_ids: list[str] = field(default_factory=list)
    provider: str = "deterministic-fallback"
    model: str | None = None
    fallback: bool = True
    prompt_version: str = PROMPT_VERSION


class CanonicalisationService:
    def __init__(self, settings: Settings, client: StructuredLLMClient | None = None) -> None:
        self.settings = settings
        self.client = client or StructuredLLMClient(
            settings,
            provider=settings.canonicalisation_provider,
            model=settings.canonicalisation_model or None,
            timeout=settings.canonicalisation_timeout_seconds,
            temperature=settings.canonicalisation_temperature,
        )

    def _items(self, neighbors: list[dict[str, object]]) -> list[dict[str, object]]:
        char_limit = max(1, self.settings.canonicalisation_max_neighbor_chars)
        return [
            {
                "rank": rank,
                "problem_id": item.get("problem_id"),
                "similarity_to_medoid": round(float(item.get("similarity") or 0.0), 4),
                "problem_statement": str(item.get("text") or "")[:char_limit],
            }
            for rank, item in enumerate(neighbors, start=1)
        ]

    def _group_key(self, neighbors: list[dict[str, object]]) -> str:
        char_limit = max(1, self.settings.canonicalisation_max_neighbor_chars)
        normalized = [
            re.sub(r"[^a-z0-9]+", " ", str(item.get("text") or "")[:char_limit].lower()).strip()
            for item in neighbors
        ]
        return "|".join(normalized)

    def _payload(self, neighbors: list[dict[str, object]]) -> str:
        return json.dumps({"neighbors": self._items(neighbors)}, ensure_ascii=False)

    def _fallback(self, neighbors: list[dict[str, object]]) -> CanonicalProblem:
        anchor = str(neighbors[0].get("text") or "Reported customer issue") if neighbors else "Reported customer issue"
        return CanonicalProblem(
            title=anchor[:120],
            description=anchor[:200],
            problem_statement=anchor[:350],
            rationale="Deterministic medoid fallback: no structured LLM result was available.",
            source_problem_ids=[str(item.get("problem_id")) for item in neighbors if item.get("problem_id")],
        )

    def define_deterministic(self, neighbors: list[dict[str, object]]) -> CanonicalProblem:
        return self._fallback(neighbors)

    def _from_payload(
        self,
        payload: dict[str, object],
        neighbors: list[dict[str, object]],
        fallback: CanonicalProblem,
        response: StructuredResponse,
    ) -> CanonicalProblem:
        title = str(payload.get("title") or "").strip()
        description = str(payload.get("description") or "").strip()
        statement = str(payload.get("problem_statement") or "").strip()
        if len(title) < 3 or len(statement) < 3:
            return fallback
        allowed = {str(item.get("problem_id")) for item in neighbors}
        source_ids = [str(value) for value in (payload.get("source_problem_ids") or []) if str(value) in allowed]
        return CanonicalProblem(
            title=title[:120],
            description=(description or title)[:200],
            problem_statement=statement[:350],
            rationale=str(payload.get("rationale") or "")[:300],
            source_problem_ids=source_ids or fallback.source_problem_ids,
            provider=response.provider,
            model=response.model,
            fallback=False,
        )

    def _worker_client(self) -> StructuredLLMClient:
        if not isinstance(self.client, StructuredLLMClient):
            return self.client
        return StructuredLLMClient(
            self.settings,
            provider=self.settings.canonicalisation_provider,
            model=self.settings.canonicalisation_model or None,
            timeout=self.settings.canonicalisation_timeout_seconds,
            temperature=self.settings.canonicalisation_temperature,
        )

    def define(self, neighbors: list[dict[str, object]]) -> CanonicalProblem:
        groups = [neighbors[: max(1, self.settings.canonicalisation_max_neighbors)]]
        return self.define_batch(groups)[0]

    def define_batch(
        self, neighbor_groups: list[list[dict[str, object]]]
    ) -> list[CanonicalProblem]:
        limit = max(1, self.settings.canonicalisation_max_neighbors)
        groups = [group[:limit] for group in neighbor_groups]
        results = [self.define_deterministic(group) for group in groups]
        if not groups or not self.client.available:
            return results
        key_to_unique: dict[str, int] = {}
        unique_groups: list[list[dict[str, object]]] = []
        owners: list[list[int]] = []
        for index, group in enumerate(groups):
            key = self._group_key(group)
            if key not in key_to_unique:
                key_to_unique[key] = len(unique_groups)
                unique_groups.append(group)
                owners.append([])
            owners[key_to_unique[key]].append(index)
        logger.info("canonicalisation: %s unique neighbor sets for %s clusters", len(unique_groups), len(groups))
        batch_size = max(1, min(200, self.settings.canonicalisation_batch_size))
        budget = max(0, self.settings.canonicalisation_max_llm_calls)
        if budget == 0:
            return results
        starts = list(range(0, len(unique_groups), batch_size))[:budget]
        workers = max(1, min(8, self.settings.canonicalisation_max_workers))
        if not isinstance(self.client, StructuredLLMClient):
            workers = 1

        def call(start: int) -> tuple[int, StructuredResponse | None, LLMUnavailable | None]:
            chunk = unique_groups[start : start + batch_size]
            payload = {
                "clusters": [
                    {"index": start + offset, "neighbors": self._items(group)}
                    for offset, group in enumerate(chunk)
                ]
            }
            try:
                response = self._worker_client().generate_json(
                    BATCH_PROMPT + "\nClusters:\n" + json.dumps(payload, ensure_ascii=False)
                )
                return start, response, None
            except LLMUnavailable as exc:
                return start, None, exc

        outcomes: list[tuple[int, StructuredResponse | None, LLMUnavailable | None]] = []
        if workers == 1:
            outcomes = [call(start) for start in starts]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(call, start) for start in starts]
                for future in as_completed(futures):
                    outcomes.append(future.result())

        calls = 0
        for start, response, error in outcomes:
            if error is not None:
                logger.warning("canonicalisation batch %s failed: %s", start // batch_size, error)
                continue
            if response is None:
                continue
            calls += 1
            rows = response.payload.get("results")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    index = int(row.get("index"))
                except (TypeError, ValueError):
                    continue
                if not 0 <= index < len(unique_groups):
                    continue
                canonical = self._from_payload(
                    row, unique_groups[index], results[owners[index][0]], response
                )
                if canonical.fallback:
                    continue
                for owner in owners[index]:
                    source_ids = [
                        str(item.get("problem_id"))
                        for item in groups[owner]
                        if item.get("problem_id")
                    ]
                    results[owner] = replace(
                        canonical,
                        source_problem_ids=source_ids or canonical.source_problem_ids,
                    )
        logger.info("canonicalisation: %s LLM calls completed", calls)
        return results
