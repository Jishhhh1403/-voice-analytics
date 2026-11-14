-- Deterministic factor evidence prioritisation tables for BigQuery.
-- Replace ${PROJECT_ID} before running, or run through scripts/gcp_deploy.sh.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.factor_prioritisation_runs` (
  prioritisation_run_id STRING NOT NULL,
  famd_run_id STRING NOT NULL,
  feedback_run_id STRING,
  feature_schema_version STRING,
  scoring_model_version STRING NOT NULL,
  weight_configuration_json JSON NOT NULL,
  membership_rule_version STRING NOT NULL,
  representation_rule_version STRING NOT NULL,
  semantic_rule_version STRING NOT NULL,
  status STRING NOT NULL,
  stage STRING,
  total_factor_count INT64 NOT NULL,
  eligible_factor_count INT64 NOT NULL,
  provisional_factor_count INT64 NOT NULL,
  excluded_factor_count INT64 NOT NULL,
  summary_json JSON,
  error STRING,
  created_at TIMESTAMP NOT NULL,
  started_at TIMESTAMP,
  completed_at TIMESTAMP
)
CLUSTER BY famd_run_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.factor_prioritisation_scores` (
  prioritisation_run_id STRING NOT NULL,
  factor_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  dimension_number INT64,
  factor_name STRING,
  prevalence_score FLOAT64,
  statistical_importance_score FLOAT64,
  representation_strength_score FLOAT64,
  semantic_coherence_score FLOAT64,
  final_priority_score FLOAT64,
  evidence_coverage FLOAT64,
  eligibility_status STRING NOT NULL,
  score_status STRING NOT NULL,
  rank INT64,
  weights_json JSON,
  explanation_json JSON,
  calculated_at TIMESTAMP NOT NULL
)
CLUSTER BY prioritisation_run_id, rank;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.factor_prioritisation_evidence` (
  prioritisation_run_id STRING NOT NULL,
  factor_id STRING NOT NULL,
  component_name STRING NOT NULL,
  component_label STRING NOT NULL,
  component_weight FLOAT64,
  component_score FLOAT64,
  weighted_contribution FLOAT64,
  raw_value_json JSON,
  normalised_value FLOAT64,
  calculation_method STRING NOT NULL,
  rule_version STRING NOT NULL,
  source_table STRING,
  assessment_status STRING NOT NULL,
  explanation STRING NOT NULL,
  evidence_reference_json JSON,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY prioritisation_run_id, factor_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.factor_semantic_assessments` (
  assessment_id STRING NOT NULL,
  prioritisation_run_id STRING NOT NULL,
  factor_id STRING NOT NULL,
  famd_run_id STRING NOT NULL,
  semantic_evaluation_json JSON NOT NULL,
  supporting_problem_ids_json JSON,
  contradictory_problem_ids_json JSON,
  assessment_status STRING NOT NULL,
  coverage FLOAT64,
  reviewer_id STRING,
  review_status STRING NOT NULL,
  review_note STRING,
  reviewed_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL
)
CLUSTER BY prioritisation_run_id, factor_id;
