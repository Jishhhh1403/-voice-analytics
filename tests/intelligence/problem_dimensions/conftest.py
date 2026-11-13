from __future__ import annotations

import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import dumps
from app.main import create_app
from app.repository import Repository


def seed_problem_dimensions(repo: Repository, run_id: str = "RUN-DIM-TEST", count: int = 40) -> str:
    repo.db.insert(
        "pipeline_runs",
        {
            "run_id": run_id,
            "tenant_id": "test",
            "run_type": "feedback",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-31T00:00:00+00:00",
        },
    )
    modules = ["payments", "cards", "accounts", "onboarding", "support"]
    aspects = ["reliability", "clarity", "speed", "access"]
    symptoms = ["failure", "delay", "confusion", "error"]
    intents = ["transfer_money", "view_balance", "manage_card", "update_profile"]
    rng = random.Random(7)
    for index in range(count):
        problem_id = f"PRB-DIM-{index:03d}"
        module = modules[index % len(modules)]
        aspect = aspects[index % len(aspects)]
        symptom = symptoms[index % len(symptoms)]
        intent = intents[index % len(intents)]
        repo.db.insert(
            "customer_problems",
            {
                "problem_id": problem_id,
                "run_id": run_id,
                "signature": f"sig-{index}",
                "title": f"Problem {index}",
                "problem_statement": f"Statement {index}",
                "journey_node_id": f"{module}.{aspect}",
                "aspect": aspect,
                "symptom_category": symptom,
                "customer_intent": intent,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        )
        repo.db.insert(
            "problem_journey_mappings",
            {
                "mapping_id": f"MAP-{index}",
                "problem_id": problem_id,
                "module_id": module,
                "feature_id": f"{module}.{aspect}",
                "mapping_confidence": 0.9,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )
        volume = 2 + index % 9
        customers = 1 + index % 5
        negative = round(0.2 + (index % 7) / 10, 3)
        metrics = {
            "evidence_volume": volume,
            "evidence_volume_90d": volume,
            "distinct_customers": customers,
            "distinct_customers_90d": customers,
            "negative_share": negative,
            "negative_share_90d": negative,
            "repeat_complaint_count": index % 3,
            "repeat_complaint_count_90d": index % 3,
            "source_diversity": 1 + index % 4,
            "source_diversity_90d": 1 + index % 4,
            "volume_growth_pct": round(rng.uniform(-0.3, 0.6), 3),
            "negative_share_change": round(rng.uniform(-0.2, 0.2), 3),
        }
        for metric_name, value in metrics.items():
            repo.db.insert(
                "problem_measurement_snapshots",
                {
                    "snapshot_id": f"SNAP-{problem_id}-{metric_name}",
                    "run_id": run_id,
                    "problem_id": problem_id,
                    "metric_name": metric_name,
                    "metric_value": value,
                    "status": "OK",
                    "measurement_window_start": "2025-11-01T00:00:00+00:00",
                    "measurement_window_end": "2026-01-30T00:00:00+00:00",
                    "calculated_at": "2026-01-30T00:00:00+00:00",
                    "methodology_version": "test-1.0.0",
                },
            )
        for evidence_index, (effort, outcome, emotion) in enumerate(
            [("high", "failed", "frustration"), ("low", "completed", "satisfaction")]
        ):
            feedback_id = f"FB-{problem_id}-{evidence_index}"
            insight_id = f"IN-{problem_id}-{evidence_index}"
            repo.db.insert(
                "problem_evidence",
                {
                    "problem_id": problem_id,
                    "run_id": run_id,
                    "insight_id": insight_id,
                    "feedback_id": feedback_id,
                    "evidence_span": f"evidence {index} {evidence_index}",
                    "submitted_at": "2026-01-15T00:00:00+00:00",
                    "source_type": "app_store_review",
                    "created_at": "2026-01-15T00:00:00+00:00",
                },
            )
            repo.db.insert(
                "extracted_insights",
                {
                    "insight_id": insight_id,
                    "run_id": run_id,
                    "feedback_id": feedback_id,
                    "evidence_span": f"evidence {index} {evidence_index}",
                    "customer_effort": effort,
                    "reported_outcome": outcome,
                    "emotion": emotion,
                    "sentiment": "negative" if evidence_index == 0 else "positive",
                    "evidence_verified": 1,
                },
            )
    return run_id


def build_dimension_app(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "dim.db",
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
        problem_dimension_llm_enabled=False,
    )
    app = create_app(settings)
    run_id = seed_problem_dimensions(app.state.repo)
    return app, run_id


def _insert_problem(repo: Repository, run_id: str, problem_id: str, with_measurements: bool) -> None:
    repo.db.insert(
        "customer_problems",
        {
            "problem_id": problem_id,
            "run_id": run_id,
            "signature": f"sig-{problem_id}",
            "title": f"Title {problem_id}",
            "problem_statement": f"Statement {problem_id}",
            "journey_node_id": "payments.transfer",
            "aspect": "reliability",
            "symptom_category": "failure",
            "customer_intent": "transfer_money",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )
    repo.db.insert(
        "problem_journey_mappings",
        {
            "mapping_id": f"MAP-{problem_id}",
            "problem_id": problem_id,
            "module_id": "payments",
            "feature_id": "payments.transfer",
            "mapping_confidence": 0.9,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    )
    if not with_measurements:
        return
    repo.db.insert(
        "problem_measurement_snapshots",
        {
            "snapshot_id": f"SNAP-{problem_id}",
            "run_id": run_id,
            "problem_id": problem_id,
            "metric_name": "evidence_volume_90d",
            "metric_value": 4.0,
            "status": "OK",
            "measurement_window_start": "2025-11-01T00:00:00+00:00",
            "measurement_window_end": "2026-01-30T00:00:00+00:00",
            "calculated_at": "2026-01-30T00:00:00+00:00",
            "methodology_version": "test-1.0.0",
        },
    )


def dump_quality(checks: list[dict]) -> str:
    return dumps(checks) or ""


@pytest.fixture
def dimension_client(tmp_path):
    app, run_id = build_dimension_app(tmp_path)
    with TestClient(app) as client:
        yield client, app, run_id
