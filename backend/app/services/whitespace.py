from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..config import Settings
from ..intelligence.whitespace.combinatorial_analyzer import analyze_combinatorial
from ..intelligence.whitespace.context import GRADUATION_LENSES, WhitespaceContext
from ..intelligence.whitespace.graph_analyzer import analyze_graph
from ..intelligence.whitespace.loader import WhitespaceDataLoader
from ..intelligence.whitespace.models import LensAssociation, WhitespaceDiscoveryResult
from ..intelligence.whitespace.spatial_analyzer import analyze_spatial
from ..intelligence.whitespace.triangulator import triangulate
from ..intelligence.whitespace.unified_merger import merge_whitespaces
from ..repository import Repository


class WhitespaceDiscoveryService:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self.loader = WhitespaceDataLoader(repo)

    def discover(
        self,
        run_id: str | None = None,
        report_id: str | None = None,
        upload_id: str | None = None,
    ) -> WhitespaceDiscoveryResult:
        dataset = self.loader.load(run_id=run_id, report_id=report_id, upload_id=upload_id)
        context = WhitespaceContext(dataset)
        graph_signals = analyze_graph(dataset, context)
        spatial_signals = analyze_spatial(dataset, context)
        combinatorial_signals = analyze_combinatorial(dataset, context)
        signals = [*graph_signals, *spatial_signals, *combinatorial_signals]
        verified = triangulate(signals, context)
        merged = merge_whitespaces(verified)
        return WhitespaceDiscoveryResult(
            run_id=dataset.run_id,
            report_id=dataset.report_id,
            upload_id=dataset.upload_id,
            lens_signals=tuple(signals),
            verified_whitespaces=tuple(verified),
            merged_whitespaces=merged.whitespaces,
            diagnostics={
                "feedback_record_count": len(dataset.insights),
                "canonical_problem_count": len(dataset.canonical_problems),
                "backlog_profile_count": len(dataset.backlog_profiles),
                "coverage_pair_count": len(dataset.coverage),
                "graph_signal_count": len(graph_signals),
                "spatial_signal_count": len(spatial_signals),
                "combinatorial_signal_count": len(combinatorial_signals),
                **merged.diagnostics,
            },
        )

    def lens_associations(
        self,
        run_id: str | None = None,
        upload_id: str | None = None,
    ) -> dict[str, LensAssociation]:
        dataset = self.loader.load(run_id=run_id, upload_id=upload_id)
        context = WhitespaceContext(dataset)
        signals = [
            signal
            for signal in (*analyze_graph(dataset, context), *analyze_combinatorial(dataset, context))
            if signal.lens_name in GRADUATION_LENSES
        ]
        return context.lens_associations(
            signals,
            minimum_signal_score=self.settings.lens_graduation_signal_threshold,
        )

    def discover_dict(
        self,
        run_id: str | None = None,
        report_id: str | None = None,
        upload_id: str | None = None,
    ) -> dict[str, Any]:
        return asdict(self.discover(run_id=run_id, report_id=report_id, upload_id=upload_id))
