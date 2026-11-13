-- FAMD problem-dimension tables for the BigQuery target.
-- Replace ${PROJECT_ID} before running, or run through scripts/gcp_deploy.sh.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_feature_snapshots` (
  snapshot_id STRING NOT NULL,
  feedback_run_id STRING NOT NULL,
  canonical_problem_id STRING NOT NULL,
  as_of_date TIMESTAMP NOT NULL,
  feature_schema_version STRING NOT NULL,
  feature_values_json JSON NOT NULL,
  feature_types_json JSON,
  source_measurement_ids_json JSON,
  quality_flags_json JSON,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY feedback_run_id, canonical_problem_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.dimension_analysis_runs` (
  run_id STRING NOT NULL,
  method STRING NOT NULL,
  method_version STRING NOT NULL,
  method_library_version STRING,
  input_snapshot_id STRING,
  feedback_run_id STRING,
  feature_schema_version STRING NOT NULL,
  parameters_json JSON,
  status STRING NOT NULL,
  stage STRING,
  diagnostics_json JSON,
  feature_quality_json JSON,
  feature_dictionary_json JSON,
  code_version STRING,
  created_at TIMESTAMP NOT NULL,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  error STRING
)
PARTITION BY DATE(created_at)
CLUSTER BY feedback_run_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_dimension_scores` (
  run_id STRING NOT NULL,
  canonical_problem_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  coordinate FLOAT64 NOT NULL,
  contribution_metadata_json JSON,
  score_status STRING NOT NULL
)
CLUSTER BY run_id, canonical_problem_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.dimension_definitions` (
  run_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  analyst_name STRING NOT NULL,
  description STRING,
  top_variables_json JSON,
  representative_problem_ids_json JSON,
  review_status STRING NOT NULL,
  reviewer STRING,
  review_note STRING,
  reviewed_at TIMESTAMP
)
CLUSTER BY run_id, review_status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.dimension_variable_contributions` (
  run_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  variable_name STRING NOT NULL,
  category_level STRING,
  contribution FLOAT64 NOT NULL,
  coordinate FLOAT64,
  direction_summary STRING,
  rank INT64
)
CLUSTER BY run_id, dimension_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.dimension_problem_membership` (
  run_id STRING NOT NULL,
  canonical_problem_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  membership_type STRING NOT NULL,
  score FLOAT64 NOT NULL,
  margin FLOAT64,
  is_ambiguous BOOL NOT NULL
)
CLUSTER BY run_id, dimension_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.dimension_trends` (
  run_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  time_window STRING NOT NULL,
  metric_name STRING NOT NULL,
  metric_value FLOAT64,
  denominator FLOAT64,
  status STRING NOT NULL
)
CLUSTER BY run_id, dimension_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.dimension_publications` (
  publication_id STRING NOT NULL,
  run_id STRING NOT NULL,
  action STRING NOT NULL,
  published_by STRING NOT NULL,
  note STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, action;
