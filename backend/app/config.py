from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    sample_feedback_path: Path = REPO_ROOT / "synthetic_banking_app_feedback_15000.csv"
    sample_backlog_path: Path = REPO_ROOT / "sample_backlog_upload.csv"
    taxonomy_path: Path = REPO_ROOT / "taxonomy" / "banking_taxonomy_v1.yaml"
    default_feedback_uri: str = ""
    auto_seed_source: bool = True
    auto_run_sample: bool = True
    pipeline_max_rows: int = 25000
    max_feedback_bytes: int = 25 * 1024 * 1024
    max_backlog_bytes: int = 10 * 1024 * 1024

    extraction_provider: str = "rules"
    llm_model: str = "gemini-2.0-flash"
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: int = 45
    llm_batch_size: int = 8
    gemini_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "http://localhost:11434/v1"
    openai_model: str = "llama3.1"
    prompt_version: str = "extraction-2.0"
    model_confidence_calibrated: bool = False

    embedding_provider: str = "local"
    embedding_dimensions: int = 96
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vertex_embedding_model: str = "text-embedding-004"
    vertex_location: str = "us-central1"
    embedding_cache_dir: Path | None = None
    embedding_batch_size: int = 64
    clustering_provider: str = "legacy"
    clustering_similarity_threshold: float = 0.64
    min_cluster_evidence: int = 1
    min_cluster_size: int = 2
    min_samples: int = 1
    cluster_selection_method: str = "eom"
    canonicalisation_provider: str = "deterministic"

    retrieval_provider: str = "hybrid"
    retrieval_top_k: int = 8
    retrieval_dense_weight: float = 0.6
    retrieval_sparse_weight: float = 0.4
    reranker_provider: str = "none"
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    pii_provider: str = "regex"
    pii_presidio_language: str = "en"
    language_detection_provider: str = "heuristic"
    detect_language: bool = True
    near_duplicate_threshold: float = 0.85
    near_duplicate_min_tokens: int = 5
    repeat_complaint_window_days: int = 30
    data_quality_min_chars: int = 3
    data_quality_max_chars: int = 5000

    taxonomy_semantic_threshold: float = 0.45
    taxonomy_accept_threshold: float = 0.55
    taxonomy_open_set_threshold: float = 0.35
    taxonomy_cross_encoder_enabled: bool = False

    enable_priority_engine: bool = True
    enable_survival_analysis: bool = False
    enable_mds: bool = True
    mds_methodology_version: str = "mds-1.0.0"
    mds_random_state: int = 42
    mds_max_iter: int = 300
    mds_neighbors: int = 5
    mds_min_themes: int = 2
    mds_max_themes: int = 500
    mds_coordinate_scale: float = 1.0
    enable_conjoint_analysis: bool = False
    enable_problem_dimensions: bool = True
    problem_dimension_method: str = "FAMD"
    problem_dimension_methodology_version: str = "famd-1.0.0"
    problem_dimension_feature_schema_version: str = "problem-dimensions-1.0.0"
    problem_dimension_method_library: str = "prince"
    problem_dimension_max_components: int = 20
    problem_dimension_min_problems: int = 30
    problem_dimension_min_category_count: int = 2
    problem_dimension_random_state: int = 42
    problem_dimension_bootstrap_iterations: int = 0
    problem_dimension_require_review: bool = True
    problem_dimension_max_contributions: int = 25
    problem_dimension_publish_components: int = 12
    problem_dimension_active_features: str = ""
    problem_dimension_supplementary_features: str = ""
    problem_dimension_excluded_features: str = ""
    problem_dimension_include_missing_indicators: bool = False
    problem_dimension_llm_enabled: bool = True
    problem_dimension_llm_provider: str = "gemini"
    problem_dimension_llm_fallback_provider: str = ""
    problem_dimension_llm_base_url: str = ""
    problem_dimension_llm_api_key: str = ""
    problem_dimension_llm_model: str = ""
    problem_dimension_llm_temperature: float = 0.1
    problem_dimension_llm_max_output_tokens: int = 8192
    problem_dimension_llm_timeout_seconds: int = 180
    problem_dimension_llm_max_attempts: int = 3
    problem_dimension_llm_batch_size: int = 6
    problem_dimension_llm_cross_review: bool = True
    problem_dimension_llm_context_observations: int = 40
    problem_dimension_factor_nomenclature_prompt_version: str = "dimension-factor-equation-nomenclature-1.0.0"
    problem_dimension_factor_narrative_prompt_version: str = "dimension-factor-narrative-1.1.0"
    problem_dimension_factor_narrative_model_fallbacks: str = "gemini-3.1-flash-lite"
    problem_dimension_factor_narrative_max_output_tokens: int = 16384
    problem_dimension_factor_narrative_timeout_seconds: int = 600
    problem_dimension_factor_narrative_retry_attempts: int = 2
    problem_dimension_interpretation_prompt_version: str = "dimension-problem-interpretation-1.0.0"
    problem_dimension_aggregation_prompt_version: str = "dimension-evidence-aggregation-1.0.0"
    problem_dimension_nomenclature_prompt_version: str = "dimension-nomenclature-1.0.0"
    problem_dimension_cross_review_prompt_version: str = "dimension-cross-review-1.0.0"
    enable_problem_dimension_efa: bool = False

    enable_factor_prioritisation: bool = True
    factor_prioritisation_model_version: str = "factor-evidence-v1"
    factor_prioritisation_weight_prevalence: float = 0.30
    factor_prioritisation_weight_statistical: float = 0.25
    factor_prioritisation_weight_representation: float = 0.25
    factor_prioritisation_weight_semantic: float = 0.20
    factor_prioritisation_membership_rule_version: str = "famd-membership-1.0.0"
    factor_prioritisation_membership_min_score: float = 1.0
    factor_prioritisation_representation_rule_version: str = "famd-row-contribution-1.0.0"
    factor_prioritisation_representation_multiplier: float = 1.0
    factor_prioritisation_semantic_rule_version: str = "attribute-coherence-1.0.0"
    factor_prioritisation_allow_provisional: bool = True
    factor_prioritisation_min_problem_count: int = 1

    enable_measurement_engine: bool = True
    priority_weight_customer_impact: float = 0.30
    priority_weight_business_risk: float = 0.30
    priority_weight_operational_impact: float = 0.15
    priority_weight_trend: float = 0.15
    priority_weight_strategic: float = 0.10
    priority_escalation_risk_threshold: float = 0.75
    measurement_window_days: int = 90
    trend_baseline_days: int = 30
    trend_current_days: int = 30
    scoring_methodology_version: str = "priority-1.0.0"

    enable_problem_portfolio: bool = True
    portfolio_serialization_version: str = "problem-portfolio-1.0.0"
    portfolio_narrative_provider: str = "gemini"
    portfolio_narrative_prompt_version: str = "portfolio-narrative-1.0.0"
    portfolio_narrative_max_attempts: int = 2
    portfolio_narrative_temperature: float = 0.2
    portfolio_narrative_max_output_tokens: int = 8192
    portfolio_narrative_timeout_seconds: int = 180
    portfolio_max_problems: int = 1000
    portfolio_require_approved_factors: bool = True

    analytics_backend: str = "sqlite"
    bigquery_project: str = ""
    bigquery_dataset_prefix: str = ""
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
