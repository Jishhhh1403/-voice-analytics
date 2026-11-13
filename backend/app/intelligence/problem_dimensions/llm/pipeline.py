"""Orchestration for factor-equation LLM nomenclature."""

from __future__ import annotations

import logging
from typing import Any

from ....config import Settings
from ....repository import Repository, now_iso
from .equation_serializer import FactorEquationSerializer
from .factor_equations import FACTOR_EQUATION_VERSION, FactorEquationBuilder
from .gemini_client import StructuredLLMProvider, build_structured_provider
from .nomenclature import LLMFactorNomenclatureGenerator
from .taxonomy_context import BankingTaxonomyContextBuilder
from .validation import NomenclatureValidationService

logger = logging.getLogger("bci.factor_interpretation")


class LLMFactorInterpretationPipeline:
    """Name every retained factor directly from its complete FAMD factor equation."""

    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        provider: StructuredLLMProvider | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.provider = provider if provider is not None else build_structured_provider(settings)
        self.taxonomy_builder = BankingTaxonomyContextBuilder(settings, repo)
        self.serializer = FactorEquationSerializer(repo)
        self.factor_equations = FactorEquationBuilder(repo)
        self.validator = NomenclatureValidationService()

    @property
    def available(self) -> bool:
        return self.provider is not None

    def _dimension_ids(self, run: dict[str, Any]) -> list[str]:
        definitions = run.get("definitions") or []
        if definitions:
            return [
                item["dimension_id"]
                for item in sorted(
                    definitions,
                    key=lambda item: (item.get("dimension_number") or 9999, item["dimension_id"]),
                )
            ]
        return self.serializer._affected_dimension_ids(run["run_id"])

    def _known_evidence(self, contract: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
        variables: set[str] = set()
        categories: set[str] = set()
        problem_ids: set[str] = set()
        for problem in contract["problems"]:
            problem_ids.add(problem["canonical_problem_id"])
            for evidence in problem["dimension_evidence"].values():
                for item in evidence.get("top_variables") or []:
                    if item.get("variable_name"):
                        variables.add(str(item["variable_name"]))
                for item in evidence.get("top_categories") or []:
                    if item.get("variable_name") and item.get("category_level"):
                        categories.add(f"{item['variable_name']}={item['category_level']}")
        for item in self.repo.get_dimension_contributions(contract["analysis_run_id"]):
            if item.get("variable_name"):
                variables.add(str(item["variable_name"]))
            if item.get("variable_name") and item.get("category_level"):
                categories.add(f"{item['variable_name']}={item['category_level']}")
        return variables, categories, problem_ids

    def _approved_nomenclature(self, run: dict[str, Any], exclude_dimension: str) -> list[dict[str, Any]]:
        items = []
        for definition in run.get("definitions") or []:
            if definition["dimension_id"] == exclude_dimension:
                continue
            if definition.get("review_status") not in {"APPROVED", "PUBLISHED"}:
                continue
            items.append(
                {
                    "dimension_id": definition["dimension_id"],
                    "factor_id": f"F{definition.get('dimension_number')}",
                    "business_name": definition.get("analyst_name"),
                    "definition": definition.get("description"),
                }
            )
        return items

    def _other_dimension_summaries(
        self,
        equations: dict[str, dict[str, Any]],
        exclude_dimension: str,
    ) -> list[dict[str, Any]]:
        summaries = []
        for dimension_id, equation in equations.items():
            if dimension_id == exclude_dimension:
                continue
            summaries.append(
                {
                    "dimension_id": dimension_id,
                    "factor_id": equation.get("factor_id"),
                    "top_variables": [
                        item.get("variable_name")
                        for item in equation.get("variable_contributions") or []
                    ][:8],
                    "top_categories": [
                        f"{item.get('variable_name')}={item.get('category_level')}"
                        for item in equation.get("category_contributions") or []
                    ][:8],
                }
            )
        return summaries

    def _apply_proposal(
        self,
        run_id: str,
        dimension_id: str,
        proposal: dict[str, Any],
        *,
        taxonomy_version: str,
        review_status: str,
        prompt_version: str,
    ) -> None:
        self.repo.update_dimension_definition(
            run_id,
            dimension_id,
            analyst_name=proposal["proposed_name"],
            proposed_label=proposal["proposed_name"],
            short_name=proposal.get("short_name"),
            description=proposal.get("formal_definition"),
            business_interpretation=proposal.get("business_interpretation"),
            interpretation_status="DRAFT",
            review_status=review_status,
            nomenclature_source="LLM",
            prompt_version=prompt_version,
            model_name=self.provider.model_id if self.provider else None,
            llm_analysis_run_id=run_id,
            taxonomy_version=taxonomy_version,
            generated_at=now_iso(),
            banking_domain=proposal.get("banking_domain"),
            journey_scope=proposal.get("journey_scope"),
            core_customer_experience=proposal.get("core_customer_experience"),
            supporting_variables=proposal.get("supporting_variables") or [],
            supporting_categories=proposal.get("supporting_categories") or [],
            contradictory_problem_ids=proposal.get("contradictory_problem_ids") or [],
            distinguishing_characteristics=proposal.get("distinguishing_characteristics"),
            nomenclature_status=proposal.get("nomenclature_status"),
            confidence=proposal.get("confidence"),
            confidence_explanation=proposal.get("confidence_explanation"),
            representative_problem_ids=proposal.get("representative_problem_ids") or [],
        )

    def _apply_cross_review(
        self,
        run_id: str,
        review: dict[str, Any],
        proposals: dict[str, dict[str, Any]],
        *,
        taxonomy_version: str,
    ) -> None:
        for finding in review.get("findings") or []:
            for dimension_id, name in (finding.get("recommended_names") or {}).items():
                proposal = proposals.get(dimension_id)
                if not proposal:
                    continue
                if not isinstance(name, str) or not name.strip() or len(name) > 160:
                    continue
                lower = name.casefold()
                if any(token in lower for token in ("f1", "f2", "f3", "d1", "d2", "dim.")):
                    continue
                proposal["proposed_name"] = name.strip()
                proposal["nomenclature_status"] = "REVIEW_REQUIRED"
                stored = self.repo.get_nomenclature_proposal(run_id, dimension_id)
                self.repo.save_nomenclature_proposal(
                    run_id,
                    dimension_id,
                    proposal["factor_id"],
                    status="CROSS_REVIEW_REVISED",
                    proposal=proposal,
                    original_proposal=(stored or {}).get("original_proposal") or proposal,
                    cross_review=review,
                    validation=(stored or {}).get("validation"),
                    prompt_version=self.settings.problem_dimension_cross_review_prompt_version,
                    model_name=self.provider.model_id if self.provider else None,
                )
                self._apply_proposal(
                    run_id,
                    dimension_id,
                    proposal,
                    taxonomy_version=taxonomy_version,
                    review_status="DRAFT",
                    prompt_version=self.settings.problem_dimension_cross_review_prompt_version,
                )

    def run(
        self,
        run_id: str,
        *,
        force: bool = False,
        auto_approve: bool = False,
        focus_problem_id: str | None = None,
    ) -> dict[str, Any]:
        run = self.repo.get_dimension_run(run_id)
        if not run:
            raise KeyError(run_id)
        if not self.available:
            return {
                "status": "UNAVAILABLE",
                "reason": "No LLM provider is configured; factors remain unnamed until one is available.",
                "dimensions": {},
            }
        contract = self.serializer.serialize(run_id)
        equations = self.factor_equations.build(
            contract,
            focus_problem_id=focus_problem_id,
        )
        dimension_ids = self._dimension_ids(run)
        feedback_run = self.repo.get_run(run.get("feedback_run_id") or "")
        taxonomy_context = self.taxonomy_builder.build((feedback_run or {}).get("taxonomy_version"))
        known_variables, known_categories, known_problem_ids = self._known_evidence(contract)
        generator = LLMFactorNomenclatureGenerator(self.settings, self.repo, self.provider)
        summary: dict[str, Any] = {}
        proposals: dict[str, dict[str, Any]] = {}
        changed = False

        for dimension_id in dimension_ids:
            existing_proposal = self.repo.get_nomenclature_proposal(run_id, dimension_id)
            definition = next(
                (item for item in run.get("definitions") or [] if item["dimension_id"] == dimension_id),
                {},
            )
            if (
                not force
                and existing_proposal
                and existing_proposal.get("status") in {
                    "PROPOSED",
                    "CROSS_REVIEW_PASSED",
                    "CROSS_REVIEW_REVISED",
                    "VALIDATED",
                }
                and definition.get("nomenclature_source") == "LLM"
            ):
                proposals[dimension_id] = existing_proposal.get("proposal") or {}
                summary[dimension_id] = {
                    "status": "COMPLETED",
                    "resumed": True,
                    "nomenclature_status": (existing_proposal.get("proposal") or {}).get(
                        "nomenclature_status"
                    ),
                }
                continue
            if definition.get("review_status") in {"APPROVED", "PUBLISHED"}:
                summary[dimension_id] = {
                    "status": "SKIPPED_APPROVED",
                    "reason": "Analyst-approved nomenclature is preserved.",
                }
                continue
            factor_id = (
                f"F{definition.get('dimension_number')}"
                if definition.get("dimension_number")
                else dimension_id.replace("D", "F", 1)
            )
            factor_equation = equations.get(dimension_id)
            if not factor_equation:
                summary[dimension_id] = {
                    "status": "FAILED",
                    "stage": "factor_equation",
                    "error": "No factor equation could be built for this dimension.",
                }
                continue
            try:
                self.repo.update_dimension_llm_processing(
                    run_id,
                    dimension_id,
                    stage="NOMENCLATURE",
                    status="RUNNING",
                    total_problems=factor_equation.get("problem_count") or 0,
                    processed_problems=factor_equation.get("problem_count") or 0,
                    failed_problems=0,
                    prompt_version=self.settings.problem_dimension_factor_nomenclature_prompt_version,
                    model_name=self.provider.model_id,
                    started_at=now_iso(),
                    completed_at=None,
                    error=None,
                )
                self.repo.save_dimension_aggregation(
                    run_id,
                    dimension_id,
                    status="COMPLETED",
                    aggregation=factor_equation,
                    prompt_version=FACTOR_EQUATION_VERSION,
                    model_name=None,
                )
                nomenclature_result = generator.generate(
                    run_id,
                    dimension_id,
                    factor_id,
                    taxonomy_context=taxonomy_context,
                    factor_equation=factor_equation,
                    approved_nomenclature=self._approved_nomenclature(run, dimension_id),
                    other_dimension_summaries=self._other_dimension_summaries(equations, dimension_id),
                )
                proposal = nomenclature_result.get("proposal")
                if not proposal:
                    self.repo.update_dimension_llm_processing(
                        run_id,
                        dimension_id,
                        stage="FAILED",
                        status="FAILED",
                        error=nomenclature_result.get("error"),
                        completed_at=now_iso(),
                    )
                    summary[dimension_id] = {
                        "status": "FAILED",
                        "stage": "nomenclature",
                        "error": nomenclature_result.get("error"),
                    }
                    continue
                validation = self.validator.validate_proposal(
                    proposal,
                    dimension_id=dimension_id,
                    factor_id=factor_id,
                    known_variables=known_variables,
                    known_categories=known_categories,
                    known_problem_ids=known_problem_ids,
                )
                if validation["status"] != "PASSED":
                    self.repo.save_nomenclature_proposal(
                        run_id,
                        dimension_id,
                        factor_id,
                        status="INVALID",
                        proposal=proposal,
                        cross_review=None,
                        validation=validation,
                        prompt_version=self.settings.problem_dimension_factor_nomenclature_prompt_version,
                        model_name=self.provider.model_id,
                    )
                    self.repo.update_dimension_llm_processing(
                        run_id,
                        dimension_id,
                        stage="FAILED",
                        status="FAILED",
                        error="; ".join(validation["errors"]),
                        completed_at=now_iso(),
                    )
                    summary[dimension_id] = {
                        "status": "FAILED",
                        "stage": "validation",
                        "error": "; ".join(validation["errors"]),
                    }
                    continue
                review_status = "APPROVED" if auto_approve else "DRAFT"
                self._apply_proposal(
                    run_id,
                    dimension_id,
                    proposal,
                    taxonomy_version=taxonomy_context["version"],
                    review_status=review_status,
                    prompt_version=self.settings.problem_dimension_factor_nomenclature_prompt_version,
                )
                self.repo.save_nomenclature_proposal(
                    run_id,
                    dimension_id,
                    factor_id,
                    status="PROPOSED",
                    proposal=proposal,
                    cross_review=None,
                    validation=validation,
                    prompt_version=self.settings.problem_dimension_factor_nomenclature_prompt_version,
                    model_name=self.provider.model_id,
                )
                self.repo.update_dimension_llm_processing(
                    run_id,
                    dimension_id,
                    stage="COMPLETED",
                    status="COMPLETED",
                    completed_at=now_iso(),
                    error=None,
                )
                proposals[dimension_id] = proposal
                changed = True
                summary[dimension_id] = {
                    "status": "COMPLETED",
                    "proposed_name": proposal.get("proposed_name"),
                    "confidence": proposal.get("confidence"),
                    "nomenclature_status": proposal.get("nomenclature_status"),
                    "factor_problem_count": factor_equation.get("problem_count"),
                    "validation_warnings": validation.get("warnings") or [],
                }
            except Exception as exc:
                logger.exception(
                    "factor nomenclature failed run=%s dimension=%s", run_id, dimension_id
                )
                self.repo.update_dimension_llm_processing(
                    run_id,
                    dimension_id,
                    stage="FAILED",
                    status="FAILED",
                    error=str(exc),
                    completed_at=now_iso(),
                )
                summary[dimension_id] = {"status": "FAILED", "error": str(exc)}

        cross_review: dict[str, Any] | None = None
        needs_review = changed or any(
            not (self.repo.get_nomenclature_proposal(run_id, dimension_id) or {}).get(
                "cross_review"
            )
            for dimension_id in proposals
        )
        if (
            self.settings.problem_dimension_llm_cross_review
            and len(proposals) > 1
            and needs_review
        ):
            catalogue = [
                {
                    "dimension_id": dimension_id,
                    "factor_id": proposal.get("factor_id"),
                    "proposed_name": proposal.get("proposed_name"),
                    "short_name": proposal.get("short_name"),
                    "formal_definition": proposal.get("formal_definition"),
                    "banking_domain": proposal.get("banking_domain"),
                    "core_customer_experience": proposal.get("core_customer_experience"),
                }
                for dimension_id, proposal in proposals.items()
            ]
            dimension_summaries = [
                {
                    "dimension_id": dimension_id,
                    "proposed_name": proposal.get("proposed_name"),
                    "supporting_variables": proposal.get("supporting_variables"),
                    "distinguishing_characteristics": proposal.get("distinguishing_characteristics"),
                }
                for dimension_id, proposal in proposals.items()
            ]
            review_result = generator.cross_review(
                run_id,
                catalogue=catalogue,
                dimension_summaries=dimension_summaries,
                taxonomy_context=taxonomy_context,
            )
            cross_review = review_result.get("review")
            if cross_review:
                self._apply_cross_review(
                    run_id,
                    cross_review,
                    proposals,
                    taxonomy_version=taxonomy_context["version"],
                )
                for dimension_id, proposal in proposals.items():
                    stored = self.repo.get_nomenclature_proposal(run_id, dimension_id)
                    if not stored:
                        continue
                    self.repo.save_nomenclature_proposal(
                        run_id,
                        dimension_id,
                        proposal.get("factor_id") or stored.get("factor_id"),
                        status=stored.get("status") or "PROPOSED",
                        proposal=stored.get("proposal") or proposal,
                        original_proposal=stored.get("original_proposal") or proposal,
                        cross_review=cross_review,
                        validation=stored.get("validation"),
                        prompt_version=(
                            self.settings.problem_dimension_cross_review_prompt_version
                            if stored.get("status") == "CROSS_REVIEW_REVISED"
                            else stored.get("prompt_version")
                        ),
                        model_name=stored.get("model_name")
                        or (self.provider.model_id if self.provider else None),
                    )
        deterministic_overlap = self.validator.detect_overlaps(
            [
                {
                    "dimension_id": dimension_id,
                    "factor_id": proposal.get("factor_id"),
                    "proposed_name": proposal.get("proposed_name"),
                }
                for dimension_id, proposal in proposals.items()
            ]
        )
        completed = sum(1 for item in summary.values() if item.get("status") == "COMPLETED")
        return {
            "status": "COMPLETED" if completed == len(dimension_ids) else ("PARTIAL" if completed else "FAILED"),
            "dimensions": summary,
            "focused_problem_id": focus_problem_id,
            "cross_dimension_review": cross_review,
            "overlap_check": deterministic_overlap,
            "taxonomy_version": taxonomy_context["version"],
            "prompt_versions": {
                "factor_equation": FACTOR_EQUATION_VERSION,
                "factor_nomenclature": self.settings.problem_dimension_factor_nomenclature_prompt_version,
                "cross_review": self.settings.problem_dimension_cross_review_prompt_version,
            },
        }


def build_interpretation_pipeline(
    settings: Settings,
    repo: Repository,
    provider: StructuredLLMProvider | None = None,
) -> LLMFactorInterpretationPipeline:
    return LLMFactorInterpretationPipeline(settings, repo, provider)
