"""Consolidate problem observations into dimension-level evidence."""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from ....config import Settings
from ....repository import Repository
from .contracts import DimensionEvidenceAggregation
from .gemini_client import StructuredLLMProvider

logger = logging.getLogger("bci.factor_interpretation")

SYSTEM_INSTRUCTION = """You are a senior banking customer-experience analyst consolidating evidence for one FAMD dimension.

You receive dimension variable/category contributions, accumulated problem observations and a banking
taxonomy context. Identify the underlying customer-experience construct that best explains the
pattern. Do not merely choose the most common words. Use the evidence references and preserve
canonical problem IDs exactly.

Rules:
- The dimension is an exploratory statistical pattern, not a proven root cause.
- A negative coordinate is the opposite direction along a dimension, not negative customer impact.
- Do not infer causal relationships.
- Distinguish recurring evidence, strongly aligned problems, oppositely positioned problems,
  outliers and problems that do not fit the emerging interpretation.
- Use banking taxonomy terminology, but do not invent regulatory or technical facts.
- If the evidence is weak or contradictory, say so and use an explicitly ambiguous construct.
- Return only the requested structured schema.
"""


class DimensionEvidenceAggregator:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        provider: StructuredLLMProvider,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.provider = provider

    def _reference_stats(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        alignment = Counter(item.get("alignment") or "unknown" for item in observations)
        journeys = Counter()
        symptoms = Counter()
        intents = Counter()
        states = Counter()
        for item in observations:
            if item.get("banking_journey_interpretation"):
                journeys[item["banking_journey_interpretation"][:180]] += 1
            if item.get("observed_symptom"):
                symptoms[item["observed_symptom"][:180]] += 1
            if item.get("customer_intent"):
                intents[item["customer_intent"][:180]] += 1
            if item.get("transaction_state"):
                states[item["transaction_state"][:180]] += 1
        return {
            "alignment_counts": dict(sorted(alignment.items())),
            "frequent_journey_interpretations": journeys.most_common(10),
            "frequent_symptoms": symptoms.most_common(10),
            "frequent_intents": intents.most_common(10),
            "frequent_transaction_states": states.most_common(10),
        }

    def run(
        self,
        run_id: str,
        dimension_id: str,
        *,
        observations: list[dict[str, Any]],
        taxonomy_context: dict[str, Any],
        dimension_evidence: dict[str, Any],
        force: bool = False,
    ) -> dict[str, Any]:
        if not force:
            existing = self.repo.get_dimension_aggregation(run_id, dimension_id)
            if existing and existing.get("status") == "OK" and existing.get("aggregation"):
                return {"status": "COMPLETED", "aggregation": existing["aggregation"]}
        if not observations:
            self.repo.save_dimension_aggregation(
                run_id,
                dimension_id,
                status="FAILED",
                aggregation=None,
                prompt_version=self.settings.problem_dimension_aggregation_prompt_version,
                model_name=self.provider.model_id,
                error="No successful problem observations are available.",
            )
            return {"status": "FAILED", "aggregation": None, "error": "No observations"}

        prompt = json.dumps(
            {
                "prompt_version": self.settings.problem_dimension_aggregation_prompt_version,
                "analysis_run_id": run_id,
                "dimension_id": dimension_id,
                "coefficient_interpretation": (
                    "Signed FAMD coordinates describe latent-dimension position. They are not causal effects."
                ),
                "dimension_evidence": dimension_evidence,
                "deterministic_reference_statistics": self._reference_stats(observations),
                "banking_taxonomy_context": taxonomy_context,
                "observations": observations,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            raw = self.provider.generate(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=prompt,
                schema=DimensionEvidenceAggregation.model_json_schema(),
                prompt_version=self.settings.problem_dimension_aggregation_prompt_version,
                metadata={"run_id": run_id, "dimension_id": dimension_id, "stage": "aggregation"},
            )
            aggregation = DimensionEvidenceAggregation.model_validate(raw).model_dump()
            known_ids = {item["canonical_problem_id"] for item in observations}
            for key in (
                "strongly_aligned_problem_ids",
                "oppositely_positioned_problem_ids",
                "outlier_problem_ids",
                "non_fitting_problem_ids",
                "evidence_references",
            ):
                aggregation[key] = [value for value in aggregation.get(key, []) if value in known_ids]
            self.repo.save_dimension_aggregation(
                run_id,
                dimension_id,
                status="OK",
                aggregation=aggregation,
                prompt_version=self.settings.problem_dimension_aggregation_prompt_version,
                model_name=self.provider.model_id,
            )
            return {"status": "COMPLETED", "aggregation": aggregation}
        except Exception as exc:
            logger.warning(
                "evidence aggregation failed run=%s dimension=%s error=%s", run_id, dimension_id, exc
            )
            self.repo.save_dimension_aggregation(
                run_id,
                dimension_id,
                status="FAILED",
                aggregation=None,
                prompt_version=self.settings.problem_dimension_aggregation_prompt_version,
                model_name=self.provider.model_id,
                error=str(exc),
            )
            return {"status": "FAILED", "aggregation": None, "error": str(exc)}
