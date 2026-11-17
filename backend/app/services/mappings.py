"""Read-only evidence graph spanning feedback, themes, factors and backlogs."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from ..db import loads
from ..repository import Repository


class MappingGraphService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def build(
        self,
        feedback_run_id: str | None = None,
        report_id: str | None = None,
    ) -> dict[str, Any]:
        run = (
            self.repo.get_run(feedback_run_id)
            if feedback_run_id
            else self.repo.latest_completed_feedback_run()
        )
        if not run:
            return {
                "status": "NO_FEEDBACK_RUN",
                "generated_at": datetime.now(UTC).isoformat(),
                "feedback_run_id": feedback_run_id,
                "feedback": [],
                "themes": [],
                "factors": [],
                "backlogs": [],
                "links": {"feedback_theme": [], "theme_factor": [], "factor_backlog": []},
                "counts": {},
                "warnings": ["No completed feedback run is available."],
                "versions": {},
            }

        run_id = run["run_id"]
        feedback_rows = self.repo.db.query(
            "SELECT feedback_id, submitted_at, source_type, source_channel, platform, rating, "
            "COALESCE(feedback_title, '') AS title, "
            "substr(COALESCE(feedback_text_redacted, ''), 1, 240) AS text "
            "FROM feedback_records WHERE run_id=? ORDER BY submitted_at, feedback_id",
            (run_id,),
        )
        theme_rows = self.repo.db.query(
            "SELECT p.problem_id, p.title, p.problem_statement, p.evidence_count, "
            "p.distinct_customers, p.negative_count, p.journey_node_id, p.lifecycle_status, "
            "p.validation_status, p.discovery_confidence, t.display_name AS journey_name "
            "FROM customer_problems p "
            "LEFT JOIN taxonomy_nodes t ON t.node_id=p.journey_node_id AND t.version=p.taxonomy_version "
            "WHERE p.run_id=? ORDER BY p.evidence_count DESC, p.title",
            (run_id,),
        )
        if not theme_rows:
            return {
                "status": "NO_THEMES",
                "generated_at": datetime.now(UTC).isoformat(),
                "feedback_run_id": run_id,
                "feedback": feedback_rows,
                "themes": [],
                "factors": [],
                "backlogs": [],
                "links": {"feedback_theme": [], "theme_factor": [], "factor_backlog": []},
                "counts": {"feedback_total": len(feedback_rows), "themes": 0},
                "warnings": ["The feedback run has no canonical themes."],
                "versions": {"feedback_run_id": run_id},
            }

        feedback_by_id = {row["feedback_id"]: row for row in feedback_rows}
        theme_by_id = {row["problem_id"]: row for row in theme_rows}

        signal_rows = self.repo.db.query(
            "SELECT i.is_problem AS is_problem, pe.problem_id AS problem_id, COUNT(*) AS total "
            "FROM problem_evidence pe JOIN extracted_insights i ON i.insight_id = pe.insight_id "
            "WHERE pe.run_id=? GROUP BY i.is_problem, pe.problem_id",
            (run_id,),
        )
        signal_group_counts: Counter[str] = Counter()
        signal_by_theme: Counter[str] = Counter()
        signal_links: list[dict[str, Any]] = []
        for row in signal_rows:
            group = "problem" if row["is_problem"] else "context"
            total = int(row["total"] or 0)
            signal_group_counts[group] += total
            signal_by_theme[row["problem_id"]] += total
            signal_links.append({"source": group, "target": row["problem_id"], "count": total})
        signal_total = (
            self.repo.db.scalar("SELECT COUNT(*) FROM extracted_insights WHERE run_id=?", (run_id,)) or 0
        )

        evidence_rows = self.repo.db.query(
            "SELECT e.feedback_id, e.problem_id, MAX(e.weight) AS weight, COUNT(*) AS evidence_count, "
            "MIN(e.submitted_at) AS submitted_at, MAX(e.source_type) AS source_type, "
            "MAX(e.source_channel) AS source_channel, MAX(e.platform) AS platform, MAX(e.rating) AS rating "
            "FROM problem_evidence e WHERE e.run_id=? GROUP BY e.feedback_id, e.problem_id "
            "ORDER BY e.problem_id, e.feedback_id",
            (run_id,),
        )
        feedback_theme_links = []
        primary_theme_by_feedback: dict[str, str] = {}
        primary_weight: dict[str, float] = {}
        theme_link_counts: Counter[str] = Counter()
        feedback_link_counts: Counter[str] = Counter()
        for row in evidence_rows:
            if row["problem_id"] not in theme_by_id:
                continue
            feedback = feedback_by_id.get(row["feedback_id"])
            if not feedback:
                feedback = {
                    "feedback_id": row["feedback_id"],
                    "submitted_at": row["submitted_at"],
                    "source_type": row["source_type"],
                    "source_channel": row["source_channel"],
                    "platform": row["platform"],
                    "rating": row["rating"],
                    "title": f"Feedback {row['feedback_id']}",
                    "text": "Evidence is available without a persisted feedback record.",
                }
                feedback_by_id[row["feedback_id"]] = feedback
                feedback_rows.append(feedback)
            weight = float(row["weight"] or 0)
            feedback_theme_links.append(
                {
                    "source": row["feedback_id"],
                    "target": row["problem_id"],
                    "weight": round(weight, 6),
                    "evidence_count": int(row["evidence_count"] or 0),
                }
            )
            theme_link_counts[row["problem_id"]] += 1
            feedback_link_counts[row["feedback_id"]] += 1
            if weight > primary_weight.get(row["feedback_id"], float("-inf")):
                primary_weight[row["feedback_id"]] = weight
                primary_theme_by_feedback[row["feedback_id"]] = row["problem_id"]

        factor_run = self.repo.latest_factor_prioritisation_run()
        factors: list[dict[str, Any]] = []
        theme_factor_links: list[dict[str, Any]] = []
        primary_factor_by_theme: dict[str, str] = {}
        primary_factor_score: dict[str, float] = {}
        factor_rank_by_id: dict[str, int] = {}
        if factor_run:
            scores = self.repo.db.query(
                "SELECT factor_id, dimension_id, factor_name, final_priority_score, rank, "
                "score_status, eligibility_status, evidence_coverage "
                "FROM factor_prioritisation_scores WHERE prioritisation_run_id=? "
                "ORDER BY rank, factor_id",
                (factor_run["prioritisation_run_id"],),
            )
            factors = [
                {
                    "factor_id": row["factor_id"],
                    "dimension_id": row["dimension_id"],
                    "factor_name": row["factor_name"],
                    "rank": int(row["rank"]),
                    "priority_score": round(float(row["final_priority_score"] or 0), 4),
                    "score_status": row["score_status"],
                    "eligibility_status": row["eligibility_status"],
                    "evidence_coverage": round(float(row["evidence_coverage"] or 0), 4),
                }
                for row in scores
            ]
            factor_rank_by_id = {item["factor_id"]: item["rank"] for item in factors}
            factor_by_dimension = {item["dimension_id"]: item["factor_id"] for item in factors}

            membership_rows = self.repo.db.query(
                "SELECT canonical_problem_id, dimension_id, membership_type, score, margin, is_ambiguous "
                "FROM dimension_problem_membership WHERE run_id=? "
                "ORDER BY canonical_problem_id, score DESC",
                (factor_run["famd_run_id"],),
            )
            for row in membership_rows:
                if row["canonical_problem_id"] not in theme_by_id:
                    continue
                factor_id = factor_by_dimension.get(row["dimension_id"])
                if not factor_id:
                    continue
                score = float(row["score"] or 0)
                theme_factor_links.append(
                    {
                        "source": row["canonical_problem_id"],
                        "target": factor_id,
                        "score": round(score, 6),
                        "margin": round(float(row["margin"] or 0), 6),
                        "membership_type": row["membership_type"],
                        "is_ambiguous": bool(row["is_ambiguous"]),
                    }
                )
                if score > primary_factor_score.get(row["canonical_problem_id"], float("-inf")):
                    primary_factor_score[row["canonical_problem_id"]] = score
                    primary_factor_by_theme[row["canonical_problem_id"]] = factor_id

        backlogs: list[dict[str, Any]] = []
        factor_backlog_links: list[dict[str, Any]] = []
        report_row = self._resolve_report(report_id, factor_run)
        coverage_report_row = self._resolve_coverage_report(report_id, run_id)
        warnings: list[str] = []
        if not factor_run:
            warnings.append("No completed factor prioritisation run is available.")
        if not report_row:
            warnings.append("No factor-based backlog validation report matches the latest factor run.")
        if not coverage_report_row:
            warnings.append("No backlog validation report matches this feedback run.")
        if report_row:
            report = report_row["report"]
            for item in report.get("backlog_items", []):
                best_finding = item.get("best_finding") or {}
                backlogs.append(
                    {
                        "backlog_id": item["backlog_id"],
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                        "product_area": item.get("product_area"),
                        "priority": item.get("priority"),
                        "business_goal": item.get("business_goal"),
                        "backlog_priority_rank": int(item.get("backlog_priority_rank") or 0),
                        "overall_alignment": item.get("overall_alignment"),
                        "priority_alignment_pct": item.get("priority_alignment_pct"),
                        "factor_coverage_pct": item.get("factor_coverage_pct"),
                        "covered_factor_count": int(item.get("covered_factor_count") or 0),
                        "covered_factor_ids": item.get("covered_factor_ids") or [],
                        "covered_problem_count": int(item.get("covered_problem_count") or 0),
                        "highest_priority_factor_rank": item.get("highest_priority_factor_rank"),
                        "best_factor_id": best_finding.get("factor_id"),
                        "best_relationship": best_finding.get("relationship"),
                    }
                )
            for finding in report.get("findings", []):
                factor_backlog_links.append(
                    {
                        "source": finding["factor_id"],
                        "target": finding["backlog_id"],
                        "relationship": finding.get("relationship"),
                        "coverage": finding.get("coverage"),
                        "coverage_pct": finding.get("coverage_pct"),
                        "alignment_score": finding.get("alignment_score"),
                        "embedding_distance": finding.get("embedding_distance"),
                        "priority_weighted_coverage": finding.get("priority_weighted_coverage"),
                        "supporting_feedback_count": finding.get("supporting_feedback_count"),
                        "covered_problem_count": finding.get("covered_problem_count"),
                        "problem_id": finding.get("problem_id"),
                        "problem_title": finding.get("problem_title"),
                        "rationale": finding.get("rationale"),
                    }
                )

        coverage_counts: Counter[str] = Counter()
        problem_backlog_links: list[dict[str, Any]] = []
        canonical_coverage: dict[str, dict[str, Any]] = {}
        flow_backlogs: list[dict[str, Any]] = []
        if coverage_report_row:
            for index, item in enumerate(coverage_report_row["report"].get("backlog_items", [])):
                flow_backlogs.append(
                    {
                        "backlog_id": item["backlog_id"],
                        "title": item.get("title", ""),
                        "product_area": item.get("product_area"),
                        "priority": item.get("priority"),
                        "backlog_priority_rank": int(item.get("backlog_priority_rank") or index + 1),
                    }
                )
            for item in coverage_report_row["report"].get("canonical_coverage", []):
                problem_id = item.get("problem_id")
                if not problem_id:
                    continue
                status = item.get("coverage_status") or "unknown"
                canonical_coverage[problem_id] = item
                coverage_counts[status] += 1
                problem_backlog_links.append(
                    {
                        "source": problem_id,
                        "target": (
                            item.get("closest_backlog_id")
                            if status in {"covered", "grey_zone"}
                            else None
                        ),
                        "status": status,
                        "score": item.get("coverage_score"),
                        "problem_title": item.get("problem_title"),
                    }
                )
            if not canonical_coverage:
                for row in self.repo.db.query(
                    "SELECT backlog_id, problem_id, coverage_type, alignment_score "
                    "FROM backlog_coverage_matrix WHERE report_id=? AND problem_id IS NOT NULL",
                    (coverage_report_row["report_id"],),
                ):
                    status = {
                        "full": "covered",
                        "partial": "grey_zone",
                        "uncovered": "not_covered",
                    }.get(row["coverage_type"], row["coverage_type"])
                    coverage_counts[status] += 1
                    problem_backlog_links.append(
                        {
                            "source": row["problem_id"],
                            "target": row["backlog_id"] if status in {"covered", "grey_zone"} else None,
                            "status": status,
                            "score": row["alignment_score"],
                            "problem_title": theme_by_id.get(row["problem_id"], {}).get("title"),
                        }
                    )

        themes = list(theme_by_id.values())
        for theme in themes:
            theme["signal_count"] = signal_by_theme.get(theme["problem_id"], 0)
            coverage = canonical_coverage.get(theme["problem_id"])
            theme["coverage_status"] = coverage.get("coverage_status") if coverage else None
            theme["closest_backlog_id"] = coverage.get("closest_backlog_id") if coverage else None
            theme["primary_factor_id"] = primary_factor_by_theme.get(theme["problem_id"])
            theme["primary_factor_rank"] = factor_rank_by_id.get(
                theme["primary_factor_id"] or "", 10_000
            )
            theme["mapped_feedback_count"] = theme_link_counts.get(theme["problem_id"], 0)
            theme["primary_factor_score"] = round(
                primary_factor_score.get(theme["problem_id"], 0), 6
            )
        themes.sort(
            key=lambda item: (
                item["primary_factor_rank"],
                -int(item.get("evidence_count") or 0),
                item.get("title") or "",
            )
        )
        theme_order = {theme["problem_id"]: index for index, theme in enumerate(themes)}

        for feedback in feedback_rows:
            primary_theme_id = primary_theme_by_feedback.get(feedback["feedback_id"])
            feedback["primary_theme_id"] = primary_theme_id
            feedback["primary_theme_order"] = theme_order.get(primary_theme_id, 10_000)
            feedback["theme_count"] = feedback_link_counts.get(feedback["feedback_id"], 0)

        feedback_rows.sort(
            key=lambda item: (
                item["primary_theme_order"],
                -(primary_weight.get(item["feedback_id"]) or 0),
                item.get("submitted_at") or "",
                item["feedback_id"],
            )
        )
        feedback_order = {item["feedback_id"]: index for index, item in enumerate(feedback_rows)}
        feedback_theme_links.sort(
            key=lambda link: (
                feedback_order.get(link["source"], 10_000),
                theme_order.get(link["target"], 10_000),
            )
        )
        theme_factor_links.sort(
            key=lambda link: (
                theme_order.get(link["source"], 10_000),
                factor_rank_by_id.get(link["target"], 10_000),
                -float(link["score"]),
            )
        )
        backlogs.sort(
            key=lambda item: (
                item.get("backlog_priority_rank") or 10_000,
                item["backlog_id"],
            )
        )
        backlog_order = {item["backlog_id"]: index for index, item in enumerate(backlogs)}
        factor_backlog_links.sort(
            key=lambda link: (
                factor_rank_by_id.get(link["source"], 10_000),
                backlog_order.get(link["target"], 10_000),
            )
        )

        mapped_feedback = sum(1 for item in feedback_rows if item["primary_theme_id"])
        return {
            "status": "READY" if factor_run and report_row else "PARTIAL",
            "generated_at": datetime.now(UTC).isoformat(),
            "feedback_run_id": run_id,
            "feedback_run_finished_at": run.get("finished_at"),
            "famd_run_id": factor_run["famd_run_id"] if factor_run else None,
            "prioritisation_run_id": factor_run["prioritisation_run_id"] if factor_run else None,
            "report_id": report_row["report_id"] if report_row else None,
            "coverage_report_id": coverage_report_row["report_id"] if coverage_report_row else None,
            "validation_run_id": (report_row["report"].get("validation_run_id") if report_row else None),
            "upload_id": report_row["upload_id"] if report_row else None,
            "feedback": feedback_rows,
            "signals": [
                {"id": group, "count": signal_group_counts.get(group, 0)}
                for group in ("problem", "context")
            ],
            "signal_links": signal_links,
            "themes": themes,
            "factors": factors,
            "backlogs": backlogs,
            "coverage_backlogs": flow_backlogs,
            "links": {
                "feedback_theme": feedback_theme_links,
                "theme_factor": theme_factor_links,
                "factor_backlog": factor_backlog_links,
                "problem_backlog": problem_backlog_links,
            },
            "coverage": {
                "covered": coverage_counts.get("covered", 0),
                "grey_zone": coverage_counts.get("grey_zone", 0),
                "not_covered": coverage_counts.get("not_covered", 0),
                "unassessed": max(0, len(themes) - sum(coverage_counts.values())),
            },
            "counts": {
                "feedback_total": len(feedback_rows),
                "feedback_mapped": mapped_feedback,
                "feedback_unmapped": len(feedback_rows) - mapped_feedback,
                "signals_total": int(signal_total),
                "signals_linked": sum(signal_group_counts.values()),
                "themes": len(themes),
                "themes_with_factors": len(primary_factor_by_theme),
                "factors": len(factors),
                "backlogs": len(backlogs),
                "feedback_theme_links": len(feedback_theme_links),
                "theme_factor_links": len(theme_factor_links),
                "factor_backlog_links": len(factor_backlog_links),
            },
            "warnings": warnings,
            "versions": {
                "feedback_run_id": run_id,
                "famd_run_id": factor_run["famd_run_id"] if factor_run else None,
                "prioritisation_run_id": factor_run["prioritisation_run_id"] if factor_run else None,
                "report_id": report_row["report_id"] if report_row else None,
                "taxonomy_version": run.get("taxonomy_version"),
                "schema_version": run.get("schema_version"),
                "code_version": run.get("code_version"),
            },
        }

    def _resolve_report(
        self, report_id: str | None, factor_run: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if report_id:
            return self.repo.get_report(report_id)
        if not factor_run:
            return None
        rows = self.repo.db.query(
            "SELECT report_id, report_json, upload_id FROM validation_reports "
            "ORDER BY created_at DESC, rowid DESC LIMIT 40"
        )
        for row in rows:
            report = loads(row.pop("report_json", None), {})
            if (
                report.get("validation_basis") == "factor_prioritisation"
                and report.get("prioritisation_run_id") == factor_run["prioritisation_run_id"]
            ):
                row["report"] = report
                return row
        return None

    def _resolve_coverage_report(
        self, report_id: str | None, feedback_run_id: str
    ) -> dict[str, Any] | None:
        if report_id:
            return self.repo.get_report(report_id)
        rows = self.repo.db.query(
            "SELECT report_id, report_json, upload_id FROM validation_reports "
            "WHERE json_extract(report_json, '$.feedback_run_id')=? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 40",
            (feedback_run_id,),
        )
        parsed: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for row in rows:
            report = loads(row.pop("report_json", None), {})
            parsed.append((row, report))
        for row, report in parsed:
            if report.get("canonical_coverage"):
                row["report"] = report
                return row
        for row, report in parsed:
            row["report"] = report
            return row
        return None
