from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np
from sklearn.decomposition import NMF
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import PoissonRegressor

from .context import WhitespaceContext
from .models import LensSignal, WhitespaceDataset
from .utils import mean, minmax_scores, normalize_label, top_values

_MIN_EFFORT = 3.8
_NMF_MIN_EFFORT = 4.0
_COVERAGE_THRESHOLD = 0.25
_POISSON_BOOST = 1.25


def _channel_for(dataset: WhitespaceDataset, feedback_ids: tuple[str, ...]) -> str | None:
    lookup = {record.feedback_id: record.channel for record in dataset.insights}
    return top_values([lookup.get(feedback_id) for feedback_id in feedback_ids], 1)[0] if feedback_ids else None


def _poisson_residuals(dataset: WhitespaceDataset) -> dict[tuple[str, str], float]:
    groups: Counter[tuple[str, str]] = Counter()
    for record in dataset.insights:
        key = (record.journey_node_id or "unknown", normalize_label(record.channel) or "unknown")
        groups[key] += 1
    if len(groups) < 3:
        return {}
    vectorizer = DictVectorizer(sparse=True)
    features = [{"journey": journey, "channel": channel} for journey, channel in groups]
    try:
        matrix = vectorizer.fit_transform(features)
    except ValueError:
        return {}
    if matrix.shape[1] < 2:
        return {}
    model = PoissonRegressor(alpha=1.0, max_iter=1000)
    model.fit(matrix, np.asarray([groups[key] for key in groups], dtype=float))
    predicted = np.maximum(model.predict(matrix), 1e-6)
    observed = np.asarray([groups[key] for key in groups], dtype=float)
    residuals = (observed - predicted) / np.sqrt(predicted + 1e-6)
    return {key: float(value) for key, value in zip(groups, residuals, strict=True)}


def _normalize(signals: list[LensSignal]) -> list[LensSignal]:
    if not signals:
        return []
    scores = minmax_scores([float(signal.metadata.get("raw_score", 0.0)) for signal in signals])
    return [
        LensSignal(
            lens_name=signal.lens_name,
            journey_node_id=signal.journey_node_id,
            intent=signal.intent,
            aspect=signal.aspect,
            normalized_score=score,
            supporting_feedback_ids=signal.supporting_feedback_ids,
            metadata=signal.metadata,
        )
        for signal, score in zip(signals, scores, strict=True)
    ]


def detect_lattice_holes(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    grouped: dict[tuple[str, str], list[object]] = defaultdict(list)
    for record in dataset.insights:
        if record.journey_node_id and record.intent:
            grouped[(record.journey_node_id, record.intent)].append(record)
    signals: list[LensSignal] = []
    for (journey, intent), records in sorted(grouped.items()):
        count = len(records)
        effort = mean([float(record.effort_score) for record in records])
        if count < 10 or effort < _MIN_EFFORT:
            continue
        feedback_ids = tuple(sorted(record.feedback_id for record in records))
        if context.is_pair_covered(journey, intent, None, _COVERAGE_THRESHOLD):
            continue
        aspects = top_values([record.aspect for record in records], 2)
        raw_score = effort * math.log1p(count)
        signals.append(
            LensSignal(
                lens_name="COMBINATORIAL_LATTICE",
                journey_node_id=journey,
                intent=intent,
                aspect=aspects[0] if aspects else None,
                normalized_score=0.0,
                supporting_feedback_ids=feedback_ids,
                metadata={
                    "raw_score": raw_score,
                    "count": count,
                    "mean_effort_score": effort,
                    "channel": top_values([record.channel for record in records], 1)[0] if records else None,
                    "pair_type": "journey_intent",
                },
            )
        )
    micro_groups: dict[tuple[str, str], list[object]] = defaultdict(list)
    for record in dataset.insights:
        if record.is_open_set and record.intent and record.symptom:
            micro_groups[(record.intent, record.symptom)].append(record)
    for (intent, symptom), records in sorted(micro_groups.items()):
        count = len(records)
        effort = mean([float(record.effort_score) for record in records])
        if count < 5 or effort < _MIN_EFFORT:
            continue
        feedback_ids = tuple(sorted(record.feedback_id for record in records))
        if context.max_alignment(feedback_ids) >= _COVERAGE_THRESHOLD:
            continue
        journeys = top_values([record.journey_node_id for record in records], 1)
        aspects = top_values([record.aspect for record in records], 2)
        raw_score = effort * math.log1p(count)
        signals.append(
            LensSignal(
                lens_name="COMBINATORIAL_LATTICE",
                journey_node_id=journeys[0] if journeys else None,
                intent=intent,
                aspect=aspects[0] if aspects else None,
                normalized_score=0.0,
                supporting_feedback_ids=feedback_ids,
                metadata={
                    "raw_score": raw_score,
                    "count": count,
                    "mean_effort_score": effort,
                    "channel": top_values([record.channel for record in records], 1)[0] if records else None,
                    "pair_type": "open_set_micro_group",
                    "symptom": symptom,
                },
            )
        )
    return signals


def detect_combinatorial_nmf(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    if len(dataset.insights) < 3:
        return []
    features: list[dict[str, float]] = []
    for record in dataset.insights:
        row: dict[str, float] = {}
        if record.intent:
            row[f"intent:{record.intent}"] = 1.0
        if record.symptom:
            row[f"symp:{record.symptom}"] = 1.0
        if record.emotion:
            row[f"emo:{record.emotion}"] = 1.0
        channel = normalize_label(record.channel)
        if channel:
            row[f"chan:{channel}"] = 1.0
        features.append(row)
    vectorizer = DictVectorizer(sparse=True)
    try:
        matrix = vectorizer.fit_transform(features)
    except ValueError:
        return []
    n_components = min(12, matrix.shape[0] - 1, matrix.shape[1] - 1)
    if n_components < 2:
        return []
    model = NMF(n_components=n_components, init="nndsvda", max_iter=500, random_state=42)
    weights = model.fit_transform(matrix)
    signals: list[LensSignal] = []
    for component in range(n_components):
        ranked = sorted(range(len(dataset.insights)), key=lambda index: (-float(weights[index, component]), index))[:50]
        feedback_ids = tuple(sorted(dataset.insights[index].feedback_id for index in ranked))
        effort = mean([float(dataset.insights[index].effort_score) for index in ranked])
        if effort < _NMF_MIN_EFFORT:
            continue
        problem_ids = {
            problem_id
            for feedback_id in feedback_ids
            for problem_id in context.problems_by_feedback.get(feedback_id, [])
        }
        if problem_ids:
            covered = sum(
                1
                for problem_id in problem_ids
                if max(
                    (pair.alignment_score for pair in context.coverage_by_problem.get(problem_id, [])),
                    default=0.0,
                )
                >= _COVERAGE_THRESHOLD
            )
            if covered / len(problem_ids) >= 0.20:
                continue
        intents = top_values([dataset.insights[index].intent for index in ranked], 1)
        aspects = top_values([dataset.insights[index].aspect for index in ranked], 1)
        journeys = top_values([dataset.insights[index].journey_node_id for index in ranked], 1)
        raw_score = float(np.mean(weights[:, component])) * effort * 10.0
        signals.append(
            LensSignal(
                lens_name="COMBINATORIAL_NMF",
                journey_node_id=journeys[0] if journeys else None,
                intent=intents[0] if intents else None,
                aspect=aspects[0] if aspects else None,
                normalized_score=0.0,
                supporting_feedback_ids=feedback_ids,
                metadata={
                    "raw_score": raw_score,
                    "component": component,
                    "mean_effort_score": effort,
                    "covered_problem_ratio": (covered / len(problem_ids)) if problem_ids else 0.0,
                    "channel": _channel_for(dataset, feedback_ids),
                },
            )
        )
    return signals


def analyze_combinatorial(dataset: WhitespaceDataset, context: WhitespaceContext) -> list[LensSignal]:
    signals = detect_lattice_holes(dataset, context) + detect_combinatorial_nmf(dataset, context)
    residuals = _poisson_residuals(dataset)
    boosted: list[LensSignal] = []
    for signal in signals:
        channel = str(signal.metadata.get("channel") or _channel_for(dataset, signal.supporting_feedback_ids) or "unknown")
        journey = signal.journey_node_id or "unknown"
        z_score = residuals.get((journey, channel), 0.0)
        metadata = {**signal.metadata, "poisson_z_score": z_score, "poisson_boost": False}
        raw_score = float(signal.metadata.get("raw_score", 0.0))
        if z_score > 2.0:
            raw_score *= _POISSON_BOOST
            metadata["poisson_boost"] = True
        metadata["raw_score"] = raw_score
        boosted.append(
            LensSignal(
                lens_name=signal.lens_name,
                journey_node_id=signal.journey_node_id,
                intent=signal.intent,
                aspect=signal.aspect,
                normalized_score=signal.normalized_score,
                supporting_feedback_ids=signal.supporting_feedback_ids,
                metadata=metadata,
            )
        )
    return _normalize(boosted)
