from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import dumps
from app.main import create_app


def seed_portfolio(repo, feedback_run_id: str = "RUN-PORTFOLIO-TEST") -> tuple[str, str]:
    repo.db.insert(
        "pipeline_runs",
        {
            "run_id": feedback_run_id,
            "tenant_id": "test",
            "run_type": "feedback",
            "status": "completed",
            "taxonomy_version": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-31T00:00:00+00:00",
        },
    )
    problems = [
        ("PRB-001", "Transfer stuck in pending", "payments.transfer", 10, 4, 0.7),
        ("PRB-002", "Statement download fails", "statements.download", 6, 3, 0.5),
        ("PRB-003", "Card activation unclear", "cards.activation", 3, 2, 0.3),
    ]
    for index, (problem_id, title, journey, volume, customers, negative) in enumerate(problems):
        repo.db.insert(
            "customer_problems",
            {
                "problem_id": problem_id,
                "run_id": feedback_run_id,
                "signature": f"sig-{problem_id}",
                "title": title,
                "problem_statement": title,
                "canonical_description": f"{title} description",
                "journey_node_id": journey,
                "aspect": "reliability",
                "symptom_category": "failure",
                "customer_intent": "complete_task",
                "lifecycle_status": "validated",
                "human_review_status": "accepted",
                "validation_status": "validated",
                "evidence_count": volume,
                "distinct_customers": customers,
                "negative_count": int(volume * negative),
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        )
        metrics = {
            "evidence_volume": volume,
            "distinct_customers": customers,
            "negative_share": negative,
            "repeat_complaint_count": index,
            "source_diversity": 2,
        }
        for metric_name, value in metrics.items():
            repo.db.insert(
                "problem_measurement_snapshots",
                {
                    "snapshot_id": f"MS-{problem_id}-{metric_name}",
                    "run_id": feedback_run_id,
                    "problem_id": problem_id,
                    "metric_name": metric_name,
                    "metric_value": value,
                    "unit": "records" if metric_name == "evidence_volume" else None,
                    "status": "OK",
                    "calculation_method": "test",
                    "measurement_window_start": "2026-01-01T00:00:00+00:00",
                    "measurement_window_end": "2026-01-31T00:00:00+00:00",
                    "input_record_count": volume,
                    "source_availability": "available",
                    "calculated_at": "2026-01-31T00:00:00+00:00",
                    "methodology_version": "test-1.0.0",
                },
            )
        repo.db.insert(
            "problem_measurement_snapshots",
            {
                "snapshot_id": f"MS-{problem_id}-missing",
                "run_id": feedback_run_id,
                "problem_id": problem_id,
                "metric_name": "assessment_velocity_delta",
                "metric_value": None,
                "status": "NO_DATA",
                "calculation_method": "test",
                "measurement_window_start": "2026-01-01T00:00:00+00:00",
                "measurement_window_end": "2026-01-31T00:00:00+00:00",
                "input_record_count": 0,
                "source_availability": "none",
                "calculated_at": "2026-01-31T00:00:00+00:00",
                "methodology_version": "test-1.0.0",
            },
        )
        repo.db.insert(
            "problem_priority_snapshots",
            {
                "snapshot_id": f"PS-{problem_id}",
                "run_id": feedback_run_id,
                "problem_id": problem_id,
                "customer_impact_score": 0.8 - index * 0.1,
                "business_risk_score": 0.6 - index * 0.1,
                "operational_impact_score": 0.5,
                "trend_score": 0.4,
                "strategic_score": 0.3,
                "priority_score": 0.75 - index * 0.1,
                "rank": index + 1,
                "escalation_status": "high" if index == 0 else "medium",
                "escalation_reasons_json": dumps([]),
                "missing_metrics_json": dumps([]),
                "supporting_evidence_json": dumps({}),
                "methodology_version": "priority-test-1.0.0",
                "measurement_window_start": "2026-01-01T00:00:00+00:00",
                "measurement_window_end": "2026-01-31T00:00:00+00:00",
                "calculated_at": "2026-01-31T00:00:00+00:00",
            },
        )

    dimension_run_id = "DIM-PORTFOLIO-TEST"
    repo.db.insert(
        "dimension_analysis_runs",
        {
            "run_id": dimension_run_id,
            "method": "FAMD",
            "method_version": "famd-test-1.0.0",
            "method_library_version": "prince-test",
            "input_snapshot_id": "SNAP-PORTFOLIO",
            "feedback_run_id": feedback_run_id,
            "feature_schema_version": "problem-dimensions-test",
            "parameters_json": dumps({"requested_components": 12}),
            "selected_features_json": dumps([]),
            "excluded_features_json": dumps([]),
            "configuration_json": dumps({}),
            "status": "APPROVED",
            "stage": "APPROVED",
            "diagnostics_json": dumps(
                {
                    "dimensions": [
                        {
                            "dimension_id": "D1",
                            "dimension_number": 1,
                            "factor_id": "F1",
                            "eigenvalue": 1.8,
                            "explained_variance": 30.0,
                            "cumulative_variance": 30.0,
                        },
                        {
                            "dimension_id": "D2",
                            "dimension_number": 2,
                            "factor_id": "F2",
                            "eigenvalue": 1.2,
                            "explained_variance": 20.0,
                            "cumulative_variance": 50.0,
                        },
                    ]
                }
            ),
            "feature_quality_json": dumps([]),
            "feature_dictionary_json": dumps([]),
            "code_version": "test",
            "created_at": "2026-02-01T00:00:00+00:00",
            "started_at": "2026-02-01T00:00:00+00:00",
            "completed_at": "2026-02-01T00:01:00+00:00",
            "error": None,
        },
    )
    for dimension_id, number, name in (
        ("D1", 1, "Payments reliability"),
        ("D2", 2, "Self-service clarity"),
    ):
        repo.db.insert(
            "dimension_definitions",
            {
                "run_id": dimension_run_id,
                "dimension_id": dimension_id,
                "dimension_number": number,
                "analyst_name": name,
                "proposed_label": name,
                "description": f"{name} factor description",
                "business_interpretation": None,
                "interpretation_status": "APPROVED",
                "model_version": "famd-test",
                "top_variables_json": dumps(
                    [
                        {
                            "variable_name": "negative_share",
                            "category_level": None,
                            "contribution": 0.4,
                            "coordinate": 0.8,
                            "direction_summary": "+",
                            "rank": 1,
                        }
                    ]
                ),
                "representative_problem_ids_json": dumps(["PRB-001", "PRB-002"]),
                "review_status": "APPROVED",
                "reviewer": "analyst@test",
                "review_note": "approved",
                "reviewed_at": "2026-02-02T00:00:00+00:00",
            },
        )
        repo.db.insert(
            "dimension_variable_contributions",
            {
                "run_id": dimension_run_id,
                "dimension_id": dimension_id,
                "variable_name": "negative_share",
                "category_level": "",
                "contribution": 0.4,
                "coordinate": 0.8,
                "direction_summary": "+",
                "rank": 1,
            },
        )
        repo.db.insert(
            "dimension_variable_contributions",
            {
                "run_id": dimension_run_id,
                "dimension_id": dimension_id,
                "variable_name": "aspect",
                "category_level": "reliability",
                "contribution": 0.3,
                "coordinate": None,
                "direction_summary": None,
                "rank": 1,
            },
        )
    scores = [
        ("PRB-001", "D1", 2.0, 80.0, 1),
        ("PRB-001", "D2", 1.0, 20.0, 2),
        ("PRB-002", "D1", -1.0, 20.0, 2),
        ("PRB-002", "D2", 2.0, 80.0, 1),
        ("PRB-003", "D1", 0.5, 50.0, 1),
        ("PRB-003", "D2", 0.5, 50.0, 1),
    ]
    for problem_id, dimension_id, coordinate, share, rank in scores:
        repo.db.insert(
            "problem_dimension_scores",
            {
                "run_id": dimension_run_id,
                "canonical_problem_id": problem_id,
                "dimension_id": dimension_id,
                "coordinate": coordinate,
                "relative_squared_coordinate_share_pct": share,
                "coordinate_rank": rank,
                "contribution_metadata_json": dumps({}),
                "score_status": "OK",
            },
        )
    for problem_id in ("PRB-001", "PRB-002", "PRB-003"):
        repo.db.insert(
            "problem_dimension_equations",
            {
                "run_id": dimension_run_id,
                "canonical_problem_id": problem_id,
                "equation_text": f"{problem_id} = 1.000000*F1 + 1.000000*F2",
                "number_of_dimensions": 2,
                "coefficient_representation_json": dumps([]),
                "created_at": "2026-02-01T00:00:00+00:00",
            },
        )

    mds_id = "MDS-PORTFOLIO-TEST"
    repo.db.insert(
        "problem_mds_runs",
        {
            "mds_id": mds_id,
            "run_id": feedback_run_id,
            "status": "OK",
            "methodology_version": "mds-test-1.0.0",
            "embedding_model": "test",
            "distance_metric": "cosine",
            "n_themes": 3,
            "stress": 0.1,
            "normalized_stress": 0.05,
            "stress_status": "good",
            "params_json": dumps({"distance_metric": "cosine"}),
            "created_at": "2026-02-01T00:00:00+00:00",
        },
    )
    for problem_id, x, y in (("PRB-001", 0.0, 0.0), ("PRB-002", 3.0, 4.0), ("PRB-003", 6.0, 8.0)):
        repo.db.insert(
            "problem_mds_points",
            {
                "mds_id": mds_id,
                "run_id": feedback_run_id,
                "problem_id": problem_id,
                "x": x,
                "y": y,
                "display_x": x,
                "display_y": y,
                "vector_source": "test",
                "metadata_json": dumps({}),
            },
        )
    return feedback_run_id, dimension_run_id


def build_portfolio_app(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "portfolio.db",
        local_object_root=tmp_path / "data" / "objects",
        sample_feedback_path=tmp_path / "feedback.csv",
        sample_backlog_path=tmp_path / "backlog.csv",
        taxonomy_path=Path(__file__).resolve().parents[3] / "taxonomy" / "banking_taxonomy_v1.yaml",
        auto_seed_source=False,
        auto_run_sample=False,
        object_store="local",
        extraction_provider="rules",
        embedding_provider="local",
        cors_origins="http://testserver",
        problem_dimension_require_review=True,
        gemini_api_key="",
        enable_problem_portfolio=True,
    )
    app = create_app(settings)
    feedback_run_id, dimension_run_id = seed_portfolio(app.state.repo)
    return app, feedback_run_id, dimension_run_id


@pytest.fixture
def portfolio_client(tmp_path):
    app, feedback_run_id, dimension_run_id = build_portfolio_app(tmp_path)
    with TestClient(app) as client:
        yield client, app, feedback_run_id, dimension_run_id
