-- Migration 002: Modules A-G enhancements, measurement and prioritisation.
-- Replace ${PROJECT_ID} before running. Datasets are created by Terraform.
--
-- BigQuery supports ADD COLUMN IF NOT EXISTS; columns added here mirror the
-- additive SQLite migrations so local and cloud schemas stay aligned.

-- ---------------------------------------------------------------- Module A
ALTER TABLE `${PROJECT_ID}.curated.feedback_records` ADD COLUMN IF NOT EXISTS feedback_text_original STRING;
ALTER TABLE `${PROJECT_ID}.curated.feedback_records` ADD COLUMN IF NOT EXISTS language_confidence FLOAT64;
ALTER TABLE `${PROJECT_ID}.curated.feedback_records` ADD COLUMN IF NOT EXISTS duplicate_group_id STRING;
ALTER TABLE `${PROJECT_ID}.curated.feedback_records` ADD COLUMN IF NOT EXISTS duplicate_type STRING;
ALTER TABLE `${PROJECT_ID}.curated.feedback_records` ADD COLUMN IF NOT EXISTS quality_flags_json JSON;
ALTER TABLE `${PROJECT_ID}.curated.feedback_records` ADD COLUMN IF NOT EXISTS pii_types_json JSON;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.curated.feedback_duplicate_candidates` (
  candidate_id STRING NOT NULL,
  run_id STRING NOT NULL,
  feedback_id STRING NOT NULL,
  candidate_feedback_id STRING,
  duplicate_type STRING NOT NULL,
  similarity FLOAT64,
  customer_ref STRING,
  detected_at TIMESTAMP NOT NULL,
  metadata_json JSON
)
PARTITION BY DATE(detected_at)
CLUSTER BY run_id, duplicate_type;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.data_quality_reports` (
  run_id STRING NOT NULL,
  check_name STRING NOT NULL,
  status STRING NOT NULL,
  severity STRING NOT NULL,
  affected_rows INT64,
  detail_json JSON,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, status;

-- ---------------------------------------------------------------- Module B
ALTER TABLE `${PROJECT_ID}.intelligence.extracted_insights` ADD COLUMN IF NOT EXISTS intents_json JSON;
ALTER TABLE `${PROJECT_ID}.intelligence.extracted_insights` ADD COLUMN IF NOT EXISTS aspects_json JSON;
ALTER TABLE `${PROJECT_ID}.intelligence.extracted_insights` ADD COLUMN IF NOT EXISTS technical_root_cause STRING DEFAULT 'unknown';
ALTER TABLE `${PROJECT_ID}.intelligence.extracted_insights` ADD COLUMN IF NOT EXISTS evidence_verified BOOL;
ALTER TABLE `${PROJECT_ID}.intelligence.extracted_insights` ADD COLUMN IF NOT EXISTS field_confidence_json JSON;
ALTER TABLE `${PROJECT_ID}.intelligence.extracted_insights` ADD COLUMN IF NOT EXISTS human_review_status STRING DEFAULT 'unreviewed';
ALTER TABLE `${PROJECT_ID}.intelligence.extracted_insights` ADD COLUMN IF NOT EXISTS cluster_id STRING;

-- ---------------------------------------------------------------- Module C/D
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS canonical_description STRING;
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS validation_status STRING DEFAULT 'candidate';
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS human_review_status STRING DEFAULT 'unreviewed';
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS discovery_confidence FLOAT64;
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS embedding_ref STRING;
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS model_metadata_json JSON;
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS symptoms_json JSON;
ALTER TABLE `${PROJECT_ID}.intelligence.customer_problems` ADD COLUMN IF NOT EXISTS parent_problem_id STRING;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_relationships` (
  relationship_id STRING NOT NULL,
  run_id STRING NOT NULL,
  source_problem_id STRING NOT NULL,
  target_problem_id STRING NOT NULL,
  relationship_type STRING NOT NULL,
  confidence FLOAT64,
  status STRING DEFAULT 'candidate',
  rationale STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, relationship_type;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_symptoms` (
  problem_id STRING NOT NULL,
  symptom_key STRING,
  symptom_label STRING NOT NULL,
  symptom_category STRING,
  confidence FLOAT64,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY problem_id, symptom_category;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.taxonomy.problem_journey_mappings` (
  mapping_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  module_id STRING,
  feature_id STRING,
  journey_stage_id STRING,
  mapping_confidence FLOAT64,
  explanation STRING,
  status STRING DEFAULT 'candidate',
  taxonomy_version STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY problem_id, taxonomy_version;

-- ---------------------------------------------------------------- Module E
CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_metrics_daily` (
  run_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  day DATE NOT NULL,
  metric_name STRING NOT NULL,
  metric_value FLOAT64,
  unit STRING,
  status STRING NOT NULL,
  methodology_version STRING
)
PARTITION BY day
CLUSTER BY run_id, problem_id, metric_name;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_measurement_snapshots` (
  snapshot_id STRING NOT NULL,
  run_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  metric_name STRING NOT NULL,
  metric_value FLOAT64,
  metric_text_value STRING,
  unit STRING,
  status STRING NOT NULL,
  calculation_method STRING,
  measurement_window_start TIMESTAMP,
  measurement_window_end TIMESTAMP,
  input_record_count INT64,
  source_availability STRING,
  quality_indicator FLOAT64,
  calculated_at TIMESTAMP NOT NULL,
  methodology_version STRING,
  dimensions_json JSON,
  metadata_json JSON
)
PARTITION BY DATE(calculated_at)
CLUSTER BY run_id, problem_id, metric_name;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_priority_snapshots` (
  snapshot_id STRING NOT NULL,
  run_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  customer_impact_score FLOAT64,
  business_risk_score FLOAT64,
  operational_impact_score FLOAT64,
  trend_score FLOAT64,
  strategic_score FLOAT64,
  priority_score FLOAT64,
  rank INT64,
  escalation_status STRING NOT NULL,
  escalation_reasons_json JSON,
  missing_metrics_json JSON,
  supporting_evidence_json JSON,
  methodology_version STRING NOT NULL,
  measurement_window_start TIMESTAMP,
  measurement_window_end TIMESTAMP,
  calculated_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(calculated_at)
CLUSTER BY run_id, escalation_status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.scoring_methodology_versions` (
  version STRING NOT NULL,
  description STRING,
  weights_json JSON,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.model_execution_history` (
  execution_id STRING NOT NULL,
  run_id STRING NOT NULL,
  stage STRING NOT NULL,
  provider STRING,
  model_id STRING,
  prompt_version STRING,
  input_count INT64,
  output_count INT64,
  status STRING NOT NULL,
  error STRING,
  metadata_json JSON,
  started_at TIMESTAMP,
  finished_at TIMESTAMP
)
PARTITION BY DATE(started_at)
CLUSTER BY run_id, stage, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.ops.human_review_decisions` (
  decision_id STRING NOT NULL,
  entity_type STRING NOT NULL,
  entity_id STRING NOT NULL,
  reviewer STRING NOT NULL,
  decision STRING NOT NULL,
  note STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY entity_type, decision;

-- ---------------------------------------------------------------- Module F/G
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS intended_outcome STRING;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS customer_intent STRING;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS target_feature STRING;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS target_journey STRING;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS functional_scope STRING;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS organisational_objective STRING;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS profile_json JSON;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS extraction_provider STRING;
ALTER TABLE `${PROJECT_ID}.backlog.backlog_items` ADD COLUMN IF NOT EXISTS model_version STRING;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.validation.backlog_problem_candidates` (
  candidate_id STRING NOT NULL,
  report_id STRING,
  validation_run_id STRING,
  backlog_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  dense_score FLOAT64,
  sparse_score FLOAT64,
  fused_score FLOAT64,
  rerank_score FLOAT64,
  rank INT64,
  reasons_json JSON,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY report_id, backlog_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.validation.backlog_coverage_matrix` (
  report_id STRING NOT NULL,
  backlog_id STRING NOT NULL,
  problem_id STRING,
  relationship STRING NOT NULL,
  coverage_type STRING NOT NULL,
  alignment_score FLOAT64,
  priority_score FLOAT64,
  priority_rank INT64,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY report_id, coverage_type;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.survival_analysis_results` (
  result_id STRING NOT NULL,
  run_id STRING NOT NULL,
  problem_id STRING,
  event_type STRING NOT NULL,
  status STRING NOT NULL,
  estimate_json JSON,
  assumptions_json JSON,
  calculated_at TIMESTAMP NOT NULL,
  methodology_version STRING
)
PARTITION BY DATE(calculated_at)
CLUSTER BY run_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.conjoint_analysis_results` (
  result_id STRING NOT NULL,
  run_id STRING NOT NULL,
  problem_id STRING,
  status STRING NOT NULL,
  attribute_importance_json JSON,
  part_worth_json JSON,
  assumptions_json JSON,
  calculated_at TIMESTAMP NOT NULL,
  methodology_version STRING
)
PARTITION BY DATE(calculated_at)
CLUSTER BY run_id, status;
