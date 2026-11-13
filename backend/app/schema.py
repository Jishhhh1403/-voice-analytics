SCHEMA_SQL = r"""
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_type TEXT NOT NULL DEFAULT 'feedback',
    status TEXT NOT NULL,
    input_uri TEXT,
    input_generation TEXT,
    source_filename TEXT,
    code_version TEXT,
    schema_version TEXT,
    model_version TEXT,
    taxonomy_version TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    correlation_id TEXT,
    summary_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON pipeline_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_source ON pipeline_runs(input_uri, input_generation);

CREATE TABLE IF NOT EXISTS pipeline_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    processed INTEGER DEFAULT 0,
    succeeded INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    message TEXT,
    metrics_json TEXT,
    UNIQUE(run_id, stage)
);

CREATE TABLE IF NOT EXISTS ingestion_manifests (
    manifest_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    bucket TEXT,
    object_key TEXT,
    source_uri TEXT,
    generation TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    uploaded_at TEXT,
    original_filename TEXT,
    accepted_rows INTEGER,
    rejected_rows INTEGER,
    duplicate_rows INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_records (
    run_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL,
    source_feedback_id TEXT,
    tenant_id TEXT NOT NULL,
    submitted_at TEXT,
    source_type TEXT,
    source_channel TEXT,
    platform TEXT,
    app_version TEXT,
    language TEXT,
    synthetic_customer_ref TEXT,
    rating INTEGER,
    feedback_title TEXT,
    feedback_text_redacted TEXT NOT NULL,
    feedback_text_original TEXT,
    content_fingerprint TEXT NOT NULL,
    language_confidence REAL,
    duplicate_group_id TEXT,
    duplicate_type TEXT,
    quality_flags_json TEXT,
    pii_types_json TEXT,
    is_synthetic INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, feedback_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_run ON feedback_records(run_id);
CREATE INDEX IF NOT EXISTS idx_feedback_fingerprint ON feedback_records(content_fingerprint);

CREATE TABLE IF NOT EXISTS feedback_quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    row_number INTEGER,
    source_feedback_id TEXT,
    error_reason TEXT NOT NULL,
    raw_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extracted_insights (
    insight_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL,
    sentence_index INTEGER,
    customer_intent TEXT,
    aspect TEXT,
    journey_node_id TEXT,
    reported_problem TEXT,
    reported_symptom TEXT,
    sentiment TEXT,
    sentiment_score REAL,
    emotion TEXT,
    customer_effort TEXT,
    reported_outcome TEXT,
    evidence_span TEXT NOT NULL,
    language TEXT,
    intents_json TEXT,
    aspects_json TEXT,
    technical_root_cause TEXT DEFAULT 'unknown',
    evidence_verified INTEGER DEFAULT 1,
    field_confidence_json TEXT,
    human_review_status TEXT DEFAULT 'unreviewed',
    cluster_id TEXT,
    model_id TEXT,
    prompt_version TEXT,
    schema_version TEXT,
    extraction_timestamp TEXT,
    extraction_method TEXT,
    confidence REAL,
    embedding_json TEXT,
    is_problem INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_insights_run ON extracted_insights(run_id);
CREATE INDEX IF NOT EXISTS idx_insights_feedback ON extracted_insights(run_id, feedback_id);
CREATE INDEX IF NOT EXISTS idx_insights_problem ON extracted_insights(is_problem, run_id);

CREATE TABLE IF NOT EXISTS customer_problems (
    problem_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    title TEXT NOT NULL,
    problem_statement TEXT NOT NULL,
    canonical_description TEXT,
    customer_intent TEXT,
    aspect TEXT,
    symptom_category TEXT,
    journey_node_id TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    lifecycle_status TEXT NOT NULL DEFAULT 'candidate',
    validation_status TEXT DEFAULT 'candidate',
    human_review_status TEXT DEFAULT 'unreviewed',
    discovery_confidence REAL,
    embedding_ref TEXT,
    model_metadata_json TEXT,
    symptoms_json TEXT,
    parent_problem_id TEXT,
    evidence_count INTEGER DEFAULT 0,
    distinct_customers INTEGER DEFAULT 0,
    negative_count INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT,
    cluster_id TEXT,
    model_version TEXT,
    taxonomy_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_problems_run ON customer_problems(run_id);
CREATE INDEX IF NOT EXISTS idx_problems_journey ON customer_problems(journey_node_id);
CREATE INDEX IF NOT EXISTS idx_problems_evidence ON customer_problems(evidence_count DESC);

CREATE TABLE IF NOT EXISTS problem_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    insight_id TEXT,
    feedback_id TEXT NOT NULL,
    evidence_span TEXT NOT NULL,
    submitted_at TEXT,
    source_type TEXT,
    source_channel TEXT,
    platform TEXT,
    rating INTEGER,
    synthetic_customer_ref TEXT,
    weight REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    UNIQUE(problem_id, feedback_id, evidence_span)
);
CREATE INDEX IF NOT EXISTS idx_evidence_problem ON problem_evidence(problem_id);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON problem_evidence(run_id);

CREATE TABLE IF NOT EXISTS problem_clusters (
    cluster_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    label TEXT,
    description TEXT,
    algorithm TEXT,
    params_json TEXT,
    model_version TEXT,
    member_count INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taxonomy_nodes (
    node_id TEXT NOT NULL,
    version TEXT NOT NULL,
    parent_id TEXT,
    node_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    synonyms_json TEXT,
    status TEXT,
    aliases_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (node_id, version)
);

CREATE TABLE IF NOT EXISTS problem_mappings (
    mapping_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    mapping_type TEXT NOT NULL,
    confidence REAL,
    rationale TEXT,
    status TEXT DEFAULT 'candidate',
    taxonomy_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mapping_problem ON problem_mappings(problem_id);

CREATE TABLE IF NOT EXISTS taxonomy_proposals (
    proposal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    problem_id TEXT,
    suggested_name TEXT NOT NULL,
    parent_candidate TEXT,
    description TEXT,
    example_evidence TEXT,
    reason TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_problem_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    day TEXT NOT NULL,
    feedback_count INTEGER DEFAULT 0,
    negative_count INTEGER DEFAULT 0,
    positive_count INTEGER DEFAULT 0,
    neutral_count INTEGER DEFAULT 0,
    unique_customers INTEGER DEFAULT 0,
    UNIQUE(run_id, problem_id, day)
);

CREATE TABLE IF NOT EXISTS backlog_uploads (
    upload_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    filename TEXT,
    object_key TEXT,
    source_uri TEXT,
    generation TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    status TEXT NOT NULL,
    total_rows INTEGER DEFAULT 0,
    valid_rows INTEGER DEFAULT 0,
    invalid_rows INTEGER DEFAULT 0,
    errors_json TEXT,
    warnings_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backlog_items (
    item_pk TEXT PRIMARY KEY,
    upload_id TEXT NOT NULL,
    backlog_id TEXT NOT NULL,
    row_number INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    acceptance_criteria TEXT,
    product_area TEXT,
    priority TEXT,
    business_goal TEXT,
    source_system TEXT,
    structured_json TEXT,
    intended_outcome TEXT,
    customer_intent TEXT,
    target_feature TEXT,
    target_journey TEXT,
    functional_scope TEXT,
    organisational_objective TEXT,
    profile_json TEXT,
    extraction_provider TEXT,
    model_version TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(upload_id, backlog_id)
);
CREATE INDEX IF NOT EXISTS idx_backlog_upload ON backlog_items(upload_id);

CREATE TABLE IF NOT EXISTS validation_runs (
    run_id TEXT PRIMARY KEY,
    upload_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage_json TEXT,
    report_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS validation_reports (
    report_id TEXT PRIMARY KEY,
    upload_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    summary_json TEXT,
    report_json TEXT,
    reviewer_status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_findings (
    finding_id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    backlog_id TEXT NOT NULL,
    problem_id TEXT,
    relationship TEXT NOT NULL,
    rationale TEXT,
    alignment_score REAL,
    supporting_feedback_count INTEGER,
    evidence_json TEXT,
    journey_node_id TEXT,
    ac_coverage REAL,
    ac_gaps_json TEXT,
    uncertainty TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_report ON validation_findings(report_id);

CREATE TABLE IF NOT EXISTS review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL,
    backlog_id TEXT,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    detail_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

-- ------------------------------------------------------------------ enhanced
-- Module A: duplicate relationships. Complaints are never silently discarded;
-- exact and near duplicates keep their own feedback record and are linked here.
CREATE TABLE IF NOT EXISTS feedback_duplicate_candidates (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    feedback_id TEXT NOT NULL,
    candidate_feedback_id TEXT,
    duplicate_type TEXT NOT NULL,
    similarity REAL,
    customer_ref TEXT,
    detected_at TEXT NOT NULL,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_dup_run ON feedback_duplicate_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_dup_feedback ON feedback_duplicate_candidates(feedback_id);

CREATE TABLE IF NOT EXISTS data_quality_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    affected_rows INTEGER DEFAULT 0,
    detail_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dq_run ON data_quality_reports(run_id);

-- Module C/E1: relational problem relationships and symptoms.
CREATE TABLE IF NOT EXISTS problem_relationships (
    relationship_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_problem_id TEXT NOT NULL,
    target_problem_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    confidence REAL,
    status TEXT DEFAULT 'candidate',
    rationale TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_problem_rel_source ON problem_relationships(source_problem_id);

CREATE TABLE IF NOT EXISTS problem_symptoms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id TEXT NOT NULL,
    symptom_key TEXT,
    symptom_label TEXT NOT NULL,
    symptom_category TEXT,
    confidence REAL,
    created_at TEXT NOT NULL,
    UNIQUE(problem_id, symptom_label)
);

-- Module D: versioned problem to journey mapping with hierarchical dimensions.
CREATE TABLE IF NOT EXISTS problem_journey_mappings (
    mapping_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,
    module_id TEXT,
    feature_id TEXT,
    journey_stage_id TEXT,
    mapping_confidence REAL,
    explanation TEXT,
    status TEXT DEFAULT 'candidate',
    taxonomy_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pjm_problem ON problem_journey_mappings(problem_id);

-- Module E2: measurement provenance. Missing data is represented explicitly,
-- never as a fabricated zero.
CREATE TABLE IF NOT EXISTS problem_metrics_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    day TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    unit TEXT,
    status TEXT NOT NULL,
    methodology_version TEXT,
    UNIQUE(run_id, problem_id, day, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_pmd_problem ON problem_metrics_daily(problem_id, day);

CREATE TABLE IF NOT EXISTS problem_measurement_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    metric_text_value TEXT,
    unit TEXT,
    status TEXT NOT NULL,
    calculation_method TEXT,
    measurement_window_start TEXT,
    measurement_window_end TEXT,
    input_record_count INTEGER DEFAULT 0,
    source_availability TEXT,
    quality_indicator REAL,
    calculated_at TEXT NOT NULL,
    methodology_version TEXT,
    dimensions_json TEXT,
    metadata_json TEXT,
    UNIQUE(run_id, problem_id, metric_name, methodology_version)
);
CREATE INDEX IF NOT EXISTS idx_pms_run ON problem_measurement_snapshots(run_id, problem_id);
CREATE INDEX IF NOT EXISTS idx_pms_metric ON problem_measurement_snapshots(metric_name, status);

CREATE TABLE IF NOT EXISTS problem_priority_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    customer_impact_score REAL,
    business_risk_score REAL,
    operational_impact_score REAL,
    trend_score REAL,
    strategic_score REAL,
    priority_score REAL,
    rank INTEGER,
    escalation_status TEXT NOT NULL,
    escalation_reasons_json TEXT,
    missing_metrics_json TEXT,
    supporting_evidence_json TEXT,
    methodology_version TEXT NOT NULL,
    measurement_window_start TEXT,
    measurement_window_end TEXT,
    calculated_at TEXT NOT NULL,
    UNIQUE(run_id, problem_id, methodology_version)
);
CREATE INDEX IF NOT EXISTS idx_pps_run ON problem_priority_snapshots(run_id, rank);

CREATE TABLE IF NOT EXISTS scoring_methodology_versions (
    version TEXT PRIMARY KEY,
    description TEXT,
    weights_json TEXT,
    created_at TEXT NOT NULL
);

-- MDS theme map: representative theme vectors, 2D coordinates, stress and
-- nearest-neighbour similarities. Positions are semantic only; business
-- attributes are joined from measurement and priority snapshots.
CREATE TABLE IF NOT EXISTS problem_theme_vectors (
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, problem_id)
);
CREATE INDEX IF NOT EXISTS idx_ptv_run ON problem_theme_vectors(run_id);

CREATE TABLE IF NOT EXISTS problem_mds_runs (
    mds_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    methodology_version TEXT NOT NULL,
    embedding_model TEXT,
    distance_metric TEXT NOT NULL DEFAULT 'cosine',
    n_themes INTEGER NOT NULL DEFAULT 0,
    stress REAL,
    normalized_stress REAL,
    stress_status TEXT,
    params_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, methodology_version)
);
CREATE INDEX IF NOT EXISTS idx_mds_runs_run ON problem_mds_runs(run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS problem_mds_points (
    mds_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    display_x REAL NOT NULL,
    display_y REAL NOT NULL,
    vector_source TEXT,
    metadata_json TEXT,
    PRIMARY KEY (mds_id, problem_id)
);
CREATE INDEX IF NOT EXISTS idx_mds_points_run ON problem_mds_points(run_id);
CREATE INDEX IF NOT EXISTS idx_mds_points_problem ON problem_mds_points(problem_id);

CREATE TABLE IF NOT EXISTS problem_mds_neighbors (
    mds_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    neighbor_problem_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    cosine_similarity REAL NOT NULL,
    cosine_distance REAL NOT NULL,
    PRIMARY KEY (mds_id, problem_id, rank)
);
CREATE INDEX IF NOT EXISTS idx_mds_neighbors_run ON problem_mds_neighbors(run_id, problem_id);

CREATE TABLE IF NOT EXISTS model_execution_history (
    execution_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    provider TEXT,
    model_id TEXT,
    prompt_version TEXT,
    input_count INTEGER DEFAULT 0,
    output_count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    metadata_json TEXT,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_meh_run ON model_execution_history(run_id, stage);

CREATE TABLE IF NOT EXISTS human_review_decisions (
    review_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    original_value TEXT,
    corrected_value TEXT,
    note TEXT,
    methodology_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hrd_entity ON human_review_decisions(entity_type, entity_id);

-- Module F/G: retrieval provenance, coverage matrix and optional analyses.
CREATE TABLE IF NOT EXISTS backlog_problem_candidates (
    candidate_id TEXT PRIMARY KEY,
    report_id TEXT,
    validation_run_id TEXT,
    backlog_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    dense_score REAL,
    sparse_score REAL,
    fused_score REAL,
    rerank_score REAL,
    rank INTEGER,
    reasons_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bpc_report ON backlog_problem_candidates(report_id);

CREATE TABLE IF NOT EXISTS backlog_coverage_matrix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL,
    backlog_id TEXT NOT NULL,
    problem_id TEXT,
    relationship TEXT NOT NULL,
    coverage_type TEXT NOT NULL,
    alignment_score REAL,
    priority_score REAL,
    priority_rank INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bcm_report ON backlog_coverage_matrix(report_id);

CREATE TABLE IF NOT EXISTS survival_analysis_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    problem_id TEXT,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    estimate_json TEXT,
    assumptions_json TEXT,
    calculated_at TEXT NOT NULL,
    methodology_version TEXT
);

CREATE TABLE IF NOT EXISTS conjoint_analysis_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    problem_id TEXT,
    status TEXT NOT NULL,
    attribute_importance_json TEXT,
    part_worth_json TEXT,
    sample_metadata_json TEXT,
    calculated_at TEXT NOT NULL,
    methodology_version TEXT
);

-- ---------------------------------------------------------------- factor analysis
-- Additive exploratory dimension analysis over canonical problems. These
-- tables are immutable per analysis run and never overwrite canonical problem
-- records, priority scores or MDS coordinates.
CREATE TABLE IF NOT EXISTS problem_feature_snapshots (
    snapshot_id TEXT NOT NULL,
    feedback_run_id TEXT NOT NULL,
    canonical_problem_id TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    feature_values_json TEXT NOT NULL,
    feature_types_json TEXT,
    source_measurement_ids_json TEXT,
    quality_flags_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, canonical_problem_id)
);
CREATE INDEX IF NOT EXISTS idx_pfs_feedback_run ON problem_feature_snapshots(feedback_run_id);
CREATE INDEX IF NOT EXISTS idx_pfs_snapshot ON problem_feature_snapshots(snapshot_id);

CREATE TABLE IF NOT EXISTS dimension_analysis_runs (
    run_id TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    method_version TEXT NOT NULL,
    method_library_version TEXT,
    input_snapshot_id TEXT,
    feedback_run_id TEXT,
    feature_schema_version TEXT NOT NULL,
    parameters_json TEXT,
    selected_features_json TEXT,
    excluded_features_json TEXT,
    configuration_json TEXT,
    status TEXT NOT NULL,
    stage TEXT,
    diagnostics_json TEXT,
    feature_quality_json TEXT,
    feature_dictionary_json TEXT,
    code_version TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_dar_created ON dimension_analysis_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dar_status ON dimension_analysis_runs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dar_feedback_run ON dimension_analysis_runs(feedback_run_id);

CREATE TABLE IF NOT EXISTS problem_dimension_scores (
    run_id TEXT NOT NULL,
    canonical_problem_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    coordinate REAL NOT NULL,
    relative_squared_coordinate_share_pct REAL,
    coordinate_rank INTEGER,
    contribution_metadata_json TEXT,
    score_status TEXT NOT NULL DEFAULT 'OK',
    PRIMARY KEY (run_id, canonical_problem_id, dimension_id)
);
CREATE INDEX IF NOT EXISTS idx_pds_run ON problem_dimension_scores(run_id);
CREATE INDEX IF NOT EXISTS idx_pds_problem ON problem_dimension_scores(canonical_problem_id);

CREATE TABLE IF NOT EXISTS problem_dimension_equations (
    run_id TEXT NOT NULL,
    canonical_problem_id TEXT NOT NULL,
    equation_text TEXT NOT NULL,
    number_of_dimensions INTEGER NOT NULL,
    coefficient_representation_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, canonical_problem_id)
);
CREATE INDEX IF NOT EXISTS idx_pde_run ON problem_dimension_equations(run_id);

CREATE TABLE IF NOT EXISTS dimension_definitions (
    run_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    dimension_number INTEGER,
    analyst_name TEXT NOT NULL,
    proposed_label TEXT,
    description TEXT,
    business_interpretation TEXT,
    interpretation_status TEXT NOT NULL DEFAULT 'DRAFT',
    model_version TEXT,
    top_variables_json TEXT,
    representative_problem_ids_json TEXT,
    review_status TEXT NOT NULL DEFAULT 'DRAFT',
    reviewer TEXT,
    review_note TEXT,
    reviewed_at TEXT,
    PRIMARY KEY (run_id, dimension_id)
);
CREATE INDEX IF NOT EXISTS idx_dd_run ON dimension_definitions(run_id);
CREATE INDEX IF NOT EXISTS idx_dd_review ON dimension_definitions(run_id, review_status);

CREATE TABLE IF NOT EXISTS dimension_variable_contributions (
    run_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    variable_name TEXT NOT NULL,
    category_level TEXT NOT NULL DEFAULT '',
    contribution REAL NOT NULL,
    coordinate REAL,
    direction_summary TEXT,
    rank INTEGER,
    PRIMARY KEY (run_id, dimension_id, variable_name, category_level)
);
CREATE INDEX IF NOT EXISTS idx_dvc_run ON dimension_variable_contributions(run_id, dimension_id, rank);

CREATE TABLE IF NOT EXISTS dimension_problem_membership (
    run_id TEXT NOT NULL,
    canonical_problem_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    membership_type TEXT NOT NULL,
    score REAL NOT NULL,
    margin REAL,
    is_ambiguous INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, canonical_problem_id, dimension_id)
);
CREATE INDEX IF NOT EXISTS idx_dpm_run ON dimension_problem_membership(run_id, dimension_id, score DESC);

CREATE TABLE IF NOT EXISTS dimension_trends (
    run_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    time_window TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    denominator REAL,
    status TEXT NOT NULL,
    PRIMARY KEY (run_id, dimension_id, time_window, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_dt_run ON dimension_trends(run_id, dimension_id);

CREATE TABLE IF NOT EXISTS dimension_publications (
    publication_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    action TEXT NOT NULL,
    published_by TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dpub_run ON dimension_publications(run_id, created_at DESC);

-- ------------------------------------------------- problem portfolio narrative
-- A portfolio run binds one completed feedback run to one reviewed factor run
-- and one MDS snapshot. The statistical serialization is deterministic and is
-- persisted separately from the LLM narrative so it can be audited or reused.
CREATE TABLE IF NOT EXISTS problem_portfolio_analysis_runs (
    run_id TEXT PRIMARY KEY,
    feedback_run_id TEXT NOT NULL,
    dimension_run_id TEXT NOT NULL,
    mds_id TEXT,
    status TEXT NOT NULL,
    stage TEXT,
    serialization_version TEXT NOT NULL,
    narrative_model TEXT,
    prompt_version TEXT,
    parameters_json TEXT,
    summary_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ppar_created ON problem_portfolio_analysis_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ppar_feedback ON problem_portfolio_analysis_runs(feedback_run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ppar_status ON problem_portfolio_analysis_runs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS problem_factor_nomenclature (
    run_id TEXT NOT NULL,
    factor_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    dimension_number INTEGER,
    business_name TEXT NOT NULL,
    description TEXT,
    review_status TEXT NOT NULL,
    source TEXT NOT NULL,
    provisional INTEGER NOT NULL DEFAULT 0,
    aliases_json TEXT,
    top_variables_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, factor_id)
);
CREATE INDEX IF NOT EXISTS idx_pfn_run ON problem_factor_nomenclature(run_id, dimension_number);

CREATE TABLE IF NOT EXISTS problem_factor_profiles (
    run_id TEXT NOT NULL,
    factor_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    dimension_number INTEGER,
    eigenvalue REAL,
    explained_variance REAL,
    cumulative_variance REAL,
    problem_count INTEGER NOT NULL DEFAULT 0,
    problem_share_pct REAL,
    mean_abs_coefficient REAL,
    max_abs_coefficient REAL,
    top_variables_json TEXT,
    top_categories_json TEXT,
    representative_problem_ids_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, factor_id)
);
CREATE INDEX IF NOT EXISTS idx_pfp_run ON problem_factor_profiles(run_id, dimension_number);

CREATE TABLE IF NOT EXISTS problem_mds_relationships (
    run_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    neighbor_problem_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    euclidean_distance REAL NOT NULL,
    distance_space TEXT NOT NULL,
    neighbor_title TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, problem_id, rank)
);
CREATE INDEX IF NOT EXISTS idx_pmr_run ON problem_mds_relationships(run_id, problem_id);

CREATE TABLE IF NOT EXISTS problem_portfolio_serializations (
    serialization_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pps_hash ON problem_portfolio_serializations(content_hash);

CREATE TABLE IF NOT EXISTS problem_portfolio_narratives (
    narrative_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    serialization_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    narrative_json TEXT,
    generation_attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ppn_run ON problem_portfolio_narratives(run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS problem_narrative_validation (
    validation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    status TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    errors_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pnv_narrative ON problem_narrative_validation(narrative_id, created_at DESC);
"""
