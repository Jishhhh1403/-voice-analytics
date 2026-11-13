-- Problem portfolio serialization, narrative and validation tables for BigQuery.
-- Replace ${PROJECT_ID} before running, or run through scripts/gcp_deploy.sh.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_portfolio_analysis_runs` (
  run_id STRING NOT NULL,
  feedback_run_id STRING NOT NULL,
  dimension_run_id STRING NOT NULL,
  mds_id STRING,
  status STRING NOT NULL,
  stage STRING,
  serialization_version STRING NOT NULL,
  narrative_model STRING,
  prompt_version STRING,
  parameters_json JSON,
  summary_json JSON,
  error STRING,
  created_at TIMESTAMP NOT NULL,
  started_at TIMESTAMP,
  completed_at TIMESTAMP
)
CLUSTER BY feedback_run_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_factor_nomenclature` (
  run_id STRING NOT NULL,
  factor_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  dimension_number INT64,
  business_name STRING NOT NULL,
  description STRING,
  review_status STRING NOT NULL,
  source STRING NOT NULL,
  provisional BOOL NOT NULL,
  aliases_json JSON,
  top_variables_json JSON,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY run_id, factor_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_factor_profiles` (
  run_id STRING NOT NULL,
  factor_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  dimension_number INT64,
  eigenvalue FLOAT64,
  explained_variance FLOAT64,
  cumulative_variance FLOAT64,
  problem_count INT64 NOT NULL,
  problem_share_pct FLOAT64,
  mean_abs_coefficient FLOAT64,
  max_abs_coefficient FLOAT64,
  top_variables_json JSON,
  top_categories_json JSON,
  representative_problem_ids_json JSON,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY run_id, factor_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_mds_relationships` (
  run_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  neighbor_problem_id STRING NOT NULL,
  rank INT64 NOT NULL,
  euclidean_distance FLOAT64 NOT NULL,
  distance_space STRING NOT NULL,
  neighbor_title STRING,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY run_id, problem_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_portfolio_serializations` (
  serialization_id STRING NOT NULL,
  run_id STRING NOT NULL,
  schema_version STRING NOT NULL,
  content_hash STRING NOT NULL,
  payload_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY run_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_portfolio_narratives` (
  narrative_id STRING NOT NULL,
  run_id STRING NOT NULL,
  serialization_id STRING NOT NULL,
  provider STRING NOT NULL,
  model_id STRING,
  prompt_version STRING NOT NULL,
  status STRING NOT NULL,
  narrative_json JSON,
  generation_attempts INT64 NOT NULL,
  error STRING,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY run_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_narrative_validation` (
  validation_id STRING NOT NULL,
  run_id STRING NOT NULL,
  narrative_id STRING NOT NULL,
  status STRING NOT NULL,
  checks_json JSON NOT NULL,
  errors_json JSON NOT NULL,
  warnings_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY run_id, narrative_id;
