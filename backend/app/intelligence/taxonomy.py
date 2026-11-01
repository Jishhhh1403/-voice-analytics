from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .text import token_set, tokenize


@dataclass
class TaxonomyNode:
    node_id: str
    parent_id: str | None
    node_type: str
    display_name: str
    description: str = ""
    synonyms: list[str] = field(default_factory=list)
    status: str = "active"
    aliases: list[str] = field(default_factory=list)

    def to_row(self, version: str) -> dict[str, Any]:
        import json
        from datetime import datetime, timezone

        return {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "node_id": self.node_id,
            "version": version,
            "parent_id": self.parent_id,
            "node_type": self.node_type,
            "display_name": self.display_name,
            "description": self.description,
            "synonyms_json": json.dumps(self.synonyms),
            "status": self.status,
            "aliases_json": json.dumps(self.aliases),
        }


class Taxonomy:
    def __init__(self, version: str, nodes: list[TaxonomyNode]) -> None:
        self.version = version
        self.nodes = [node for node in nodes if node.status == "active"]
        self.by_id = {node.node_id: node for node in self.nodes}
        self.children: dict[str | None, list[TaxonomyNode]] = {}
        for node in self.nodes:
            self.children.setdefault(node.parent_id, []).append(node)

    @classmethod
    def load(cls, path: Path) -> "Taxonomy":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        nodes = [
            TaxonomyNode(
                node_id=item["node_id"],
                parent_id=item.get("parent_id"),
                node_type=item.get("node_type", "feature"),
                display_name=item["display_name"],
                description=item.get("description", ""),
                synonyms=list(item.get("synonyms") or []),
                status=item.get("status", "active"),
                aliases=list(item.get("aliases") or []),
            )
            for item in data.get("nodes", [])
        ]
        return cls(str(data.get("version", "0.0.0")), nodes)

    def ancestors(self, node_id: str) -> list[TaxonomyNode]:
        result: list[TaxonomyNode] = []
        seen: set[str] = set()
        current = self.by_id.get(node_id)
        while current and current.node_id not in seen:
            seen.add(current.node_id)
            result.append(current)
            current = self.by_id.get(current.parent_id or "")
        return result

    def module_for(self, node_id: str | None) -> TaxonomyNode | None:
        if not node_id:
            return None
        chain = self.ancestors(node_id)
        for node in reversed(chain):
            if node.node_type == "module":
                return node
        return chain[-1] if chain else None

    def path_label(self, node_id: str) -> str:
        chain = list(reversed(self.ancestors(node_id)))
        return " / ".join(node.display_name for node in chain)

    def _score(self, node: TaxonomyNode, text: str, text_tokens: set[str]) -> float:
        score = 0.0
        lowered = text.lower()
        candidates = [node.display_name, *node.synonyms, *node.aliases]
        for candidate in candidates:
            candidate_lower = candidate.lower().strip()
            if not candidate_lower:
                continue
            if re.search(rf"\b{re.escape(candidate_lower)}\b", lowered):
                score += 3.0 if candidate_lower == node.display_name.lower() else 2.2
            else:
                overlap = len(token_set(candidate) & text_tokens)
                if overlap:
                    score += 0.5 * overlap
        if node.description:
            score += 0.25 * len(token_set(node.description) & text_tokens)
        if node.node_type == "module":
            score *= 0.92
        return round(score, 3)

    def best_node(self, text: str, allowed: set[str] | None = None, threshold: float = 1.4) -> tuple[TaxonomyNode | None, float]:
        text_tokens = token_set(text)
        best: TaxonomyNode | None = None
        best_score = 0.0
        for node in self.nodes:
            if allowed and node.node_id not in allowed:
                continue
            score = self._score(node, text, text_tokens)
            if score > best_score:
                best, best_score = node, score
        if best_score < threshold:
            return None, best_score
        return best, best_score

    def map_product_area(self, product_area: str | None) -> TaxonomyNode | None:
        if not product_area:
            return None
        alias = {
            "payments": "payments",
            "payment": "payments",
            "investments": "deposits",
            "investment": "deposits",
            "accounts": "accounts",
            "account": "accounts",
            "authentication": "authentication",
            "auth": "authentication",
            "cards": "cards",
            "card": "cards",
            "loans": "loans",
            "loan": "loans",
            "deposits": "deposits",
            "deposit": "deposits",
            "onboarding": "onboarding",
            "kyc": "onboarding",
            "support": "support",
            "notifications": "notifications",
            "navigation": "navigation",
            "statements": "statements",
            "beneficiaries": "beneficiaries",
            "beneficiary": "beneficiaries",
        }
        node_id = alias.get(product_area.lower().strip())
        if node_id:
            return self.by_id.get(node_id)
        node, _ = self.best_node(product_area)
        return node

    def tree(self) -> list[dict[str, Any]]:
        def build(parent_id: str | None) -> list[dict[str, Any]]:
            items = []
            for node in self.children.get(parent_id, []):
                items.append(
                    {
                        "node_id": node.node_id,
                        "parent_id": node.parent_id,
                        "node_type": node.node_type,
                        "display_name": node.display_name,
                        "description": node.description,
                        "synonyms": node.synonyms,
                        "status": node.status,
                        "children": build(node.node_id),
                    }
                )
            return items

        return build(None)

    def rows(self) -> list[dict[str, Any]]:
        return [node.to_row(self.version) for node in self.nodes]

    def keywords(self, node_id: str) -> list[str]:
        node = self.by_id.get(node_id)
        if not node:
            return []
        return [node.display_name, *node.synonyms, *node.aliases, *tokenize(node.description)]
