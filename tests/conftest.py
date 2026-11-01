from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FEEDBACK_COLUMNS = [
    "feedback_id",
    "submitted_at",
    "source_type",
    "source_channel",
    "platform",
    "app_version",
    "language",
    "synthetic_customer_ref",
    "rating_1_to_5",
    "feedback_title",
    "feedback_text",
    "is_synthetic",
]

FEEDBACK_ROWS = [
    [
        "FB-T001",
        "2026-01-02T10:00:00Z",
        "in_app_feedback",
        "in_app",
        "Android",
        "4.1.0",
        "en",
        "SYN-1",
        "2",
        "Adding a beneficiary",
        "I tried to add a new beneficiary but it kept failing with an unclear error.",
        "true",
    ],
    [
        "FB-T002",
        "2026-01-03T10:00:00Z",
        "app_store_review",
        "review",
        "iOS",
        "4.1.0",
        "en",
        "SYN-2",
        "1",
        "Statement download",
        "The statement PDF will not generate and the screen just shows a spinner.",
        "true",
    ],
    [
        "FB-T003",
        "2026-01-04T10:00:00Z",
        "post_interaction_survey",
        "survey",
        "Web",
        "4.1.0",
        "en",
        "SYN-3",
        "2",
        "Transfer pending",
        "My IMPS transfer is still pending and I cannot see what to do next.",
        "true",
    ],
    [
        "FB-T004",
        "2026-01-05T10:00:00Z",
        "in_app_feedback",
        "in_app",
        "Android",
        "4.1.0",
        "en",
        "SYN-4",
        "1",
        "Double debit",
        "I was charged twice for the same bill payment. Call me on 9876543210 or email anita@example.com.",
        "true",
    ],
    [
        "FB-T005",
        "2026-01-06T10:00:00Z",
        "in_app_feedback",
        "in_app",
        "Android",
        "4.1.0",
        "en",
        "SYN-5",
        "2",
        "Duplicate",
        "I tried to add a new beneficiary but it kept failing with an unclear error.",
        "true",
    ],
    [
        "FB-T006",
        "2026-01-07T10:00:00Z",
        "in_app_feedback",
        "in_app",
        "Android",
        "4.1.0",
        "en",
        "SYN-6",
        "3",
        "No text",
        "",
        "true",
    ],
    [
        "FB-T007",
        "not-a-date",
        "in_app_feedback",
        "in_app",
        "Android",
        "4.1.0",
        "en",
        "SYN-7",
        "3",
        "Bad date",
        "The transfer status page is confusing and does not explain what to do next.",
        "true",
    ],
]

BACKLOG_COLUMNS = [
    "backlog_id",
    "title",
    "description",
    "acceptance_criteria",
    "product_area",
    "priority",
    "business_goal",
    "source_system",
]

BACKLOG_ROWS = [
    [
        "BL-T001",
        "Improve transfer status clarity",
        "Make pending and failed transfer states clear and explain the next step.",
        "Show pending, success and failed states; Explain what the customer should do next",
        "Payments",
        "High",
        "Reduce transfer complaints",
        "Jira",
    ],
    [
        "BL-T002",
        "Improve beneficiary registration reliability",
        "Reduce failures and unclear errors while adding a beneficiary.",
        "Validate account details; Show verification progress; Explain cooling-off period",
        "Payments",
        "High",
        "Improve beneficiary setup completion",
        "Jira",
    ],
    [
        "BL-T003",
        "Fix statement download",
        "Make statement PDF generation reliable and show actionable errors.",
        "Generate the PDF; Show progress; Recover from errors",
        "Statements",
        "Medium",
        "Restore statement self-service",
        "Jira",
    ],
]


def _write_csv(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    path.write_text(output.getvalue(), encoding="utf-8")


@pytest.fixture(scope="session")
def app_client(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("bci")
    feedback_path = root / "feedback.csv"
    backlog_path = root / "backlog.csv"
    _write_csv(feedback_path, FEEDBACK_COLUMNS, FEEDBACK_ROWS)
    _write_csv(backlog_path, BACKLOG_COLUMNS, BACKLOG_ROWS)

    settings = Settings(
        data_dir=root / "data",
        database_path=root / "data" / "test.db",
        local_object_root=root / "data" / "objects",
        sample_feedback_path=feedback_path,
        sample_backlog_path=backlog_path,
        taxonomy_path=Path(__file__).resolve().parents[1] / "taxonomy" / "banking_taxonomy_v1.yaml",
        auto_seed_source=False,
        auto_run_sample=False,
        object_store="local",
        extraction_provider="rules",
        embedding_provider="local",
        cors_origins="http://testserver",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        pipeline = app.state.pipeline
        uri = pipeline.ensure_default_source()
        stat = pipeline.store.stat(uri)
        run_id = pipeline.start(uri, stat.generation, None, force_rerun=True, run_in_thread=False)
        pipeline.execute(run_id, uri, stat.generation)
        yield client, app, run_id
