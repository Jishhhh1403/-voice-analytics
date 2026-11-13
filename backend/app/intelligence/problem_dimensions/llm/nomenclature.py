"""LLM factor nomenclature and cross-dimension consistency review."""

from __future__ import annotations

import json
import logging
from typing import Any

from ....config import Settings
from ....repository import Repository
from .contracts import CrossDimensionReview, FactorNomenclatureProposal
from .gemini_client import StructuredLLMProvider

logger = logging.getLogger("bci.factor_interpretation")

NOMENCLATURE_SYSTEM_INSTRUCTION = """You are a senior banking product and customer-experience leader naming one exploratory FAMD factor.

You receive one complete factor equation: variable and category contributions, representative problem
equations, positively and negatively positioned problems, data quality, banking taxonomy context and
existing approved names for other factors. When focused_problem_equation is present, that analyst-selected
problem and its full equation must be considered directly when naming every factor.

Produce a business name and definition that:
1. Describes the underlying customer-experience construct.
2. Uses meaningful banking/business terminology.
3. Is understandable to Product Owners and leadership.
4. Does not simply join variable names.
5. Is neither excessively broad nor overly technical.
6. Distinguishes itself from the other retained factors.
7. Is supported by the supplied factor equation and canonical problem evidence.

Rules:
- Never write F1, F2, D1, Dim.1 or any technical identifier as the proposed business name.
- A negative coordinate is the opposite direction along a factor, not negative customer impact.
- Do not infer causal relationships, revenue impact, churn, regulatory risk or verified facts.
- Do not invent banking facts outside the supplied taxonomy.
- If evidence does not support a clear interpretation, return an explicitly ambiguous or provisional
  nomenclature instead of inventing a name.
- Return only the requested structured schema.
"""

CROSS_REVIEW_SYSTEM_INSTRUCTION = """You are a senior banking analytics reviewer checking a factor nomenclature catalogue.

Assess whether dimensions overlap in meaning, whether names are too broad or too technical, whether two
dimensions appear to describe the same customer-experience construct, whether a name uses variables that
belong more strongly to another dimension, whether terminology is consistent, and whether all dimensions
have distinct business interpretations.

Rules:
- Do not alter FAMD coordinates, dimension IDs, variable contributions or factor assignments.
- Do not merge or reassign statistical dimensions.
- Recommendations may request human review or propose revised names only.
- Return only the requested structured schema.
"""


class LLMFactorNomenclatureGenerator:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        provider: StructuredLLMProvider,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.provider = provider

    def generate(
        self,
        run_id: str,
        dimension_id: str,
        factor_id: str,
        *,
        taxonomy_context: dict[str, Any],
        factor_equation: dict[str, Any],
        approved_nomenclature: list[dict[str, Any]],
        other_dimension_summaries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt_version = self.settings.problem_dimension_factor_nomenclature_prompt_version
        prompt = json.dumps(
            {
                "prompt_version": prompt_version,
                "analysis_run_id": run_id,
                "required_dimension_id": dimension_id,
                "required_factor_id": factor_id,
                "factor_equation": factor_equation,
                "banking_taxonomy_context": taxonomy_context,
                "existing_approved_nomenclature": approved_nomenclature,
                "other_retained_factor_summaries": other_dimension_summaries,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            raw = self.provider.generate(
                system_instruction=NOMENCLATURE_SYSTEM_INSTRUCTION,
                prompt=prompt,
                schema=FactorNomenclatureProposal.model_json_schema(),
                prompt_version=prompt_version,
                metadata={"run_id": run_id, "dimension_id": dimension_id, "stage": "factor_nomenclature"},
            )
            proposal = FactorNomenclatureProposal.model_validate(raw).model_dump()
            proposal["factor_id"] = factor_id
            proposal["dimension_id"] = dimension_id
            return {"status": "PROPOSED", "proposal": proposal}
        except Exception as exc:
            logger.warning(
                "factor nomenclature generation failed run=%s dimension=%s error=%s",
                run_id,
                dimension_id,
                exc,
            )
            return {"status": "FAILED", "proposal": None, "error": str(exc)}

    def cross_review(
        self,
        run_id: str,
        *,
        catalogue: list[dict[str, Any]],
        dimension_summaries: list[dict[str, Any]],
        taxonomy_context: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = json.dumps(
            {
                "prompt_version": self.settings.problem_dimension_cross_review_prompt_version,
                "analysis_run_id": run_id,
                "factor_catalogue": catalogue,
                "dimension_summaries": dimension_summaries,
                "banking_taxonomy_context": taxonomy_context,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            raw = self.provider.generate(
                system_instruction=CROSS_REVIEW_SYSTEM_INSTRUCTION,
                prompt=prompt,
                schema=CrossDimensionReview.model_json_schema(),
                prompt_version=self.settings.problem_dimension_cross_review_prompt_version,
                metadata={"run_id": run_id, "stage": "cross_dimension_review"},
            )
            review = CrossDimensionReview.model_validate(raw).model_dump()
            return {"status": review["status"], "review": review}
        except Exception as exc:
            logger.warning("cross-dimension review failed run=%s error=%s", run_id, exc)
            return {"status": "FAILED", "review": None, "error": str(exc)}
