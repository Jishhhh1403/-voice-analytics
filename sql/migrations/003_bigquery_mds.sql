-- MDS theme-map tables for the BigQuery target.
-- Replace ${PROJECT_ID} before running, or run through scripts/gcp_deploy.sh.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_theme_vectors` (
  run_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  model_name STRING NOT NULL,
  dimensions INT64 NOT NULL,
  vector_json STRING NOT NULL,
  source STRING NOT NULL,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, problem_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_mds_runs` (
  mds_id STRING NOT NULL,
  run_id STRING NOT NULL,
  status STRING NOT NULL,
  methodology_version STRING NOT NULL,
  embedding_model STRING,
  distance_metric STRING NOT NULL,
  n_themes INT64 NOT NULL,
  stress FLOAT64,
  normalized_stress FLOAT64,
  stress_status STRING,
  params_json JSON,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY run_id, status;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_mds_points` (
  mds_id STRING NOT NULL,
  run_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  x FLOAT64 NOT NULL,
  y FLOAT64 NOT NULL,
  display_x FLOAT64 NOT NULL,
  display_y FLOAT64 NOT NULL,
  vector_source STRING,
  metadata_json JSON
)
CLUSTER BY run_id, problem_id;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.intelligence.problem_mds_neighbors` (
  mds_id STRING NOT NULL,
  run_id STRING NOT NULL,
  problem_id STRING NOT NULL,
  neighbor_problem_id STRING NOT NULL,
  rank INT64 NOT NULL,
  cosine_similarity FLOAT64 NOT NULL,
  cosine_distance FLOAT64 NOT NULL
)
CLUSTER BY run_id, problem_id;
