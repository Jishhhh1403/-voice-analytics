from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Banking Customer Intelligence"
    environment: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    tenant_id: str = "demo-bank"
    code_version: str = "0.1.0"
    schema_version: str = "1.0.0"

    data_dir: Path = REPO_ROOT / "data"
    database_path: Path | None = None
    object_store: str = "local"
    local_object_root: Path | None = None
    gcs_bucket: str = ""
    gcs_feedback_prefix: str = "feedback/source"
    gcs_backlog_prefix: str = "backlogs/uploads"
    gcs_reports_prefix: str = "reports"

    sample_feedback_path: Path = REPO_ROOT / "synthetic_banking_app_feedback_1800.csv"
    sample_backlog_path: Path = REPO_ROOT / "sample_backlog_upload.csv"
    taxonomy_path: Path = REPO_ROOT / "taxonomy" / "banking_taxonomy_v1.yaml"
    default_feedback_uri: str = ""
    auto_seed_source: bool = True
    auto_run_sample: bool = True
    pipeline_max_rows: int = 5000
    max_feedback_bytes: int = 25 * 1024 * 1024
    max_backlog_bytes: int = 10 * 1024 * 1024

    extraction_provider: str = "rules"
    llm_model: str = "gemini-2.0-flash"
    llm_timeout_seconds: int = 45
    llm_batch_size: int = 8
    gemini_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "http://localhost:11434/v1"
    openai_model: str = "llama3.1"

    embedding_provider: str = "local"
    embedding_dimensions: int = 96
    clustering_similarity_threshold: float = 0.64
    min_cluster_evidence: int = 1

    cors_origins: str = "http://localhost:5173,http://localhost:8080,http://localhost:3000"
    review_roles: str = "admin,journey_expert,product_owner,analyst"
    synthetic_warning: bool = True

    @property
    def db_path(self) -> Path:
        return self.database_path or (self.data_dir / "local" / "bci.db")

    @property
    def object_root(self) -> Path:
        return self.local_object_root or (self.data_dir / "local" / "objects")

    @property
    def cors_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.object_root.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
