-- Signed FAMD coefficients, factor metadata and equations for the BigQuery target.
-- Replace ${PROJECT_ID} before running, or run through scripts/gcp_deploy.sh.

ALTER TABLE `${PROJECT_ID}.intelligence.dimension_analysis_runs`
  ADD COLUMN IF NOT EXISTS selected_features_json JSON,
  ADD COLUMN IF NOT EXISTS excluded_features_json JSON,
  ADD COLUMN IF NOT EXISTS configuration_json JSON;

ALTER TABLE `${PROJECT_ID}.intelligence.problem_dimension_scores`
  ADD COLUMN IF NOT EXISTS relative_squared_coordinate_share_pct FLOAT64,
  ADD COLUMN IF NOT EXISTS coordinate_rank INT64;

ALTER TABLE `${PROJECT_ID}.intelligence.dimension_definitions`
  ADD COLUMN IF NOT EXISTS dimension_number INT64,
  ADD COLUMN IF NOT EXISTS proposed_label STRING,
  ADD COLUMN IF NOT EXISTS business_interpretation STRING,
  ADD COLUMN IF NOT EXISTS interpretation_status STRING,
  ADD COLUMN IF NOT EXISTS model_version STRING;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_dimension_equations` (
  run_id STRING NOT NULL,
  canonical_problem_id STRING NOT NULL,
  equation_text STRING NOT NULL,
  number_of_dimensions INT64 NOT NULL,
  coefficient_representation_json JSON,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY run_id, canonical_problem_id;
