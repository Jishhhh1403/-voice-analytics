from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from .models import CoveragePair, LensAssociation, LensSignal, WhitespaceDataset

GRADUATION_LENSES = ("GRAPH_BRIDGE", "COMBINATORIAL_LATTICE")
GRADUATION_SIGNAL_SCORE_THRESHOLD = 0.6


class WhitespaceContext:
    def __init__(self, dataset: WhitespaceDataset) -> None:
        self.dataset = dataset
        self.feedback = {record.feedback_id: record for record in dataset.insights}
        self.problems_by_feedback: dict[str, list[str]] = defaultdict(list)
        self.coverage_by_problem: dict[str, list[CoveragePair]] = defaultdict(list)
        for problem in dataset.canonical_problems:
            for feedback_id in problem.supporting_feedback_ids:
                self.problems_by_feedback[feedback_id].append(problem.problem_id)
        for pair in dataset.coverage:
            self.coverage_by_problem[pair.problem_id].append(pair)

    def max_alignment(self, feedback_ids: Iterable[str]) -> float:
        problem_ids = {problem_id for feedback_id in feedback_ids for problem_id in self.problems_by_feedback.get(feedback_id, [])}
        scores = [
            pair.alignment_score
            for problem_id in problem_ids
            for pair in self.coverage_by_problem.get(problem_id, [])
        ]
        return max(scores, default=0.0)

    def is_aspect_covered(self, aspect: str | None, threshold: float = 0.25) -> bool:
        if not aspect:
            return False
        for problem in self.dataset.canonical_problems:
            if aspect not in problem.top_aspects:
                continue
            scores = [pair.alignment_score for pair in self.coverage_by_problem.get(problem.problem_id, [])]
            if scores and max(scores) >= threshold:
                return True
        return any(aspect in backlog.profiled_aspects for backlog in self.dataset.backlog_profiles)

    def is_symptom_covered(self, symptom: str | None, threshold: float = 0.25) -> bool:
        if not symptom:
            return False
        feedback_ids = [record.feedback_id for record in self.dataset.insights if record.symptom == symptom]
        return self.max_alignment(feedback_ids) >= threshold or any(
            symptom.replace("_", " ") in backlog.title.lower() for backlog in self.dataset.backlog_profiles
        )

    def is_pair_covered(
        self,
        journey_node_id: str | None,
        intent: str | None,
        aspect: str | None,
        threshold: float = 0.25,
    ) -> bool:
        feedback_ids = [
            record.feedback_id
            for record in self.dataset.insights
            if (not journey_node_id or record.journey_node_id == journey_node_id)
            and (not intent or record.intent == intent)
            and (not aspect or record.aspect == aspect)
        ]
        if self.max_alignment(feedback_ids) >= threshold:
            return True
        return any(
            (not journey_node_id or backlog.journey_node_id == journey_node_id)
            and (not intent or intent in backlog.profiled_intents)
            and (not aspect or aspect in backlog.profiled_aspects)
            for backlog in self.dataset.backlog_profiles
        )

    def canonical_coverage(self, feedback_ids: Sequence[str]) -> float:
        problem_ids = {problem_id for feedback_id in feedback_ids for problem_id in self.problems_by_feedback.get(feedback_id, [])}
        if not problem_ids:
            return 0.0
        best_by_problem: dict[str, float] = {}
        for problem_id in problem_ids:
            scores = [pair.alignment_score for pair in self.coverage_by_problem.get(problem_id, [])]
            best_by_problem[problem_id] = max(scores, default=0.0)
        return max(best_by_problem.values(), default=0.0)

    def lens_associations(
        self,
        signals: Sequence[LensSignal],
        lens_names: Sequence[str] = GRADUATION_LENSES,
        minimum_signal_score: float = GRADUATION_SIGNAL_SCORE_THRESHOLD,
    ) -> dict[str, LensAssociation]:
        best: dict[str, LensAssociation] = {}
        for signal in signals:
            if signal.lens_name not in lens_names or not signal.supporting_feedback_ids:
                continue
            if signal.normalized_score <= minimum_signal_score:
                continue
            signal_feedbacks = set(signal.supporting_feedback_ids)
            label_count = sum(
                1 for value in (signal.journey_node_id, signal.intent, signal.aspect) if value
            )
            for problem in self.dataset.canonical_problems:
                shared = signal_feedbacks & set(problem.supporting_feedback_ids)
                label_matches = sum(
                    1
                    for value, candidates in (
                        (signal.journey_node_id, (problem.journey_node_id,)),
                        (signal.intent, problem.top_intents),
                        (signal.aspect, problem.top_aspects),
                    )
                    if value and value in candidates
                )
                if not shared and not label_matches:
                    continue
                feedback_score = len(shared) / len(signal_feedbacks)
                label_score = label_matches / label_count if label_count else 0.0
                candidate = LensAssociation(
                    problem_id=problem.problem_id,
                    lens_name=signal.lens_name,
                    association_score=round(0.6 * feedback_score + 0.4 * label_score, 4),
                    signal_score=signal.normalized_score,
                    journey_node_id=signal.journey_node_id,
                    intent=signal.intent,
                    aspect=signal.aspect,
                    shared_feedback_count=len(shared),
                )
                current = best.get(problem.problem_id)
                if current is None or candidate.association_score > current.association_score:
                    best[problem.problem_id] = candidate
        return best
