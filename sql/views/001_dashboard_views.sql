-- Dashboard-facing views. Replace ${PROJECT_ID} or render through scripts/gcp_deploy.sh.

CREATE OR REPLACE VIEW `${PROJECT_ID}.intelligence.v_problem_overview` AS
SELECT
  p.run_id,
  p.problem_id,
  p.title,
  p.problem_statement,
  p.journey_node_id,
  p.symptom_category,
  p.lifecycle_status,
  p.evidence_count,
  p.distinct_customers,
  p.negative_count,
  p.first_seen,
  p.last_seen,
  p.taxonomy_version
FROM `${PROJECT_ID}.intelligence.customer_problems` AS p;

CREATE OR REPLACE VIEW `${PROJECT_ID}.intelligence.v_journey_summary` AS
SELECT
  run_id,
  COALESCE(journey_node_id, 'unmapped') AS journey_node_id,
  COUNT(*) AS problem_count,
  SUM(evidence_count) AS evidence_count,
  SUM(distinct_customers) AS distinct_customer_mentions
FROM `${PROJECT_ID}.intelligence.customer_problems`
GROUP BY run_id, journey_node_id;

CREATE OR REPLACE VIEW `${PROJECT_ID}.intelligence.v_sentiment_daily` AS
SELECT
  run_id,
  DATE(extraction_timestamp) AS day,
  sentiment,
  COUNT(*) AS insight_count
FROM `${PROJECT_ID}.intelligence.extracted_insights`
WHERE extraction_timestamp IS NOT NULL
GROUP BY run_id, day, sentiment;

CREATE OR REPLACE VIEW `${PROJECT_ID}.validation.v_report_findings` AS
SELECT
  r.report_id,
  r.run_id AS validation_run_id,
  r.upload_id,
  r.reviewer_status,
  f.backlog_id,
  f.problem_id,
  f.relationship,
  f.alignment_score,
  f.supporting_feedback_count,
  f.journey_node_id,
  f.ac_coverage,
  f.uncertainty
FROM `${PROJECT_ID}.validation.validation_reports` AS r
JOIN `${PROJECT_ID}.validation.validation_findings` AS f
  ON f.report_id = r.report_id;

CREATE OR REPLACE VIEW `${PROJECT_ID}.validation.v_relationship_distribution` AS
SELECT
  report_id,
  relationship,
  COUNT(*) AS finding_count,
  AVG(alignment_score) AS avg_alignment_score
FROM `${PROJECT_ID}.validation.validation_findings`
GROUP BY report_id, relationship;

CREATE OR REPLACE VIEW `${PROJECT_ID}.ops.v_run_health` AS
SELECT
  run_id,
  tenant_id,
  run_type,
  status,
  created_at,
  started_at,
  finished_at,
  TIMESTAMP_DIFF(finished_at, started_at, SECOND) AS duration_seconds,
  error
FROM `${PROJECT_ID}.ops.pipeline_runs`;

CREATE OR REPLACE VIEW `${PROJECT_ID}.intelligence.v_problem_theme_map` AS
SELECT
  m.run_id,
  m.problem_id,
  p.title,
  p.journey_node_id,
  p.lifecycle_status,
  m.x,
  m.y,
  m.display_x,
  m.display_y,
  ms.stress,
  ms.normalized_stress,
  ms.stress_status,
  ms.methodology_version
FROM `${PROJECT_ID}.intelligence.problem_mds_points` AS m
JOIN `${PROJECT_ID}.intelligence.problem_mds_runs` AS ms
  ON ms.mds_id = m.mds_id
LEFT JOIN `${PROJECT_ID}.intelligence.customer_problems` AS p
  ON p.problem_id = m.problem_id AND p.run_id = m.run_id;
