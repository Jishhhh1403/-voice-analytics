from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_whitespace_endpoint_returns_deterministic_empty_result(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "whitespace.db",
        auto_seed_source=False,
        auto_run_sample=False,
        object_store="local",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/whitespace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["lens_signals"] == []
    assert payload["verified_whitespaces"] == []
    assert payload["merged_whitespaces"] == []
    assert payload["diagnostics"]["feedback_record_count"] == 0
