-- BigQuery target schema for the production migration.
-- Replace ${PROJECT_ID} before running, or run through scripts/gcp_deploy.sh.
-- Datasets are created by Terraform; this file creates tables, partitions and clusters.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.pipeline_runs` (
  run_id STRING NOT NULL,
  tenant_id STRING NOT NULL,
  run_type STRING NOT NULL,
  status STRING NOT NULL,
  input_uri STRING,
  input_generation STRING,
  source_filename STRING,
  code_version STRING,
  schema_version STRING,
  model_version STRING,
  taxonomy_version STRING,
  created_at TIMESTAMP NOT NULL,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  correlation_id STRING,
  summary_json JSON,
  error STRING
)
PARTITION BY DATE(created_at)
CLUSTER BY tenant_id, run_type, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.pipeline_stages` (
  run_id STRING NOT NULL,
  stage STRING NOT NULL,
  status STRING NOT NULL,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  processed INT64,
  succeeded INT64,
  failed INT64,
  message STRING,
  metrics_json JSON
)
PARTITION BY DATE(started_at)
CLUSTER BY run_id, stage;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.ingestion_manifests` (
  manifest_id STRING NOT NULL,
  run_id STRING NOT NULL,
  bucket STRING,
  object_key STRING,
  source_uri STRING,
  generation STRING,
  size_bytes INT64,
  sha256 STRING,
  uploaded_at TIMESTAMP,
  original_filename STRING,
  accepted_rows INT64,
  rejected_rows INT64,
  duplicate_rows INT64,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.staging.feedback_raw_metadata` (
  run_id STRING NOT NULL,
  feedback_id STRING NOT NULL,
  source_uri STRING,
  generation STRING,
  raw_object_key STRING,
  accepted BOOL,
  rejection_reason STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, accepted;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.curated.feedback_records` (
  run_id STRING NOT NULL,
  feedback_id STRING NOT NULL,
  source_feedback_id STRING,
  tenant_id STRING NOT NULL,
  submitted_at TIMESTAMP,
  source_type STRING,
  source_channel STRING,
  platform STRING,
  app_version STRING,
  language STRING,
  synthetic_customer_ref STRING,
  rating INT64,
  feedback_title STRING,
  feedback_text_redacted STRING NOT NULL,
  content_fingerprint STRING NOT NULL,
  is_synthetic BOOL,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY tenant_id, run_id, content_fingerprint;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.curated.feedback_quarantine` (
  run_id STRING NOT NULL,
  row_number INT64,
  source_feedback_id STRING,
  error_reason STRING NOT NULL,
  raw_json JSON,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, error_reason;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.extracted_insights` (
  insight_id STRING NOT NULL,
  run_id STRING NOT NULL,
  feedback_id STRING NOT NULL,
  sentence_index INT64,
  customer_intent STRING,
  aspect STRING,
  journey_node_id STRING,
  reported_problem STRING,
  reported_symptom STRING,
  sentiment STRING,
  sentiment_score FLOAT64,
  emotion STRING,
  customer_effort STRING,
  reported_outcome STRING,
  evidence_span STRING NOT NULL,
  language STRING,
  model_id STRING,
  prompt_version STRING,
  schema_version STRING,
  extraction_timestamp TIMESTAMP,
  extraction_method STRING,
  confidence FLOAT64,
  embedding ARRAY<FLOAT64>,
  is_problem BOOL
)
PARTITION BY DATE(extraction_timestamp)
CLUSTER BY run_id, is_problem, journey_node_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.customer_problems` (
  problem_id STRING NOT NULL,
  run_id STRING NOT NULL,
  signature STRING NOT NULL,
  title STRING NOT NULL,
  problem_statement STRING NOT NULL,
  customer_intent STRING,
  aspect STRING,
  symptom_category STRING,
  journey_node_id STRING,
  status STRING NOT NULL,
  lifecycle_status STRING NOT NULL,
  evidence_count INT64,
  distinct_customers INT64,
  negative_count INT64,
  first_seen TIMESTAMP,
  last_seen TIMESTAMP,
  cluster_id STRING,
  model_version STRING,
  taxonomy_version STRING,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, journey_node_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_evidence` (
  problem_id STRING NOT NULL,
  run_id STRING NOT NULL,
  insight_id STRING,
  feedback_id STRING NOT NULL,
  evidence_span STRING NOT NULL,
  submitted_at TIMESTAMP,
  source_type STRING,
  source_channel STRING,
  platform STRING,
  rating INT64,
  synthetic_customer_ref STRING,
  weight FLOAT64,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, problem_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_clusters` (
  cluster_id STRING NOT NULL,
  run_id STRING NOT NULL,
  label STRING,
  description STRING,
  algorithm STRING,
  params_json JSON,
  model_version STRING,
  member_count INT64,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, cluster_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.taxonomy.taxonomy_nodes` (
  node_id STRING NOT NULL,
  version STRING NOT NULL,
  parent_id STRING,
  node_type STRING NOT NULL,
  display_name STRING NOT NULL,
  description STRING,
  synonyms_json JSON,
  status STRING,
  aliases_json JSON,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY version, node_type;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.taxonomy.problem_mappings` (
  mapping_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  node_id STRING NOT NULL,
  mapping_type STRING NOT NULL,
  confidence FLOAT64,
  rationale STRING,
  status STRING,
  taxonomy_version STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY problem_id, node_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.taxonomy.taxonomy_proposals` (
  proposal_id STRING NOT NULL,
  run_id STRING NOT NULL,
  problem_id STRING,
  suggested_name STRING NOT NULL,
  parent_candidate STRING,
  description STRING,
  example_evidence STRING,
  reason STRING,
  status STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.backlog.backlog_uploads` (
  upload_id STRING NOT NULL,
  tenant_id STRING NOT NULL,
  filename STRING,
  object_key STRING,
  source_uri STRING,
  generation STRING,
  sha256 STRING,
  size_bytes INT64,
  status STRING NOT NULL,
  total_rows INT64,
  valid_rows INT64,
  invalid_rows INT64,
  errors_json JSON,
  warnings_json JSON,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY tenant_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.backlog.backlog_items` (
  item_pk STRING NOT NULL,
  upload_id STRING NOT NULL,
  backlog_id STRING NOT NULL,
  row_number INT64,
  title STRING NOT NULL,
  description STRING NOT NULL,
  acceptance_criteria STRING,
  product_area STRING,
  priority STRING,
  business_goal STRING,
  source_system STRING,
  structured_json JSON,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY upload_id, backlog_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.validation.validation_runs` (
  run_id STRING NOT NULL,
  upload_id STRING NOT NULL,
  status STRING NOT NULL,
  stage_json JSON,
  report_id STRING,
  error STRING,
  created_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP
)
PARTITION BY DATE(created_at)
CLUSTER BY upload_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.validation.validation_reports` (
  report_id STRING NOT NULL,
  upload_id STRING NOT NULL,
  run_id STRING NOT NULL,
  summary_json JSON,
  report_json JSON,
  reviewer_status STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY upload_id, reviewer_status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.validation.validation_findings` (
  finding_id STRING NOT NULL,
  report_id STRING NOT NULL,
  backlog_id STRING NOT NULL,
  problem_id STRING,
  relationship STRING NOT NULL,
  rationale STRING,
  alignment_score FLOAT64,
  supporting_feedback_count INT64,
  evidence_json JSON,
  journey_node_id STRING,
  ac_coverage FLOAT64,
  ac_gaps_json JSON,
  uncertainty STRING
)
CLUSTER BY report_id, relationship, journey_node_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.review_decisions` (
  entity_type STRING NOT NULL,
  entity_id STRING NOT NULL,
  reviewer STRING NOT NULL,
  decision STRING NOT NULL,
  note STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY entity_type, entity_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.report_reviews` (
  report_id STRING NOT NULL,
  backlog_id STRING,
  reviewer STRING NOT NULL,
  decision STRING NOT NULL,
  note STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY report_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.audit_log` (
  actor STRING NOT NULL,
  action STRING NOT NULL,
  entity_type STRING,
  entity_id STRING,
  detail_json JSON,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY entity_type, action;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.app_meta` (
  key STRING NOT NULL,
  value STRING,
  updated_at TIMESTAMP
);
