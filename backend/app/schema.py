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
    content_fingerprint TEXT NOT NULL,
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
    customer_intent TEXT,
    aspect TEXT,
    symptom_category TEXT,
    journey_node_id TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    lifecycle_status TEXT NOT NULL DEFAULT 'candidate',
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
"""
