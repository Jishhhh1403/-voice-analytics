"""Structured banking taxonomy context for factor interpretation.

The context is domain knowledge supplied to the model. It is never evidence
that a particular failure occurred, and it does not add regulatory or technical
facts that are absent from the platform taxonomy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ....config import Settings
from ....repository import Repository

EXPECTED_BANKING_DOMAINS: tuple[str, ...] = (
    "Payments",
    "NEFT",
    "RTGS",
    "IMPS",
    "UPI",
    "Account management",
    "Fund transfers",
    "Deposits",
    "Cards",
    "Loans",
    "Authentication",
    "Digital banking access",
    "Statements",
    "Customer service",
    "Disputes and complaints",
)

JOURNEY_CONTEXT_FIELDS: tuple[str, ...] = (
    "journey",
    "journey_stage",
    "journey_node",
    "customer_action",
    "customer_intent",
    "customer_expectation",
    "observed_state",
    "transaction_state",
    "customer_reported_symptom",
    "customer_consequence",
    "workaround",
    "observed_failure_mechanism",
)

PROCESS_KNOWLEDGE: tuple[dict[str, Any], ...] = (
    {
        "stage": "transaction_initiation",
        "description": "Customer enters payment details and confirms the instruction.",
        "states": ["draft", "initiated", "abandoned"],
    },
    {
        "stage": "authentication_and_authorisation",
        "description": "Customer and transaction are authenticated and authorised before processing.",
        "states": ["authentication_pending", "authorised", "declined", "authentication_failed"],
    },
    {
        "stage": "account_debit",
        "description": "The funding account is debited where the rail and product require it.",
        "states": ["not_debited", "debit_pending", "debited", "debit_reversed"],
    },
    {
        "stage": "processing",
        "description": "The institution or rail processes the instruction; timing differs by rail.",
        "states": ["submitted", "in_progress", "held", "rejected"],
    },
    {
        "stage": "interbank_processing_or_settlement",
        "description": (
            "Interbank processing or settlement applies only to rails that use it. "
            "NEFT, RTGS, IMPS and UPI do not share one lifecycle or timing model."
        ),
        "states": ["queued", "in_settlement", "settled", "returned"],
    },
    {
        "stage": "beneficiary_credit",
        "description": "The beneficiary account is credited where the rail supports a credit leg.",
        "states": ["not_credited", "credit_pending", "credited", "credit_reversed"],
    },
    {
        "stage": "confirmation",
        "description": "A confirmation or reference is returned to the customer.",
        "states": ["awaiting_confirmation", "confirmed", "confirmation_delayed", "confirmation_missing"],
    },
    {
        "stage": "reversal_or_refund",
        "description": "Failed or disputed flows may require a reversal or refund.",
        "states": ["not_required", "requested", "in_progress", "completed", "rejected"],
    },
    {
        "stage": "transaction_status_visibility",
        "description": "The customer can see a reliable, current state and next step.",
        "states": ["visible", "stale", "missing", "ambiguous"],
    },
)

CAVEATS: tuple[str, ...] = (
    "Taxonomy context is domain knowledge, not evidence that a failure occurred.",
    "Payment rails do not share an identical lifecycle or settlement timing model.",
    "Do not invent regulatory, security, financial or technical facts outside the supplied taxonomy.",
    "A negative FAMD coefficient is the opposite direction along a dimension, not negative customer impact.",
)


class BankingTaxonomyContextBuilder:
    """Build a versioned, reusable banking context from repository taxonomy."""

    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo

    def _load_yaml_nodes(self) -> tuple[str, list[dict[str, Any]]]:
        path = Path(self.settings.taxonomy_path)
        if not path.exists():
            return "", []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return str(data.get("version", "")), list(data.get("nodes") or [])

    def build(self, taxonomy_version: str | None) -> dict[str, Any]:
        nodes = self.repo.get_taxonomy_nodes(taxonomy_version)
        yaml_version, yaml_nodes = self._load_yaml_nodes()
        if not nodes and yaml_nodes:
            nodes = [
                {
                    "node_id": item.get("node_id"),
                    "parent_id": item.get("parent_id"),
                    "node_type": item.get("node_type"),
                    "display_name": item.get("display_name"),
                    "description": item.get("description"),
                    "synonyms": list(item.get("synonyms") or []),
                }
                for item in yaml_nodes
            ]
        version = taxonomy_version or yaml_version or "unavailable"
        modules = [item for item in nodes if item.get("node_type") == "module"]
        features = [item for item in nodes if item.get("node_type") != "module"]
        supported_labels = " ".join(
            f"{item.get('display_name') or ''} {item.get('description') or ''}" for item in nodes
        ).casefold()
        missing = [
            domain
            for domain in EXPECTED_BANKING_DOMAINS
            if domain.casefold() not in supported_labels
            and not any(token in supported_labels for token in domain.casefold().split())
        ]
        domains = [
            {
                "node_id": item.get("node_id"),
                "display_name": item.get("display_name"),
                "description": item.get("description"),
                "synonyms": list(item.get("synonyms") or []),
            }
            for item in modules
        ]
        feature_context = [
            {
                "node_id": item.get("node_id"),
                "parent_id": item.get("parent_id"),
                "display_name": item.get("display_name"),
                "description": item.get("description"),
                "synonyms": list(item.get("synonyms") or []),
            }
            for item in features
        ]
        caveats = list(CAVEATS)
        if missing:
            caveats.append(
                "The current taxonomy does not explicitly enumerate these expected areas: "
                + ", ".join(missing)
                + ". Do not assume they are supported."
            )
        return {
            "version": version,
            "banking_domains": domains,
            "banking_features": feature_context,
            "journey_context_fields": list(JOURNEY_CONTEXT_FIELDS),
            "process_knowledge": [dict(item) for item in PROCESS_KNOWLEDGE],
            "missing_supported_domains": missing,
            "caveats": caveats,
        }
