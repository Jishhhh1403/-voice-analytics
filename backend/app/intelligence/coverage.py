from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import Settings
from .embeddings import build_coverage_embedder
from .llm_client import LLMUnavailable, StructuredLLMClient
from .text import token_set
from .whitespace.models import LensAssociation

AGENT_ROLES: list[dict[str, str]] = [
    {
        "key": "customer_experience",
        "name": "Customer Experience Analyst",
        "lens": "customer-observable symptoms, journey step and reported obstacle",
    },
    {
        "key": "delivery",
        "name": "Backlog Delivery Lead",
        "lens": "whether the backlog scope and acceptance criteria would resolve the reported obstacle",
    },
    {
        "key": "risk",
        "name": "Risk and Controls Reviewer",
        "lens": "unresolved gaps, contradictions and false-positive coverage risk",
    },
    {
        "key": "taxonomy",
        "name": "Journey Taxonomy Specialist",
        "lens": "journey-node consistency and overlap of problem scope",
    },
]

AGENT_FRAMEWORK = """Apply this reasoning framework and return strict JSON:
{"evidence_for_match": string, "evidence_against_match": string,
 "gap_assessment": string, "decision": "MATCH"|"MISMATCH", "confidence": number 0-1}
Do not invent facts outside the supplied canonical problem and backlog item."""


@dataclass
class CoverageVerdict:
    problem_id: str
    problem_title: str
    closest_backlog_id: str | None
    closest_backlog_title: str | None
    coverage_score: float
    coverage_status: str
    decision: str
    rationale: str
    grey_zone: dict[str, Any] | None = None
    lens_graduation: dict[str, Any] | None = None


@dataclass
class CoverageOutput:
    scores: np.ndarray
    verdicts: list[CoverageVerdict] = field(default_factory=list)
    model_name: str = "unfitted"
    provider: str = "unfitted"
    thresholds: dict[str, float] = field(default_factory=dict)


def _item_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(value).strip()
        for key in (
            "title",
            "problem_statement",
            "description",
            "canonical_description",
            "acceptance_criteria",
            "product_area",
            "intended_outcome",
            "customer_intent",
            "target_feature",
            "target_journey",
            "functional_scope",
        )
        if (value := item.get(key))
    )


class GreyZoneConsortium:
    def __init__(self, settings: Settings, client: StructuredLLMClient | None = None) -> None:
        self.settings = settings
        self.client = client or StructuredLLMClient(
            settings,
            provider="auto",
            timeout=settings.canonicalisation_timeout_seconds,
            temperature=settings.canonicalisation_temperature,
            max_attempts=settings.grey_zone_llm_max_attempts,
        )

    def _worker_client(self) -> StructuredLLMClient:
        if not isinstance(self.client, StructuredLLMClient):
            return self.client
        return StructuredLLMClient(
            self.settings,
            provider="auto",
            timeout=self.settings.canonicalisation_timeout_seconds,
            temperature=self.settings.canonicalisation_temperature,
            max_attempts=self.settings.grey_zone_llm_max_attempts,
        )

    def _heuristic(self, problem: dict[str, Any], backlog: dict[str, Any], score: float) -> str:
        overlap = len(token_set(_item_text(problem)) & token_set(_item_text(backlog)))
        midpoint = (self.settings.coverage_match_threshold + self.settings.coverage_mismatch_threshold) / 2
        return "MATCH" if score >= midpoint or overlap >= 6 else "MISMATCH"

    def _context(self, problem: dict[str, Any], backlog: dict[str, Any], score: float) -> str:
        return str(
            {
                "canonical_problem": {
                    "problem_id": problem.get("problem_id"),
                    "title": problem.get("title"),
                    "problem_statement": problem.get("problem_statement"),
                    "canonical_description": problem.get("canonical_description"),
                    "journey_node_id": problem.get("journey_node_id"),
                    "evidence_count": problem.get("evidence_count"),
                },
                "closest_backlog_item": {
                    "backlog_id": backlog.get("backlog_id"),
                    "title": backlog.get("title"),
                    "description": backlog.get("description"),
                    "acceptance_criteria": backlog.get("acceptance_criteria"),
                    "product_area": backlog.get("product_area"),
                    "intended_outcome": backlog.get("intended_outcome"),
                },
                "bge_cosine_score": round(float(score), 4),
                "grey_zone_band": [
                    self.settings.coverage_mismatch_threshold,
                    self.settings.coverage_match_threshold,
                ],
            }
        )

    def _parse_agent(self, payload: dict[str, Any], fallback: str, role: dict[str, str]) -> dict[str, Any]:
        decision = str(payload.get("decision") or "").upper()
        if decision not in {"MATCH", "MISMATCH"}:
            decision = fallback
        try:
            confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.5)))
        except (TypeError, ValueError):
            confidence = 0.5
        return {
            "role": role["key"],
            "name": role["name"],
            "lens": role["lens"],
            "decision": decision,
            "confidence": round(confidence, 3),
            "evidence_for_match": str(payload.get("evidence_for_match") or "")[:500],
            "evidence_against_match": str(payload.get("evidence_against_match") or "")[:500],
            "gap_assessment": str(payload.get("gap_assessment") or "")[:500],
        }

    def deliberate(self, problem: dict[str, Any], backlog: dict[str, Any], score: float) -> dict[str, Any]:
        fallback_decision = self._heuristic(problem, backlog, score)
        context = self._context(problem, backlog, score)
        roles = AGENT_ROLES[: max(1, min(4, self.settings.grey_zone_agent_count))]
        agents: list[dict[str, Any]] = []
        if self.settings.grey_zone_llm_enabled and self.client.available:
            for role in roles:
                prompt = (
                    f"You are the {role['name']} in a coverage adjudication consortium. "
                    f"Decide whether the closest backlog item fully matches the canonical problem. "
                    f"Your assigned lens: {role['lens']}.\n{AGENT_FRAMEWORK}\nContext:\n{context}"
                )
                model: str | None = None
                try:
                    response = self.client.generate_json(prompt)
                    agent = self._parse_agent(response.payload, fallback_decision, role)
                    model = response.model
                except LLMUnavailable:
                    agent = self._parse_agent({}, fallback_decision, role)
                agent["model"] = model
                agents.append(agent)
        if not agents:
            agents = [self._parse_agent({}, fallback_decision, role) for role in roles]

        votes = [agent["decision"] for agent in agents]
        majority = "MATCH" if votes.count("MATCH") > votes.count("MISMATCH") else "MISMATCH"
        chair = {
            "role": "chair",
            "name": "Adjudication Chair",
            "decision": majority,
            "confidence": round(sum(float(agent["confidence"]) for agent in agents) / len(agents), 3),
            "rationale": "Majority decision of the specialist consortium.",
            "model": None,
        }
        if self.settings.grey_zone_llm_enabled and self.client.available:
            chair_prompt = (
                "You chair a coverage adjudication consortium. Weigh the specialist assessments and give the "
                "final decision on whether the backlog item matches the canonical problem.\n"
                "Return strict JSON: {\"decision\":\"MATCH\"|\"MISMATCH\",\"confidence\":number 0-1,"
                "\"rationale\":string (max 400 chars)}\n"
                f"Context:\n{context}\nSpecialist assessments:\n{str(agents)}"
            )
            try:
                response = self.client.generate_json(chair_prompt)
                decision = str(response.payload.get("decision") or "").upper()
                chair["decision"] = decision if decision in {"MATCH", "MISMATCH"} else majority
                chair["confidence"] = max(
                    0.0, min(1.0, float(response.payload.get("confidence") or chair["confidence"]))
                )
                chair["rationale"] = str(response.payload.get("rationale") or chair["rationale"])[:400]
                chair["model"] = response.model
            except (LLMUnavailable, TypeError, ValueError):
                pass
        return {
            "agents": agents,
            "chair": chair,
            "final_decision": chair["decision"],
            "final_confidence": chair["confidence"],
            "rationale": chair["rationale"],
        }

    def _majority_chair(self, agents: list[dict[str, Any]]) -> dict[str, Any]:
        votes = [agent["decision"] for agent in agents]
        majority = "MATCH" if votes.count("MATCH") > votes.count("MISMATCH") else "MISMATCH"
        return {
            "role": "chair",
            "name": "Adjudication Chair",
            "decision": majority,
            "confidence": round(sum(float(agent["confidence"]) for agent in agents) / len(agents), 3),
            "rationale": "Majority decision of the specialist consortium.",
            "model": None,
        }

    def deliberate_batch(
        self, cases: list[tuple[dict[str, Any], dict[str, Any], float]]
    ) -> list[dict[str, Any]]:
        if not cases:
            return []
        roles = AGENT_ROLES[: max(1, min(4, self.settings.grey_zone_agent_count))]
        if not (self.settings.grey_zone_llm_enabled and self.client.available):
            return [self.deliberate(problem, backlog, score) for problem, backlog, score in cases]
        batch_size = max(1, min(100, self.settings.grey_zone_batch_size))
        contexts = [self._context(problem, backlog, score) for problem, backlog, score in cases]
        role_order = [role["key"] for role in roles]
        results: list[dict[str, Any] | None] = [None] * len(cases)

        for start in range(0, len(cases), batch_size):
            chunk = cases[start : start + batch_size]
            chunk_contexts = contexts[start : start + batch_size]
            agents_by_case: list[list[dict[str, Any]]] = [[] for _ in chunk]
            workers = max(1, min(4, self.settings.grey_zone_max_workers))
            if not isinstance(self.client, StructuredLLMClient):
                workers = 1

            def role_call(
                role: dict[str, str], case_contexts: list[str] = chunk_contexts
            ) -> tuple[dict[str, str], object, str | None]:
                prompt = (
                    f"You are the {role['name']} in a coverage adjudication consortium. "
                    f"Decide for every case whether the closest backlog item fully matches the canonical problem. "
                    f"Your assigned lens: {role['lens']}.\n{AGENT_FRAMEWORK}\n"
                    "Return strict JSON with key \"results\" whose value is an array with one object per case: "
                    '{"index": integer, "evidence_for_match": string, "evidence_against_match": string, '
                    '"gap_assessment": string, "decision": "MATCH"|"MISMATCH", "confidence": number 0-1}.\n'
                    "Cases:\n"
                    + json.dumps(
                        [{"index": offset, "context": context} for offset, context in enumerate(case_contexts)],
                        ensure_ascii=False,
                    )
                )
                try:
                    response = self._worker_client().generate_json(prompt)
                    return role, response.payload.get("results"), response.model
                except LLMUnavailable:
                    return role, None, None

            if workers == 1:
                role_results = [role_call(role) for role in roles]
            else:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    role_results = list(executor.map(role_call, roles))
            for role, rows, response_model in role_results:
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        try:
                            index = int(row.get("index"))
                        except (TypeError, ValueError):
                            continue
                        if 0 <= index < len(chunk):
                            fallback = self._heuristic(chunk[index][0], chunk[index][1], chunk[index][2])
                            agent = self._parse_agent(row, fallback, role)
                            agent["model"] = response_model
                            agents_by_case[index].append(agent)
            for index, (problem, backlog, score) in enumerate(chunk):
                fallback = self._heuristic(problem, backlog, score)
                present = {agent["role"] for agent in agents_by_case[index]}
                for role in roles:
                    if role["key"] not in present:
                        agent = self._parse_agent({}, fallback, role)
                        agent["model"] = None
                        agents_by_case[index].append(agent)
                agents_by_case[index].sort(key=lambda agent: role_order.index(agent["role"]))

            chair_prompt = (
                "You chair a coverage adjudication consortium. For every case, weigh the specialist assessments "
                "and give the final decision on whether the backlog item matches the canonical problem.\n"
                "Return strict JSON with key \"results\" whose value is an array with one object per case: "
                '{"index": integer, "decision": "MATCH"|"MISMATCH", "confidence": number 0-1, '
                '"rationale": string (max 400 chars)}.\n'
                "Cases:\n"
                + json.dumps(
                    [
                        {"index": index, "context": chunk_contexts[index], "specialists": agents}
                        for index, agents in enumerate(agents_by_case)
                    ],
                    ensure_ascii=False,
                )
            )
            chair_rows: object = None
            chair_model: str | None = None
            try:
                response = self._worker_client().generate_json(chair_prompt)
                chair_rows = response.payload.get("results")
                chair_model = response.model
            except LLMUnavailable:
                chair_rows = None
            chairs: list[dict[str, Any] | None] = [None] * len(chunk)
            if isinstance(chair_rows, list):
                for row in chair_rows:
                    if not isinstance(row, dict):
                        continue
                    try:
                        index = int(row.get("index"))
                    except (TypeError, ValueError):
                        continue
                    if 0 <= index < len(chunk):
                        chairs[index] = row
            for index, agents in enumerate(agents_by_case):
                chair = self._majority_chair(agents)
                row = chairs[index]
                if isinstance(row, dict):
                    decision = str(row.get("decision") or "").upper()
                    chair["decision"] = decision if decision in {"MATCH", "MISMATCH"} else chair["decision"]
                    try:
                        confidence = float(row.get("confidence") or chair["confidence"])
                    except (TypeError, ValueError):
                        confidence = float(chair["confidence"])
                    chair["confidence"] = max(0.0, min(1.0, confidence))
                    chair["rationale"] = str(row.get("rationale") or chair["rationale"])[:400]
                    chair["model"] = chair_model
                results[start + index] = {
                    "agents": agents,
                    "chair": chair,
                    "final_decision": chair["decision"],
                    "final_confidence": chair["confidence"],
                    "rationale": chair["rationale"],
                }
        return [result for result in results if result is not None]


class CoverageAssessment:
    def __init__(self, settings: Settings, consortium: GreyZoneConsortium | None = None) -> None:
        self.settings = settings
        self.consortium = consortium or GreyZoneConsortium(settings)

    def _status(self, score: float) -> str:
        if score >= self.settings.coverage_match_threshold:
            return "covered"
        if score < self.settings.coverage_mismatch_threshold:
            return "not_covered"
        return "grey_zone"

    def assess(
        self,
        canonical_problems: list[dict[str, Any]],
        backlog_items: list[dict[str, Any]],
        lens_associations: Mapping[str, LensAssociation] | None = None,
    ) -> CoverageOutput:
        thresholds = {
            "match": self.settings.coverage_match_threshold,
            "mismatch": self.settings.coverage_mismatch_threshold,
        }
        if not canonical_problems or not backlog_items:
            return CoverageOutput(
                scores=np.zeros((len(canonical_problems), len(backlog_items)), dtype=np.float32),
                model_name="empty",
                provider="empty",
                thresholds=thresholds,
            )
        embedder, problem_vectors, backlog_vectors = build_coverage_embedder(
            self.settings,
            [_item_text(item) for item in canonical_problems],
            [_item_text(item) for item in backlog_items],
        )
        raw = np.clip(problem_vectors @ backlog_vectors.T, -1.0, 1.0)
        scores = np.clip(raw, 0.0, 1.0).astype(np.float32)
        model_name = str(getattr(embedder, "model_name", "unknown"))
        provider = "bge_dense_cosine" if model_name.startswith("bge-") else "tfidf_fallback"
        score_label = "BGE cosine" if provider == "bge_dense_cosine" else "TF-IDF fallback cosine"
        verdicts: list[CoverageVerdict] = []
        grey_cases: list[tuple[dict[str, Any], dict[str, Any], float]] = []
        grey_positions: list[int] = []
        for problem_index, problem in enumerate(canonical_problems):
            backlog_index = int(np.argmax(scores[problem_index]))
            score = float(scores[problem_index][backlog_index])
            closest = backlog_items[backlog_index]
            status = self._status(score)
            decision = "MATCH" if status == "covered" else "MISMATCH"
            rationale = f"{score_label} coverage {score:.4f} against closest backlog item {closest.get('backlog_id')}."
            if status == "grey_zone":
                grey_positions.append(len(verdicts))
                grey_cases.append((problem, closest, score))
            verdicts.append(
                CoverageVerdict(
                    problem_id=str(problem.get("problem_id") or ""),
                    problem_title=str(problem.get("title") or ""),
                    closest_backlog_id=str(closest.get("backlog_id") or "") or None,
                    closest_backlog_title=str(closest.get("title") or "") or None,
                    coverage_score=round(score, 4),
                    coverage_status=status,
                    decision=decision,
                    rationale=rationale,
                    grey_zone=None,
                )
            )
        if grey_cases:
            deliberate_batch = getattr(self.consortium, "deliberate_batch", None)
            if callable(deliberate_batch):
                deliberations = deliberate_batch(grey_cases)
            else:
                deliberations = [self.consortium.deliberate(*case) for case in grey_cases]
            for position, deliberation in zip(grey_positions, deliberations, strict=False):
                verdicts[position].decision = deliberation["final_decision"]
                verdicts[position].rationale = deliberation["rationale"]
                verdicts[position].grey_zone = deliberation
        if lens_associations:
            for verdict in verdicts:
                association = lens_associations.get(verdict.problem_id)
                if association is None or verdict.coverage_status != "grey_zone" or verdict.decision != "MISMATCH":
                    continue
                if association.association_score <= self.settings.lens_graduation_threshold:
                    continue
                original_decision = verdict.decision
                graduation = {
                    "lens_name": association.lens_name,
                    "association_score": round(association.association_score, 4),
                    "signal_score": round(association.signal_score, 4),
                    "signal_score_threshold": self.settings.lens_graduation_signal_threshold,
                    "threshold": self.settings.lens_graduation_threshold,
                    "original_decision": original_decision,
                    "final_decision": "MATCH",
                    "shared_feedback_count": association.shared_feedback_count,
                    "rationale": (
                        f"{association.lens_name} signal (internal score {association.signal_score:.4f}, "
                        f"association {association.association_score:.4f}) graduated this grey-zone canonical "
                        "problem to the matched group despite the consortium MISMATCH decision."
                    ),
                }
                verdict.decision = "MATCH"
                verdict.coverage_status = "covered"
                verdict.lens_graduation = graduation
                verdict.rationale = f"{verdict.rationale} {graduation['rationale']}"
        return CoverageOutput(
            scores=scores,
            verdicts=verdicts,
            model_name=model_name,
            provider=provider,
            thresholds=thresholds,
        )
