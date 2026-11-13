from __future__ import annotations

import csv
import hashlib
import io
import logging
import threading
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..config import Settings
from ..intelligence import lexicon
from ..intelligence.contracts import BacklogProfile
from ..intelligence.retrieval import HybridRetriever
from ..intelligence.taxonomy import Taxonomy
from ..intelligence.text import jaccard, token_set, tokenize
from ..repository import Repository, now_iso
from ..storage import ObjectStore, build_object_store

logger = logging.getLogger("bci.backlog")

REQUIRED_COLUMNS = ["backlog_id", "title", "description"]
OPTIONAL_COLUMNS = [
    "acceptance_criteria",
    "product_area",
    "priority",
    "business_goal",
    "source_system",
    "intended_outcome",
    "customer_intent",
    "target_feature",
    "target_journey",
    "functional_scope",
    "organisational_objective",
]
MAX_ROWS = 1000

SYMPTOM_COVERAGE_TERMS: dict[str, list[str]] = {
    "pending": ["pending", "status", "success", "failed", "progress", "what to do", "reference", "resolution"],
    "failure": ["failed", "failure", "error", "retry", "actionable", "what to do", "recover"],
    "delayed": ["delay", "time", "expected", "progress", "status", "timely"],
    "timeout": ["timeout", "expiry", "retry", "resend", "code", "progress", "wait"],
    "invalid": ["invalid", "validate", "validation", "error message", "correct", "actionable"],
    "duplicate": ["duplicate", "twice", "confirm", "idempot", "warning", "prevent"],
    "display": ["pdf", "readable", "preview", "generate", "download", "error", "blank"],
    "state": ["save", "confirm", "saved", "persist", "setting", "restore", "resume", "progress"],
    "session": ["session", "expiry", "warning", "re-authentication", "preserve", "return", "progress"],
    "discoverability": ["find", "search", "navigation", "locate", "dashboard", "menu", "access", "visible"],
    "receipt": ["status", "update", "notification", "track", "alert", "received", "confirmation"],
    "clarity": ["status", "pending", "success", "failed", "explain", "next step", "reference", "reason"],
    "consistency": ["amount", "confirmation", "summary", "rate", "display", "consistent", "validate"],
    "accuracy": ["amount", "confirmation", "summary", "rate", "display", "consistent"],
    "missing": ["show", "display", "provide", "visible", "access", "update", "track", "status"],
    "blocked": ["upload", "progress", "retry", "error", "status", "recover", "restore"],
    "performance": ["performance", "loading", "fast", "responsive", "progress", "time"],
    "stability": ["stability", "crash", "freeze", "recover", "error", "responsive"],
    "security": ["security", "secure", "verify", "alert", "protect", "confirm"],
    "general": ["status", "clear", "explain", "error", "update", "support", "confirmation"],
}


def split_criteria(value: str) -> list[str]:
    raw = (value or "").replace("|", ";").replace("\r", "\n")
    parts = [part.strip(" -•\t") for part in raw.replace("\n", ";").split(";")]
    return [part for part in parts if part]


def _risky_cell(value: str) -> bool:
    return bool(value) and value[0] in ("=", "+", "-", "@", "\t", "\r")


def parse_backlog_csv(data: bytes, upload_id: str, settings: Settings) -> dict[str, Any]:
    if not data:
        raise ValueError("uploaded file is empty")
    if len(data) > settings.max_backlog_bytes:
        raise ValueError("uploaded file exceeds the configured maximum size")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("backlog CSV must be UTF-8 (with optional BOM)") from exc
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [header.strip() for header in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise ValueError("missing required columns: " + ", ".join(missing))

    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    row_count = 0
    for row_number, raw_row in enumerate(reader, start=2):
        row_count += 1
        if row_count > MAX_ROWS:
            raise ValueError(f"backlog rows exceed maximum of {MAX_ROWS}")
        row = {str(key).strip(): (value or "").strip() for key, value in raw_row.items() if key is not None}
        backlog_id = row.get("backlog_id", "")
        title = row.get("title", "")
        description = row.get("description", "")
        problems: list[str] = []
        if not backlog_id:
            problems.append("missing backlog_id")
        elif backlog_id in seen_ids:
            problems.append("duplicate backlog_id")
        if not title:
            problems.append("missing title")
        if not description:
            problems.append("missing description")
        if any(_risky_cell(row.get(column, "")) for column in REQUIRED_COLUMNS + OPTIONAL_COLUMNS if column in row):
            warnings.append(f"Row {row_number}: potential CSV formula-injection content was neutralised on export.")
        if problems:
            errors.append({"row_number": row_number, "backlog_id": backlog_id, "errors": problems})
            continue
        seen_ids.add(backlog_id)
        criteria = split_criteria(row.get("acceptance_criteria", ""))
        if not criteria:
            warnings.append(f"Row {row_number}: no acceptance criteria supplied; AC coverage will be reported as unknown.")
        items.append(
            {
                "backlog_id": backlog_id,
                "row_number": row_number,
                "title": title,
                "description": description,
                "acceptance_criteria": row.get("acceptance_criteria", ""),
                "product_area": row.get("product_area") or None,
                "priority": row.get("priority") or None,
                "business_goal": row.get("business_goal") or None,
                "source_system": row.get("source_system") or None,
                "intended_outcome": row.get("intended_outcome") or None,
                "customer_intent": row.get("customer_intent") or None,
                "target_feature": row.get("target_feature") or None,
                "target_journey": row.get("target_journey") or None,
                "functional_scope": row.get("functional_scope") or None,
                "organisational_objective": row.get("organisational_objective") or None,
                "structured": {
                    "criteria": criteria,
                    "criteria_count": len(criteria),
                    "acceptance_criteria_items": criteria,
                },
            }
        )
    return {
        "items": items,
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "total_rows": row_count,
        "valid_rows": len(items),
        "invalid_rows": len(errors),
        "upload_id": upload_id,
    }


def csv_template() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
    writer.writerow(
        [
            "BL-1234",
            "Improve pending transfer clarity",
            "Make the pending state of transfers explain what happens next.",
            "Show clear pending/success/failed state; Explain expected resolution time; Provide a transaction reference",
            "Payments",
            "High",
            "Reduce avoidable payment complaints",
            "Jira",
            "Customers understand what happens next when a transfer is pending",
            "transfer_money",
            "transfer_status",
            "payments.transfer_status",
            "Customer-facing status messaging and reference details",
            "Reduce contact-centre demand and duplicate payment attempts",
        ]
    )
    return output.getvalue()


class BacklogValidationService:
    def __init__(self, settings: Settings, repo: Repository, store: ObjectStore | None = None) -> None:
        self.settings = settings
        self.repo = repo
        self.store = store or build_object_store(settings)
        self.taxonomy = Taxonomy.load(settings.taxonomy_path)
        self._threads: dict[str, threading.Thread] = {}

    def upload(self, filename: str, data: bytes, tenant_id: str | None = None) -> dict[str, Any]:
        upload_id = "UP-" + uuid.uuid4().hex[:12]
        parsed = parse_backlog_csv(data, upload_id, self.settings)
        safe_name = Path(filename or "backlog.csv").name
        key = f"{self.settings.gcs_backlog_prefix}/{tenant_id or self.settings.tenant_id}/{upload_id}/{safe_name}"
        stored = self.store.put_bytes(key, data, "text/csv")
        status = "validated" if not parsed["errors"] else "validated_with_errors"
        self.repo.create_backlog_upload(
            upload_id=upload_id,
            tenant_id=tenant_id or self.settings.tenant_id,
            filename=safe_name,
            source_uri=stored.uri,
            generation=stored.generation,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            status=status,
            total_rows=parsed["total_rows"],
            valid_rows=parsed["valid_rows"],
            invalid_rows=parsed["invalid_rows"],
            errors=parsed["errors"],
            warnings=parsed["warnings"],
            items=parsed["items"],
        )
        self.repo.audit(tenant_id or "system", "backlog_upload", "backlog_upload", upload_id, {"filename": safe_name})
        return self.repo.get_backlog_upload(upload_id) or {}

    def start_validation(self, upload_id: str, force_rerun: bool = False) -> str:
        upload = self.repo.get_backlog_upload(upload_id)
        if not upload:
            raise ValueError("backlog upload not found")
        if upload["valid_rows"] == 0:
            raise ValueError("upload has no valid backlog rows")
        run_id = "VRUN-" + uuid.uuid4().hex[:12]
        self.repo.create_validation_run(run_id, upload_id)
        thread = threading.Thread(target=self.execute, args=(run_id, upload_id), daemon=True, name=f"validation-{run_id}")
        self._threads[run_id] = thread
        thread.start()
        return run_id

    def execute(self, run_id: str, upload_id: str) -> None:
        stages = [
            {"stage": "module_f_normalise", "status": "running"},
            {"stage": "module_g_validate", "status": "pending"},
        ]
        self.repo.update_validation_run(run_id, "running", stage_json=stages)
        try:
            upload = self.repo.get_backlog_upload(upload_id)
            if not upload:
                raise ValueError("backlog upload not found")
            items = self.repo.backlog_items(upload_id)
            profiles = [self._profile(row) for row in items]
            stages[0]["status"] = "succeeded"
            stages[0]["processed"] = len(profiles)
            stages[1]["status"] = "running"
            self.repo.update_validation_run(run_id, "running", stage_json=stages)

            report_id = "RPT-" + uuid.uuid4().hex[:12]
            report, findings, summary = self._validate(upload, profiles)
            report["report_id"] = report_id
            report["validation_run_id"] = run_id
            self.repo.save_report(report_id, upload_id, run_id, summary, report, findings)
            self.repo.save_coverage_matrix(report_id, report)
            stages[1]["status"] = "succeeded"
            stages[1]["processed"] = len(profiles)
            self.repo.update_validation_run(run_id, "completed", stage_json=stages, report_id=report_id)
            self.repo.db.execute(
                "UPDATE backlog_uploads SET status='validated', updated_at=? WHERE upload_id=?",
                (now_iso(), upload_id),
            )
            logger.info("backlog validation completed", extra={"run_id": run_id, "report_id": report_id})
        except Exception:  # noqa: BLE001
            logger.exception("backlog validation failed", extra={"run_id": run_id})
            stages[-1]["status"] = "failed"
            self.repo.update_validation_run(run_id, "failed", stage_json=stages, error="validation stage failed")

    def _profile(self, row: dict[str, Any]) -> BacklogProfile:
        text = " ".join(
            filter(
                None,
                [
                    row.get("title"),
                    row.get("description"),
                    row.get("acceptance_criteria"),
                    row.get("product_area"),
                    row.get("intended_outcome"),
                    row.get("customer_intent"),
                    row.get("target_feature"),
                    row.get("target_journey"),
                    row.get("functional_scope"),
                ],
            )
        )
        intents = [item.key for item, _ in lexicon.match_entities(text, lexicon.INTENTS)]
        aspects = [item.key for item, _ in lexicon.match_entities(text, lexicon.ASPECTS)]
        node = None
        if row.get("product_area"):
            node = self.taxonomy.map_product_area(row.get("product_area"))
        if not node:
            for aspect_key in aspects:
                aspect = next((item for item in lexicon.ASPECTS if item.key == aspect_key), None)
                if aspect and aspect.node_id in self.taxonomy.by_id:
                    node = self.taxonomy.by_id[aspect.node_id]
                    break
        if not node:
            node, _ = self.taxonomy.best_node(text, threshold=2.0)
        symptom_matches = lexicon.match_entities(
            " ".join(filter(None, [row.get("description"), row.get("acceptance_criteria")])), lexicon.SYMPTOMS
        )
        return BacklogProfile(
            backlog_id=row["backlog_id"],
            title=row["title"],
            description=row["description"],
            acceptance_criteria=row.get("acceptance_criteria") or "",
            acceptance_criteria_items=split_criteria(row.get("acceptance_criteria") or ""),
            product_area=row.get("product_area"),
            priority=row.get("priority"),
            business_goal=row.get("business_goal"),
            intended_outcome=row.get("intended_outcome"),
            customer_intent=row.get("customer_intent"),
            target_feature=row.get("target_feature"),
            target_journey=row.get("target_journey"),
            functional_scope=row.get("functional_scope"),
            organisational_objective=row.get("organisational_objective"),
            source_system=row.get("source_system"),
            intents=intents,
            aspects=aspects,
            journey_node_id=node.node_id if node else None,
            covered_symptoms=[item.key for item, _ in symptom_matches],
            tokens=tokenize(text),
            extraction_provider="rules",
            model_version="rules-v1",
        )

    def _validate(self, upload: dict[str, Any], profiles: list[BacklogProfile]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        latest_run = self.repo.latest_completed_feedback_run()
        if not latest_run:
            raise ValueError("run a feedback pipeline before validating a backlog")
        run_id = latest_run["run_id"]
        problems = self.repo.db.query(
            "SELECT p.problem_id, p.title, p.problem_statement, p.customer_intent, p.aspect, p.symptom_category, "
            "p.journey_node_id, p.evidence_count, p.distinct_customers, p.negative_count, p.last_seen, "
            "(SELECT display_name FROM taxonomy_nodes t WHERE t.node_id=p.journey_node_id ORDER BY t.version DESC LIMIT 1) "
            "AS journey_name FROM customer_problems p WHERE p.run_id=? ORDER BY p.evidence_count DESC",
            (run_id,),
        )
        if not problems:
            raise ValueError("no canonical problems available; run the feedback pipeline first")

        problem_texts = [f"{p['title']} {p['problem_statement']}" for p in problems]
        backlog_texts = [
            " ".join(
                filter(
                    None,
                    [
                        p.title,
                        p.description,
                        p.acceptance_criteria,
                        p.product_area or "",
                        p.intended_outcome or "",
                        p.customer_intent or "",
                        p.target_feature or "",
                        p.target_journey or "",
                        p.functional_scope or "",
                    ],
                )
            )
            for p in profiles
        ]
        retriever = HybridRetriever(self.settings).fit(problem_texts)
        retrieval = retriever.score(backlog_texts)
        problem_vectors = retrieval.scores

        evidence_by_problem = self._evidence(run_id)
        findings: list[dict[str, Any]] = []
        backlog_summaries: list[dict[str, Any]] = []
        addressed_problem_ids: set[str] = set()

        for index, profile in enumerate(profiles):
            problem_scores = problem_vectors[index]
            candidates: list[tuple[float, int]] = sorted(
                [(float(score), problem_index) for problem_index, score in enumerate(problem_scores)],
                reverse=True,
            )
            item_findings: list[dict[str, Any]] = []
            for similarity, problem_index in candidates[:8]:
                problem = problems[problem_index]
                node_alignment, node_reason = self._node_alignment(profile, problem)
                intent_alignment = self._intent_alignment(profile, problem)
                coverage, covered, uncovered = self._symptom_coverage(profile, problem)
                lexical = jaccard(set(profile.tokens), token_set(problem_texts[problem_index]))
                score = round(
                    0.35 * max(similarity, lexical) + 0.25 * node_alignment + 0.2 * intent_alignment + 0.2 * coverage,
                    3,
                )
                relationship = self._relationship(
                    similarity, lexical, node_alignment, intent_alignment, coverage, problem, score
                )
                if relationship == "NO_CLEAR_RELATIONSHIP" and (similarity < 0.18 and node_alignment == 0):
                    continue
                evidence = evidence_by_problem.get(problem["problem_id"], [])[:3]
                supporting = int(problem["evidence_count"] or 0)
                ac_gaps = [
                    f"No acceptance criterion addresses the reported symptom '{label}'."
                    for label in uncovered
                ]
                uncertainty = None
                if relationship in ("ADDRESSES", "PARTIALLY_ADDRESSES") and supporting < 2:
                    uncertainty = "Only one supporting feedback item; treat as NEEDS_REVIEW until more evidence is available."
                    relationship = "NEEDS_REVIEW"
                if 0.25 <= coverage < 0.45 and relationship == "ADDRESSES":
                    relationship = "NEEDS_REVIEW"
                    uncertainty = uncertainty or "Acceptance criteria cover only part of the reported problem scope."
                finding = {
                    "finding_id": "F-" + hashlib.sha1(f"{profile.backlog_id}|{problem['problem_id']}".encode()).hexdigest()[:14],
                    "backlog_id": profile.backlog_id,
                    "problem_id": problem["problem_id"],
                    "problem_title": problem["title"],
                    "relationship": relationship,
                    "rationale": (
                        f"{node_reason} Intent alignment {intent_alignment:.2f}; symptom coverage {coverage:.2f}; "
                        f"semantic/lexical similarity {max(similarity, lexical):.2f}. "
                        f"Covered symptoms: {', '.join(covered) if covered else 'none'}. "
                        f"Evidence: {supporting} customer mention(s)."
                    ),
                    "alignment_score": score,
                    "supporting_feedback_count": supporting,
                    "evidence": evidence,
                    "journey_node_id": problem["journey_node_id"],
                    "journey_name": problem.get("journey_name"),
                    "ac_coverage": coverage,
                    "ac_gaps": ac_gaps,
                    "uncertainty": uncertainty,
                }
                item_findings.append(finding)
                if relationship in ("ADDRESSES", "PARTIALLY_ADDRESSES"):
                    addressed_problem_ids.add(problem["problem_id"])
            item_findings.sort(key=lambda item: (item["alignment_score"], item["supporting_feedback_count"]), reverse=True)
            findings.extend(item_findings)
            overall, best = self._overall(item_findings)
            ac_total = sum(1 for item in item_findings if item["ac_gaps"])
            coverage_values = [item["ac_coverage"] for item in item_findings]
            ac_coverage = round(sum(coverage_values) / len(coverage_values), 3) if coverage_values else 0.0
            backlog_summaries.append(
                {
                    "backlog_id": profile.backlog_id,
                    "title": profile.title,
                    "description": profile.description,
                    "product_area": profile.product_area,
                    "priority": profile.priority,
                    "business_goal": profile.business_goal or "NOT_PROVIDED",
                    "journey_node_id": profile.journey_node_id,
                    "journey_name": self.taxonomy.by_id[profile.journey_node_id].display_name
                    if profile.journey_node_id in self.taxonomy.by_id
                    else "UNMAPPED",
                    "overall_alignment": overall,
                    "best_finding": best,
                    "ac_coverage": ac_coverage,
                    "ac_gap_count": ac_total,
                    "findings": item_findings,
                    "customer_evidence_alignment_note": (
                        "Customer-evidence alignment only. Organisational priority, regulatory obligations, delivery "
                        "cost and strategic value are not inferred from customer text."
                    ),
                }
            )

        if not findings:
            findings.append(
                {
                    "finding_id": "F-NONE",
                    "backlog_id": profiles[0].backlog_id if profiles else "unknown",
                    "problem_id": None,
                    "problem_title": None,
                    "relationship": "NO_CLEAR_RELATIONSHIP",
                    "rationale": "No customer problem had enough lexical or semantic overlap with the backlog items.",
                    "alignment_score": 0.0,
                    "supporting_feedback_count": 0,
                    "evidence": [],
                    "journey_node_id": None,
                    "ac_coverage": 0.0,
                    "ac_gaps": [],
                    "uncertainty": "The backlog may be valid for business reasons not represented in customer feedback.",
                }
            )

        relation_counts = Counter(item["relationship"] for item in findings)
        alignment_counts = Counter(item["overall_alignment"] for item in backlog_summaries)
        uncovered = [
            problem
            for problem in problems
            if problem["problem_id"] not in addressed_problem_ids and (problem["evidence_count"] or 0) >= 5
        ][:12]
        summary = {
            "generated_at": now_iso(),
            "feedback_run_id": run_id,
            "upload_id": upload["upload_id"],
            "backlog_count": len(profiles),
            "canonical_problem_count": len(problems),
            "findings": len(findings),
            "relationships": dict(relation_counts),
            "alignment": dict(alignment_counts),
            "high_evidence_uncovered_problems": len(uncovered),
            "taxonomy_version": self.taxonomy.version,
            "embedding_model": retrieval.model_name,
            "retrieval": {
                "provider": self.settings.retrieval_provider,
                "dense_weight": retrieval.dense_weight,
                "sparse_weight": retrieval.sparse_weight,
                "reranked": retrieval.reranked,
            },
            "schema_version": self.settings.schema_version,
        }
        report = {
            "report_id": None,
            "upload_id": upload["upload_id"],
            "filename": upload.get("filename"),
            "generated_at": summary["generated_at"],
            "feedback_run_id": run_id,
            "summary": summary,
            "backlog_items": backlog_summaries,
            "findings": findings,
            "uncovered_high_evidence_problems": [
                {
                    "problem_id": problem["problem_id"],
                    "title": problem["title"],
                    "problem_statement": problem["problem_statement"],
                    "journey_node_id": problem["journey_node_id"],
                    "journey_name": problem.get("journey_name"),
                    "evidence_count": problem["evidence_count"],
                    "distinct_customers": problem["distinct_customers"],
                    "last_seen": problem["last_seen"],
                }
                for problem in uncovered
            ],
            "versions": {
                "taxonomy": self.taxonomy.version,
                "embedding_model": retrieval.model_name,
                "schema": self.settings.schema_version,
                "code": self.settings.code_version,
            },
            "limitations": [
                "Alignment is derived only from the supplied customer feedback and backlog text.",
                "Organisational priority is not calculated; source priority is preserved as metadata.",
                "A NEEDS_REVIEW relationship must be resolved by a product owner before it is treated as aligned.",
                "Similarity is used for candidate retrieval, never as the final relationship decision.",
            ],
        }
        return report, findings, summary

    def _evidence(self, run_id: str) -> dict[str, list[dict[str, Any]]]:
        rows = self.repo.db.query(
            "SELECT problem_id, feedback_id, evidence_span, submitted_at, source_type, platform, rating "
            "FROM problem_evidence WHERE run_id=? ORDER BY submitted_at DESC",
            (run_id,),
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["problem_id"]].append(row)
        return grouped

    def _node_alignment(self, profile: BacklogProfile, problem: dict[str, Any]) -> tuple[float, str]:
        problem_node = problem.get("journey_node_id")
        profile_node = profile.journey_node_id
        if not problem_node or not profile_node:
            return 0.0, "No journey node could be established for one side of the comparison."
        profile_nodes = {profile_node}
        for aspect_key in profile.aspects:
            aspect = next((item for item in lexicon.ASPECTS if item.key == aspect_key), None)
            if aspect and aspect.node_id in self.taxonomy.by_id:
                profile_nodes.add(aspect.node_id)
        if problem_node in profile_nodes:
            return 1.0, f"Both items map to '{self.taxonomy.path_label(problem_node)}'."
        problem_module = self.taxonomy.module_for(problem_node)
        for node_id in profile_nodes:
            module = self.taxonomy.module_for(node_id)
            if problem_module and module and problem_module.node_id == module.node_id:
                return 0.6, (
                    f"Both items sit in the '{problem_module.display_name}' module, "
                    f"but the backlog targets '{self.taxonomy.path_label(node_id)}' while the problem is "
                    f"'{self.taxonomy.path_label(problem_node)}'."
                )
        return 0.0, (
            f"Journey mismatch: backlog targets '{self.taxonomy.path_label(profile_node)}', "
            f"problem is '{self.taxonomy.path_label(problem_node)}'."
        )

    def _intent_alignment(self, profile: BacklogProfile, problem: dict[str, Any]) -> float:
        problem_intent = problem.get("customer_intent")
        if not problem_intent:
            return 0.0
        if problem_intent in profile.intents:
            return 1.0
        problem_aspect = next((item for item in lexicon.ASPECTS if item.key == problem.get("aspect")), None)
        if problem_aspect:
            for intent_key in profile.intents:
                intent = next((item for item in lexicon.INTENTS if item.key == intent_key), None)
                if intent and intent.node_hint == problem_aspect.node_id:
                    return 0.7
            for aspect_key in profile.aspects:
                if aspect_key == problem.get("aspect"):
                    return 0.8
        return 0.0

    def _problem_symptoms(self, problem: dict[str, Any]) -> list[tuple[str, str, str]]:
        text = " ".join(
            filter(None, [problem.get("title"), problem.get("problem_statement"), problem.get("symptom_category")])
        )
        matches = lexicon.match_entities(text, lexicon.SYMPTOMS)
        results: list[tuple[str, str, str]] = []
        for symptom, _ in matches[:3]:
            results.append((symptom.key, symptom.category, symptom.label))
        if not results and problem.get("symptom_category"):
            category = str(problem["symptom_category"])
            results.append((category, category, category.replace("_", " ")))
        return results

    def _symptom_coverage(self, profile: BacklogProfile, problem: dict[str, Any]) -> tuple[float, list[str], list[str]]:
        text = f"{profile.description} {profile.acceptance_criteria}".lower()
        symptoms = self._problem_symptoms(problem)
        if not symptoms:
            overlap = jaccard(set(profile.tokens), token_set(problem.get("title") or ""))
            return (round(overlap, 3), [], ["general scope"])
        covered: list[str] = []
        uncovered: list[str] = []
        for key, category, label in symptoms:
            terms = SYMPTOM_COVERAGE_TERMS.get(key) or SYMPTOM_COVERAGE_TERMS.get(category) or SYMPTOM_COVERAGE_TERMS["general"]
            if any(term in text for term in terms):
                covered.append(label)
            else:
                uncovered.append(label)
        return (round(len(covered) / len(symptoms), 3), covered, uncovered)

    def _relationship(
        self,
        similarity: float,
        lexical: float,
        node_alignment: float,
        intent_alignment: float,
        coverage: float,
        problem: dict[str, Any],
        score: float,
    ) -> str:
        signal = max(similarity, lexical)
        if node_alignment == 0 and signal < 0.22:
            return "CONTRADICTS_OR_OUT_OF_SCOPE" if signal < 0.12 else "NO_CLEAR_RELATIONSHIP"
        if node_alignment >= 0.6 and coverage >= 0.5 and intent_alignment >= 0.45 and signal >= 0.18:
            return "ADDRESSES" if score >= 0.5 else "NEEDS_REVIEW"
        if node_alignment >= 0.6 and (coverage > 0 or signal >= 0.22):
            return "PARTIALLY_ADDRESSES"
        if node_alignment >= 0.6:
            return "RELATED_BUT_NOT_SOLVING"
        if signal >= 0.3:
            return "RELATED_BUT_NOT_SOLVING"
        if signal >= 0.18:
            return "NEEDS_REVIEW"
        return "NO_CLEAR_RELATIONSHIP"

    def _overall(self, findings: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
        if not findings:
            return "unsupported", None
        priority = {
            "ADDRESSES": 5,
            "PARTIALLY_ADDRESSES": 4,
            "NEEDS_REVIEW": 3,
            "RELATED_BUT_NOT_SOLVING": 2,
            "NO_CLEAR_RELATIONSHIP": 1,
            "CONTRADICTS_OR_OUT_OF_SCOPE": 0,
        }
        best = max(findings, key=lambda item: (priority[item["relationship"]], item["alignment_score"]))
        relationships = {item["relationship"] for item in findings}
        if "ADDRESSES" in relationships:
            best_address = max(
                (item for item in findings if item["relationship"] == "ADDRESSES"),
                key=lambda item: item["alignment_score"],
            )
            if best_address["alignment_score"] >= 0.55 and best_address["supporting_feedback_count"] >= 2:
                return "strong", best_address
            return "needs_review", best
        if "PARTIALLY_ADDRESSES" in relationships:
            return "partial", best
        if "NEEDS_REVIEW" in relationships:
            return "needs_review", best
        if "RELATED_BUT_NOT_SOLVING" in relationships:
            return "weak", best
        return "unsupported", best

    def report_download_rows(self, report: dict[str, Any]) -> list[list[str]]:
        header = [
            "backlog_id",
            "title",
            "overall_alignment",
            "problem_id",
            "problem_title",
            "relationship",
            "alignment_score",
            "supporting_feedback_count",
            "journey",
            "ac_coverage",
            "ac_gaps",
            "rationale",
        ]
        rows: list[list[str]] = []
        for item in report.get("backlog_items", []):
            if not item.get("findings"):
                rows.append([item["backlog_id"], item["title"], item["overall_alignment"], "", "", "", "", "", "", "", "", ""])
                continue
            for finding in item["findings"]:
                rows.append(
                    [
                        item["backlog_id"],
                        item["title"],
                        item["overall_alignment"],
                        finding.get("problem_id") or "",
                        finding.get("problem_title") or "",
                        finding["relationship"],
                        str(finding["alignment_score"]),
                        str(finding["supporting_feedback_count"]),
                        finding.get("journey_name") or "",
                        str(finding.get("ac_coverage", "")),
                        " | ".join(finding.get("ac_gaps") or []),
                        finding.get("rationale") or "",
                    ]
                )
        return [header, *rows]

    def run_sync(self, run_id: str, upload_id: str) -> None:
        self.execute(run_id, upload_id)
