from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ...db import loads
from ...repository import Repository
from ..whitespace.models import (
    BacklogProfileRecord,
    CanonicalProblemRecord,
    CoveragePair,
    InsightRecord,
    WhitespaceDataset,
)
from ..whitespace.utils import effort_score, normalize_label, parse_timestamp, top_values


def _flatten_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_strings(item))
        return result
    if isinstance(value, Iterable):
        result = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    return [str(value)]


def _primary_value(rows: Sequence[Mapping[str, Any]], field: str) -> Any:
    for row in rows:
        value = row.get(field)
        if value is not None and str(value).strip():
            return value
    return None


def _common_value(rows: Sequence[Mapping[str, Any]], field: str) -> str | None:
    values = [row.get(field) for row in rows]
    labels = top_values(values, limit=1)
    return labels[0] if labels else None


def _customer_hash(value: Any, fallback: str) -> str:
    import hashlib

    seed = str(value) if value not in (None, "") else fallback
    return "CUST-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _is_open_set(rows: Sequence[Mapping[str, Any]], intent: str | None, aspect: str | None) -> bool:
    if not intent or not aspect:
        return True
    for row in rows:
        for field in ("intents_json", "aspects_json"):
            for value in _flatten_strings(loads(row.get(field), [])):
                label = normalize_label(value) or ""
                if "open" in label or label in {"unknown", "other", "unmapped"}:
                    return True
    return False


class WhitespaceDataLoader:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def load(
        self,
        run_id: str | None = None,
        report_id: str | None = None,
        upload_id: str | None = None,
    ) -> WhitespaceDataset:
        resolved_run = self.repo.resolve_run_id(run_id)
        if not resolved_run:
            return WhitespaceDataset(run_id="", report_id=report_id, upload_id=upload_id, insights=(), canonical_problems=(), backlog_profiles=(), coverage=())
        report = self._resolve_report(resolved_run, report_id)
        resolved_report_id = report["report_id"] if report else report_id
        resolved_upload_id = upload_id or (report["upload_id"] if report else None)
        if not resolved_upload_id:
            latest_upload = self.repo.db.query_one("SELECT upload_id FROM backlog_uploads ORDER BY created_at DESC LIMIT 1")
            resolved_upload_id = latest_upload["upload_id"] if latest_upload else None
        feedback_rows = self.repo.db.query(
            "SELECT * FROM feedback_records WHERE run_id=? AND COALESCE(is_primary_record, 1)=1",
            (resolved_run,),
        )
        feedback_ids = [row["feedback_id"] for row in feedback_rows]
        insight_rows = self._insight_rows(resolved_run, feedback_ids)
        insights = self._insights(feedback_rows, insight_rows)
        problems = self._canonical_problems(resolved_run)
        backlog = self._backlog_profiles(resolved_upload_id, insights)
        coverage = self._coverage(resolved_report_id)
        return WhitespaceDataset(
            run_id=resolved_run,
            report_id=resolved_report_id,
            upload_id=resolved_upload_id,
            insights=tuple(insights),
            canonical_problems=tuple(problems),
            backlog_profiles=tuple(backlog),
            coverage=tuple(coverage),
        )

    def _resolve_report(self, run_id: str, report_id: str | None) -> dict[str, Any] | None:
        if report_id:
            return self.repo.db.query_one("SELECT * FROM validation_reports WHERE report_id=?", (report_id,))
        rows = self.repo.db.query("SELECT * FROM validation_reports ORDER BY created_at DESC LIMIT 100")
        for row in rows:
            payload = loads(row.get("report_json"), {})
            if payload.get("feedback_run_id") == run_id:
                return row
        return None

    def _insight_rows(self, run_id: str, feedback_ids: Sequence[str]) -> list[dict[str, Any]]:
        if not feedback_ids:
            return []
        placeholders = ",".join("?" for _ in feedback_ids)
        return self.repo.db.query(
            f"SELECT * FROM extracted_insights WHERE run_id=? AND feedback_id IN ({placeholders}) "
            "ORDER BY feedback_id, sentence_index",
            [run_id, *feedback_ids],
        )

    def _insights(
        self,
        feedback_rows: Sequence[Mapping[str, Any]],
        insight_rows: Sequence[Mapping[str, Any]],
    ) -> list[InsightRecord]:
        by_feedback: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in insight_rows:
            by_feedback[str(row["feedback_id"])].append(row)
        records: list[InsightRecord] = []
        for feedback in feedback_rows:
            feedback_id = str(feedback["feedback_id"])
            rows = by_feedback.get(feedback_id, [])
            intent = _common_value(rows, "customer_intent")
            aspect = _common_value(rows, "aspect")
            symptom = _common_value(rows, "reported_symptom") or _common_value(rows, "reported_problem")
            emotion = _common_value(rows, "emotion")
            journey = _primary_value(rows, "journey_node_id")
            efforts = [effort_score(row.get("customer_effort")) for row in rows] or [2.0]
            channel = feedback.get("source_channel") or feedback.get("source_type") or "unknown"
            records.append(
                InsightRecord(
                    feedback_id=feedback_id,
                    customer_id_hash=_customer_hash(
                        feedback.get("synthetic_customer_ref"), feedback.get("content_fingerprint") or feedback_id
                    ),
                    timestamp=parse_timestamp(feedback.get("submitted_at")),
                    channel=str(channel),
                    journey_node_id=normalize_label(journey),
                    intent=normalize_label(intent),
                    aspect=normalize_label(aspect),
                    symptom=normalize_label(symptom),
                    emotion=normalize_label(emotion),
                    effort_score=sum(efforts) / len(efforts),
                    is_open_set=_is_open_set(rows, intent, aspect),
                )
            )
        return records

    def _priority_scores(self, run_id: str) -> dict[str, float]:
        rows = self.repo.db.query(
            "SELECT problem_id, priority_score FROM problem_priority_snapshots "
            "WHERE run_id=? ORDER BY calculated_at DESC",
            (run_id,),
        )
        result: dict[str, float] = {}
        for row in rows:
            result.setdefault(str(row["problem_id"]), float(row.get("priority_score") or 0.0))
        return result

    def _mds_coordinates(self, run_id: str, problem_ids: Sequence[str]) -> dict[str, tuple[float, float]]:
        if not problem_ids:
            return {}
        wanted = set(problem_ids)
        mds = self.repo.latest_mds(run_id)
        candidates = [mds["mds_id"]] if mds else []
        if not candidates:
            candidates = [
                row["mds_id"]
                for row in self.repo.db.query("SELECT mds_id FROM problem_mds_runs ORDER BY created_at DESC LIMIT 10")
            ]
        for mds_id in candidates:
            points = {
                str(row["problem_id"]): (float(row["x"]), float(row["y"]))
                for row in self.repo.mds_points(mds_id)
                if row.get("problem_id") in wanted
            }
            if points:
                return points
        return {}

    def _problem_attributes(
        self,
        run_id: str,
        problem_ids: Sequence[str],
    ) -> tuple[dict[str, list[str]], dict[str, float], dict[str, list[str]]]:
        if not problem_ids:
            return {}, {}, {}
        placeholders = ",".join("?" for _ in problem_ids)
        params: list[Any] = [run_id, *problem_ids]
        support_rows = self.repo.db.query(
            f"SELECT problem_id, feedback_id FROM problem_evidence WHERE run_id=? AND problem_id IN ({placeholders}) "
            "ORDER BY problem_id, feedback_id",
            params,
        )
        support: dict[str, list[str]] = defaultdict(list)
        for row in support_rows:
            key = str(row["problem_id"])
            feedback_id = str(row["feedback_id"])
            if feedback_id not in support[key]:
                support[key].append(feedback_id)
        intent_rows = self.repo.db.query(
            f"SELECT pe.problem_id, i.customer_intent, i.aspect FROM problem_evidence pe "
            f"JOIN extracted_insights i ON i.run_id=pe.run_id AND i.feedback_id=pe.feedback_id "
            f"WHERE pe.run_id=? AND pe.problem_id IN ({placeholders})",
            params,
        )
        intents: dict[str, list[str]] = defaultdict(list)
        aspects: dict[str, list[str]] = defaultdict(list)
        for row in intent_rows:
            key = str(row["problem_id"])
            if normalize_label(row.get("customer_intent")):
                intents[key].append(str(row["customer_intent"]))
            if normalize_label(row.get("aspect")):
                aspects[key].append(str(row["aspect"]))
        return dict(intents), dict(aspects), {**support, **{key: support.get(key, []) for key in problem_ids}}

    def _canonical_problems(self, run_id: str) -> list[CanonicalProblemRecord]:
        rows = self.repo.db.query("SELECT * FROM customer_problems WHERE run_id=? ORDER BY problem_id", (run_id,))
        if not rows:
            return []
        problem_ids = [str(row["problem_id"]) for row in rows]
        coordinates = self._mds_coordinates(run_id, problem_ids)
        priorities = self._priority_scores(run_id)
        intents, aspects, support = self._problem_attributes(run_id, problem_ids)
        effort_map = self._problem_efforts(run_id, problem_ids)
        records: list[CanonicalProblemRecord] = []
        for row in rows:
            problem_id = str(row["problem_id"])
            top_intents = top_values(intents.get(problem_id, []), limit=3) or (
                (normalize_label(row.get("customer_intent")),) if normalize_label(row.get("customer_intent")) else ()
            )
            top_aspects = top_values(aspects.get(problem_id, []), limit=3) or (
                (normalize_label(row.get("aspect")),) if normalize_label(row.get("aspect")) else ()
            )
            x, y = coordinates.get(problem_id, (float("nan"), float("nan")))
            records.append(
                CanonicalProblemRecord(
                    problem_id=problem_id,
                    journey_node_id=normalize_label(row.get("journey_node_id")),
                    top_intents=tuple(value for value in top_intents if value),
                    top_aspects=tuple(value for value in top_aspects if value),
                    priority_score=float(priorities.get(problem_id, 0.0)),
                    mean_effort_score=effort_map.get(problem_id, 2.0),
                    mds_x=x,
                    mds_y=y,
                    supporting_feedback_ids=tuple(support.get(problem_id, [])),
                )
            )
        return records

    def _problem_efforts(self, run_id: str, problem_ids: Sequence[str]) -> dict[str, float]:
        if not problem_ids:
            return {}
        placeholders = ",".join("?" for _ in problem_ids)
        rows = self.repo.db.query(
            f"SELECT pe.problem_id, i.customer_effort FROM problem_evidence pe "
            f"JOIN extracted_insights i ON i.run_id=pe.run_id AND i.feedback_id=pe.feedback_id "
            f"WHERE pe.run_id=? AND pe.problem_id IN ({placeholders})",
            [run_id, *problem_ids],
        )
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            grouped[str(row["problem_id"])].append(effort_score(row.get("customer_effort")))
        return {key: sum(values) / len(values) for key, values in grouped.items() if values}

    def _backlog_profiles(
        self,
        upload_id: str | None,
        insights: Sequence[InsightRecord],
    ) -> list[BacklogProfileRecord]:
        if not upload_id:
            return []
        rows = self.repo.db.query("SELECT * FROM backlog_items WHERE upload_id=? ORDER BY row_number", (upload_id,))
        intents = sorted({record.intent for record in insights if record.intent})
        aspects = sorted({record.aspect for record in insights if record.aspect})
        journeys = sorted({record.journey_node_id for record in insights if record.journey_node_id})
        profiles: list[BacklogProfileRecord] = []
        for row in rows:
            structured = loads(row.get("profile_json"), {}) or {}
            structured_values = [str(value) for value in _flatten_strings(structured)]
            text_parts = [
                row.get("title"),
                row.get("description"),
                row.get("acceptance_criteria"),
                row.get("customer_intent"),
                row.get("target_feature"),
                row.get("target_journey"),
                row.get("functional_scope"),
                row.get("intended_outcome"),
                *structured_values,
            ]
            text = " ".join(str(value).lower() for value in text_parts if value)
            profiled_intents = top_values([row.get("customer_intent"), *structured_values], limit=3)
            if not profiled_intents:
                profiled_intents = tuple(value for value in intents if value.replace("_", " ") in text or value in text)[:3]
            profiled_aspects = top_values([row.get("target_feature"), *structured_values], limit=3)
            if not profiled_aspects:
                profiled_aspects = tuple(value for value in aspects if value.replace("_", " ") in text or value in text)[:3]
            journey = normalize_label(row.get("target_journey"))
            if not journey:
                journey = next((value for value in journeys if value.replace("_", " ") in text or value in text), None)
            profiles.append(
                BacklogProfileRecord(
                    backlog_id=str(row["backlog_id"]),
                    title=str(row.get("title") or ""),
                    journey_node_id=journey,
                    profiled_intents=tuple(profiled_intents),
                    profiled_aspects=tuple(profiled_aspects),
                )
            )
        return profiles

    def _coverage(self, report_id: str | None) -> list[CoveragePair]:
        if not report_id:
            return []
        rows = self.repo.db.query(
            "SELECT problem_id, backlog_id, alignment_score FROM validation_findings WHERE report_id=?",
            (report_id,),
        )
        return [
            CoveragePair(
                problem_id=str(row["problem_id"]),
                backlog_id=str(row["backlog_id"]),
                alignment_score=float(row.get("alignment_score") or 0.0),
            )
            for row in rows
            if row.get("problem_id") and row.get("backlog_id")
        ]
