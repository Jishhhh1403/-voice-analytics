export type StageStatus = {
  stage: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  processed: number;
  succeeded: number;
  failed: number;
  message?: string | null;
  metrics: Record<string, unknown>;
};

export type PipelineRun = {
  run_id: string;
  tenant_id: string;
  run_type: string;
  status: string;
  input_uri?: string | null;
  input_generation?: string | null;
  source_filename?: string | null;
  code_version?: string | null;
  schema_version?: string | null;
  model_version?: string | null;
  taxonomy_version?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  correlation_id?: string | null;
  error?: string | null;
  summary: Record<string, unknown>;
  stages: StageStatus[];
  is_terminal?: boolean;
};

export type Summary = {
  run_id: string | null;
  latest_run?: Partial<PipelineRun> | null;
  total_feedback: number;
  total_insights: number;
  total_problems: number;
  unmapped_problems: number;
  synthetic: boolean;
  message?: string;
  trend: { period: string; total: number; low_rating: number }[];
  sentiment_by_journey: { journey_node_id: string; sentiment: string; total: number }[];
  top_problems: {
    problem_id: string;
    title: string;
    journey_node_id: string;
    symptom_category: string;
    evidence_count: number;
    distinct_customers: number;
    last_seen: string;
  }[];
  source_mix: { name: string; total: number }[];
  platform_mix: { name: string; total: number }[];
  rating_mix: { rating: string; total: number }[];
  journey_breakdown: { journey_node_id: string; problems: number; evidence: number }[];
};

export type ProblemListItem = {
  problem_id: string;
  title: string;
  problem_statement: string;
  canonical_description?: string | null;
  customer_intent?: string | null;
  aspect?: string | null;
  symptom_category?: string | null;
  journey_node_id?: string | null;
  journey_name?: string | null;
  lifecycle_status: string;
  evidence_count: number;
  distinct_customers: number;
  negative_count: number;
  first_seen?: string | null;
  last_seen?: string | null;
  cluster_id?: string | null;
};

export type EvidenceInsight = {
  feedback_id: string;
  insight_id: string;
  customer_intent?: string | null;
  aspect?: string | null;
  intents: string[];
  aspects: string[];
  reported_problem?: string | null;
  reported_symptom?: string | null;
  sentiment: string;
  sentiment_score?: number | null;
  emotion: string;
  customer_effort: string;
  reported_outcome: string;
  evidence_span: string;
  language?: string | null;
  technical_root_cause?: string | null;
  evidence_verified?: number | boolean | null;
  field_confidence: Record<string, number>;
  human_review_status?: string | null;
  confidence: number;
};

export type Evidence = {
  feedback_id: string;
  evidence_span: string;
  submitted_at?: string;
  source_type?: string;
  source_channel?: string;
  platform?: string;
  rating?: number | null;
  synthetic_customer_ref?: string | null;
  insights?: EvidenceInsight[];
};

export type MeasurementSnapshot = {
  snapshot_id: string;
  run_id: string;
  problem_id: string;
  metric_name: string;
  metric_value?: number | null;
  metric_text_value?: string | null;
  unit?: string | null;
  status: string;
  calculation_method?: string | null;
  measurement_window_start?: string | null;
  measurement_window_end?: string | null;
  input_record_count?: number;
  source_availability?: string | null;
  quality_indicator?: number | null;
  calculated_at?: string;
  methodology_version?: string | null;
  dimensions: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type ProblemMeasurement = {
  problem_id: string;
  snapshots: MeasurementSnapshot[];
  daily: { day: string; metric_name: string; metric_value: number; unit: string; status: string }[];
};

export type ProblemPriority = {
  snapshot_id: string;
  run_id: string;
  problem_id: string;
  customer_impact_score: number;
  business_risk_score: number;
  operational_impact_score: number;
  trend_score: number;
  strategic_score: number;
  priority_score: number;
  rank: number;
  escalation_status: string;
  escalation_reasons: string[];
  missing_metrics: string[];
  supporting_evidence: Record<string, unknown>;
  methodology_version: string;
  measurement_window_start?: string | null;
  measurement_window_end?: string | null;
  calculated_at: string;
};

export type ProblemDetail = ProblemListItem & {
  signature: string;
  model_version: string;
  taxonomy_version: string;
  mappings: {
    mapping_id: string;
    node_id: string;
    display_name?: string;
    mapping_type: string;
    confidence: number;
    rationale: string;
    status: string;
  }[];
  evidence: Evidence[];
  insights: {
    insight_id: string;
    customer_intent?: string;
    aspect?: string;
    reported_symptom?: string;
    sentiment: string;
    emotion: string;
    customer_effort: string;
    reported_outcome: string;
    confidence: number;
  }[];
  reviews: { reviewer: string; decision: string; note: string; created_at: string }[];
};

export type TaxonomyNode = {
  node_id: string;
  parent_id?: string | null;
  node_type: string;
  display_name: string;
  description?: string;
  synonyms?: string[];
  children: TaxonomyNode[];
};

export type JourneyNode = {
  node_id: string;
  parent_id?: string | null;
  node_type: string;
  display_name: string;
  description?: string;
  problem_count: number;
  evidence_count: number;
  children: JourneyNode[];
};

export type BacklogItem = {
  backlog_id: string;
  row_number: number;
  title: string;
  description: string;
  acceptance_criteria?: string;
  product_area?: string;
  priority?: string;
  business_goal?: string;
  source_system?: string;
};

export type BacklogUpload = {
  upload_id: string;
  tenant_id: string;
  filename: string;
  source_uri: string;
  generation: string;
  status: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  errors: { row_number: number; backlog_id?: string; errors: string[] }[];
  warnings: string[];
  items: BacklogItem[];
  validation_runs: { run_id: string; status: string; report_id?: string; created_at: string }[];
  created_at: string;
};

export type CoveredProblem = {
  problem_id: string;
  title?: string | null;
  problem_statement?: string | null;
  journey_name?: string | null;
  evidence_count?: number | null;
  distinct_customers?: number | null;
};

export type FactorCoverageEntry = {
  factor_id: string;
  factor_name: string;
  description?: string | null;
  priority_rank?: number | null;
  priority_score?: number | null;
  score_status?: string | null;
  eligibility_status?: string | null;
  supporting_problem_count: number;
  supporting_problems: CoveredProblem[];
  covered_by_count: number;
  covered_by_backlog_ids: string[];
  best_coverage: number;
  best_embedding_distance?: number | null;
  best_relationship?: string | null;
};

export type Finding = {
  finding_id: string;
  backlog_id: string;
  problem_id?: string | null;
  problem_title?: string | null;
  relationship: string;
  rationale: string;
  alignment_score: number;
  supporting_feedback_count: number;
  evidence: Evidence[];
  journey_node_id?: string | null;
  journey_name?: string | null;
  ac_coverage: number;
  ac_gaps: string[];
  uncertainty?: string | null;
  factor_id?: string | null;
  factor_name?: string | null;
  dimension_id?: string | null;
  factor_priority_rank?: number | null;
  factor_priority_score?: number | null;
  factor_score_status?: string | null;
  coverage?: number;
  coverage_pct?: number;
  embedding_similarity?: number;
  embedding_distance?: number;
  sparse_similarity?: number;
  lexical_similarity?: number;
  fused_similarity?: number;
  priority_weighted_coverage?: number;
  covered_problem_count?: number;
  covered_problems?: CoveredProblem[];
};

export type Report = {
  report_id: string;
  upload_id: string;
  run_id: string;
  filename?: string;
  reviewer_status: string;
  created_at: string;
  summary: Record<string, any>;
  report: {
    generated_at: string;
    feedback_run_id: string;
    validation_basis?: "factor_prioritisation" | "canonical_problems";
    prioritisation_run_id?: string;
    famd_run_id?: string;
    summary: Record<string, any>;
    backlog_items: {
      backlog_id: string;
      title: string;
      description: string;
      product_area?: string;
      priority?: string;
      business_goal: string;
      journey_node_id?: string;
      journey_name: string;
      overall_alignment: string;
      best_finding?: Finding | null;
      best_factor?: Finding | null;
      ac_coverage: number;
      ac_gap_count: number;
      findings: Finding[];
      customer_evidence_alignment_note: string;
      backlog_priority_rank?: number;
      priority_alignment_score?: number;
      priority_alignment_pct?: number;
      covered_factor_count?: number;
      covered_factor_ids?: string[];
      highest_priority_factor_rank?: number | null;
      covered_problem_count?: number;
      covered_problem_ids?: string[];
      embedding_distance?: number | null;
      factor_coverage_pct?: number;
    }[];
    findings: Finding[];
    factor_coverage?: FactorCoverageEntry[];
    uncovered_high_priority_factors?: FactorCoverageEntry[];
    uncovered_high_evidence_problems: {
      problem_id: string;
      title: string;
      problem_statement: string;
      journey_name?: string;
      evidence_count: number;
      distinct_customers: number;
      last_seen?: string;
    }[];
    versions: Record<string, string | number | Record<string, unknown>>;
    limitations: string[];
  };
  reviews: { reviewer: string; decision: string; note: string; created_at: string }[];
};

export type ThemeMapNeighbor = {
  problem_id: string;
  title?: string | null;
  rank: number;
  cosine_similarity: number;
  cosine_distance: number;
};

export type ThemeMapTheme = {
  problem_id: string;
  title?: string | null;
  problem_statement?: string | null;
  canonical_description?: string | null;
  journey_node_id?: string | null;
  journey_name?: string | null;
  lifecycle_status?: string | null;
  human_review_status?: string | null;
  validation_status?: string | null;
  x: number;
  y: number;
  display_x: number;
  display_y: number;
  vector_source?: string | null;
  evidence_volume?: number | null;
  evidence_volume_status: string;
  distinct_customers?: number | null;
  distinct_customers_status: string;
  negative_share?: number | null;
  negative_share_status: string;
  repeat_complaint_count?: number | null;
  source_diversity?: number | null;
  volume_growth_pct?: number | null;
  volume_growth_pct_status: string;
  volume_growth_abs?: number | null;
  priority_score?: number | null;
  priority_rank?: number | null;
  escalation_status?: string | null;
  customer_impact_score?: number | null;
  business_risk_score?: number | null;
  operational_impact_score?: number | null;
  trend_score?: number | null;
  strategic_score?: number | null;
  coverage_status: string;
  coverage_relationship?: string | null;
  coverage_report_id?: string | null;
  neighbors: ThemeMapNeighbor[];
};

export type ThemeMapResponse = {
  run_id: string | null;
  status: string;
  methodology_version: string;
  embedding_model?: string | null;
  distance_metric: string;
  n_themes: number;
  stress?: number | null;
  normalized_stress?: number | null;
  stress_status?: string | null;
  params: Record<string, unknown>;
  axes: Record<string, string>;
  severity_basis: string;
  color_mode_default: string;
  coverage_summary: Record<string, number>;
  themes: ThemeMapTheme[];
  notes: string[];
};

export type DimensionVariableContribution = {
  run_id?: string;
  dimension_id?: string;
  variable_name: string;
  category_level?: string | null;
  contribution: number;
  coordinate?: number | null;
  direction_summary?: string | null;
  rank?: number | null;
};

export type DimensionDefinition = {
  run_id?: string;
  dimension_id: string;
  dimension_number?: number | null;
  analyst_name: string;
  proposed_label?: string | null;
  description?: string | null;
  business_interpretation?: string | null;
  interpretation_status?: string | null;
  model_version?: string | null;
  top_variables: DimensionVariableContribution[];
  representative_problem_ids: string[];
  review_status: string;
  reviewer?: string | null;
  review_note?: string | null;
  reviewed_at?: string | null;
};

export type DimensionQualityCheck = {
  name: string;
  status: string;
  severity: string;
  message: string;
  details: Record<string, unknown>;
};

export type DimensionFeature = {
  name: string;
  label: string;
  type: string;
  source: string;
  description: string;
  transform: string;
  missing_policy: string;
};

export type DimensionSummary = {
  dimension_id: string;
  dimension_number?: number | null;
  factor_id?: string | null;
  eigenvalue?: number | null;
  explained_variance?: number | null;
  cumulative_variance?: number | null;
};

export type DimensionStabilityComponent = {
  dimension_id: string;
  mean_abs_cosine?: number | null;
  min_abs_cosine?: number | null;
  iterations: number;
};

export type DimensionDiagnostics = {
  n_problems?: number;
  n_features?: number;
  fitted_components?: number;
  retained_components?: number;
  quality_summary?: { checks: number; pass: number; warn: number; fail: number };
  dimensions?: DimensionSummary[];
  eigenvalues?: number[];
  percentage_of_variance?: number[];
  cumulative_percentage_of_variance?: number[];
  total_inertia?: number | null;
  preprocessing_warnings?: string[];
  feature_build_notes?: string[];
  interpretation_warning?: string;
  stability?: {
    status: string;
    iterations?: number;
    successful_iterations?: number;
    note?: string;
    components?: DimensionStabilityComponent[];
  };
  efa?: { status: string; note?: string; n_factors?: number; factors?: { factor_id: string; loadings: { variable_name: string; loading: number }[] }[] };
  [key: string]: unknown;
};

export type DimensionRunSummary = {
  run_id: string;
  method: string;
  method_version: string;
  method_library_version?: string | null;
  input_snapshot_id?: string | null;
  feedback_run_id?: string | null;
  feature_schema_version: string;
  status: string;
  stage?: string | null;
  code_version?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
};

export type DimensionRun = DimensionRunSummary & {
  parameters: Record<string, unknown>;
  diagnostics: DimensionDiagnostics;
  feature_quality: DimensionQualityCheck[];
  feature_dictionary: DimensionFeature[];
  selected_features: { name: string; kind: string; role: string }[];
  excluded_features: string[];
  configuration: Record<string, unknown>;
  definitions: DimensionDefinition[];
};

export type DimensionStatus = {
  enabled: boolean;
  method: string;
  methodology_version: string;
  feature_schema_version: string;
  review_required: boolean;
  latest_published_run_id?: string | null;
  latest_published_at?: string | null;
  latest_runs: DimensionRunSummary[];
};

export type DimensionTopProblem = {
  problem_id: string;
  title: string;
  aspect?: string | null;
  symptom_category?: string | null;
  journey_node_id?: string | null;
  coordinate?: number | null;
};

export type DimensionTrend = {
  dimension_id: string;
  time_window: string;
  metric_name: string;
  metric_value?: number | null;
  denominator?: number | null;
  status: string;
};

export type DimensionPublication = {
  publication: {
    publication_id: string;
    run_id: string;
    action: string;
    published_by: string;
    note?: string | null;
    created_at: string;
  };
  run: DimensionRun;
};

export type DimensionDetail = {
  run_id: string;
  run_status: string;
  definition: DimensionDefinition;
  top_problems: DimensionTopProblem[];
  contributions: DimensionVariableContribution[];
  trends: DimensionTrend[];
};

export type ProblemDimensionScore = {
  run_id: string;
  canonical_problem_id: string;
  dimension_id: string;
  coordinate: number;
  relative_squared_coordinate_share_pct?: number | null;
  coordinate_rank?: number | null;
  score_status: string;
  contribution_metadata?: { row_contribution?: number | null; component_index?: number | null };
  analyst_name?: string | null;
  description?: string | null;
  review_status?: string | null;
  membership_type?: string | null;
  margin?: number | null;
  is_ambiguous?: number | boolean | null;
};

export type ProblemDimensions = {
  run_id: string;
  run_status: string;
  problem: {
    problem_id: string;
    title: string;
    aspect?: string | null;
    symptom_category?: string | null;
    journey_node_id?: string | null;
  };
  dominant_dimension?: ProblemDimensionScore | null;
  equation?: DimensionEquation | null;
  scores: ProblemDimensionScore[];
  ambiguous: boolean;
};

export type DimensionEquation = {
  run_id: string;
  canonical_problem_id: string;
  equation_text: string;
  number_of_dimensions: number;
  coefficient_representation: DimensionEquationCoefficient[];
  created_at?: string;
};

export type DimensionEquationCoefficient = {
  dimension_id: string;
  dimension_number?: number | null;
  factor_id: string;
  coefficient: number;
  relative_squared_coordinate_share_pct?: number | null;
  coordinate_rank?: number | null;
};

export type DimensionCoefficientRow = {
  problem_id: string;
  dimension_id: string;
  coefficient: number;
  relative_squared_coordinate_share_pct?: number | null;
  coordinate_rank?: number | null;
  dimension_number?: number | null;
  factor_name?: string | null;
  proposed_label?: string | null;
  factor_review_status?: string | null;
};

export type DimensionCoefficientMatrix = {
  run_id: string;
  run_status: string;
  dimensions: {
    dimension_id: string;
    dimension_number?: number | null;
    factor_id: string;
    factor_name?: string | null;
    proposed_label?: string | null;
    review_status?: string | null;
  }[];
  coefficients: DimensionCoefficientRow[];
  selected_features: { name: string; kind: string; role: string }[];
  excluded_features: string[];
  coefficient_type: string;
  share_definition: string;
  interpretation_warning: string;
};

export type FactorNarrativeFeature = {
  feature_name: string;
  feature_type: "variable" | "category";
  contribution_pct: number;
  direction_summary?: string | null;
};

export type FactorNarrative = {
  factor_id: string;
  dimension_id: string;
  name: string;
  short_name: string;
  description: string;
  business_interpretation: string;
  banking_domain: string;
  journey_scope?: string | null;
  core_customer_experience: string;
  problem_count: number;
  problem_share_pct: number;
  explained_variance_pct?: number | null;
  cumulative_variance_pct?: number | null;
  mean_coefficient: number;
  mean_abs_coefficient: number;
  min_coefficient: number;
  max_coefficient: number;
  max_abs_coefficient: number;
  top_features: FactorNarrativeFeature[];
  positive_problem_pattern: string;
  negative_problem_pattern: string;
  representative_problem_ids: string[];
  confidence: number;
  confidence_explanation: string;
};

export type FactorNarrativePayload = {
  status: string;
  reason?: string | null;
  summary?: string | null;
  taxonomy_version?: string | null;
  total_problems?: number | null;
  total_factors?: number | null;
  factors: FactorNarrative[];
};

export type DimensionNarrativeSerializationRecord = {
  serialization_id: string;
  run_id: string;
  status: string;
  prompt_version: string;
  agent_version?: string | null;
  model_name?: string | null;
  content_hash: string;
  payload: FactorNarrativePayload;
  error?: string | null;
  created_at: string;
};

export type DimensionNarrativeSerializationResponse = {
  run_id: string;
  available: boolean;
  prompt_version: string;
  serialization: DimensionNarrativeSerializationRecord | null;
};

export type DimensionProblemProfile = {
  run_id: string;
  run_status: string;
  problem_id: string;
  problem?: {
    problem_id: string;
    title: string;
    aspect?: string | null;
    symptom_category?: string | null;
    journey_node_id?: string | null;
  } | null;
  equation: DimensionEquation | null;
  coefficients: ProblemDimensionScore[];
};

export type PortfolioNarrativeEvidence = {
  problem_id?: string | null;
  factor_name?: string | null;
  metric_name?: string | null;
  note?: string | null;
};

export type PortfolioNarrativeFinding = {
  title: string;
  narrative: string;
  business_implication: string;
  confidence: "high" | "medium" | "low";
  evidence: PortfolioNarrativeEvidence[];
  limitations: string[];
};

export type PortfolioFactorInterpretation = {
  factor_name: string;
  interpretation: string;
  common_problem_patterns: string[];
  business_implication: string;
  confidence: "high" | "medium" | "low";
  evidence: PortfolioNarrativeEvidence[];
  limitations: string[];
};

export type PortfolioAction = {
  action: string;
  rationale: string;
  horizon: "now" | "next" | "later";
  evidence: PortfolioNarrativeEvidence[];
  limitations: string[];
};

export type PortfolioNarrative = {
  title: string;
  executive_summary: string;
  key_findings: PortfolioNarrativeFinding[];
  factor_interpretations: PortfolioFactorInterpretation[];
  recommended_actions: PortfolioAction[];
  data_limitations: string[];
  methodology_notes: string[];
};

export type PortfolioNarrativeRow = {
  narrative_id: string;
  run_id: string;
  serialization_id: string;
  provider: string;
  model_id?: string | null;
  prompt_version: string;
  status: string;
  narrative?: PortfolioNarrative | null;
  generation_attempts: number;
  error?: string | null;
  created_at: string;
};

export type PortfolioValidation = {
  validation_id: string;
  run_id: string;
  narrative_id: string;
  status: string;
  checks: { name: string; status: string; message?: string | null }[];
  errors: string[];
  warnings: string[];
  created_at: string;
};

export type PortfolioFactorNomenclature = {
  factor_id: string;
  dimension_id: string;
  dimension_number?: number | null;
  business_name: string;
  description?: string | null;
  review_status: string;
  provisional: boolean;
  aliases: string[];
  top_variables: DimensionVariableContribution[];
};

export type PortfolioFactorProfile = {
  factor_id: string;
  dimension_id: string;
  dimension_number?: number | null;
  eigenvalue?: number | null;
  explained_variance?: number | null;
  cumulative_variance?: number | null;
  problem_count: number;
  problem_share_pct?: number | null;
  mean_abs_coefficient?: number | null;
  max_abs_coefficient?: number | null;
  top_variables: DimensionVariableContribution[];
  top_categories: { variable_name: string; category_level?: string | null; contribution: number }[];
  representative_problem_ids: string[];
};

export type PortfolioUnavailableAttribute = {
  field: string;
  reason: string;
};

export type PortfolioSerializationRow = {
  serialization_id: string;
  run_id: string;
  schema_version: string;
  content_hash: string;
  payload: {
    source: {
      feedback_run_id: string;
      dimension_run_id: string;
      counts: {
        problems_in_run: number;
        problems_serialized: number;
        factors: number;
        factor_scores: number;
      };
    };
    availability: {
      available: string[];
      unavailable: PortfolioUnavailableAttribute[];
      missing_value_policy: string;
    };
    factor_nomenclature: PortfolioFactorNomenclature[];
    factor_profiles: PortfolioFactorProfile[];
    portfolio_summary: {
      priority_escalation_counts: Record<string, number>;
      coverage_counts: Record<string, number>;
      journey_module_counts: Record<string, number>;
      missing_measurement_counts: Record<string, number>;
      provisional_factor_names: string[];
    };
    problems: {
      problem_id: string;
      title?: string | null;
      journey?: { journey_node_id?: string | null; journey_name?: string | null };
      priority?: { priority_score?: number | null; rank?: number | null; escalation_status?: string | null } | null;
      factors: { factor_id: string; factor_name: string; dimension_id: string; coefficient: number; relative_squared_coordinate_share_pct?: number | null }[];
      measurements: Record<string, { value?: number | null; status: string; unit?: string | null }>;
    }[];
    data_quality: {
      warnings: string[];
      unavailable_attributes: PortfolioUnavailableAttribute[];
    };
    interpretation_constraints: string[];
  };
  created_at: string;
};

export type PortfolioRunSummary = {
  run_id: string;
  feedback_run_id: string;
  dimension_run_id: string;
  status: string;
  stage?: string | null;
  serialization_version: string;
  narrative_model?: string | null;
  prompt_version?: string | null;
  parameters: Record<string, unknown>;
  summary: {
    n_problems?: number;
    n_factors?: number;
    data_quality_warnings?: string[];
    [key: string]: unknown;
  };
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type PortfolioRun = PortfolioRunSummary & {
  serialization?: { serialization_id: string; schema_version: string; content_hash: string; created_at: string };
  narrative?: PortfolioNarrativeRow | null;
  validation?: PortfolioValidation | null;
  factor_nomenclature: PortfolioFactorNomenclature[];
  factor_profiles: PortfolioFactorProfile[];
};

export type PortfolioStatus = {
  enabled: boolean;
  provider: string;
  model?: string | null;
  provider_configured: boolean;
  serialization_version: string;
  prompt_version: string;
  require_approved_factors: boolean;
  latest_run_id?: string | null;
  latest_run_status?: string | null;
  latest_runs: PortfolioRunSummary[];
};

export type FactorPrioritisationComponent = {
  name: string;
  label: string;
  weight: number;
  score: number | null;
  weighted_contribution: number | null;
  assessment_status: string;
  calculation_method: string;
  rule_version: string;
  explanation: string;
  raw_value: Record<string, unknown>;
};

export type FactorPrioritisationExplanation = {
  factor_id: string;
  dimension_id: string;
  factor_name: string | null;
  headline: string;
  rank: number | null;
  formula: string;
  components: FactorPrioritisationComponent[];
  evidence_coverage_pct: number;
  assessed_components: string[];
  missing_components: string[];
  nomenclature_status: string;
  nomenclature_approved: boolean;
  why: string[];
  caveats: string[];
  nomenclature: {
    factor_name?: string | null;
    short_name?: string | null;
    description?: string | null;
    source?: string | null;
    serialization_id?: string | null;
    model_name?: string | null;
    prompt_version?: string | null;
  };
  validation_warnings: string[];
};

export type FactorPrioritisationScore = {
  prioritisation_run_id: string;
  factor_id: string;
  dimension_id: string;
  dimension_number?: number | null;
  factor_name: string | null;
  prevalence_score: number | null;
  statistical_importance_score: number | null;
  representation_strength_score: number | null;
  semantic_coherence_score: number | null;
  final_priority_score: number | null;
  evidence_coverage: number;
  eligibility_status: string;
  score_status: string;
  rank: number | null;
  weights: Record<string, number>;
  explanation: FactorPrioritisationExplanation;
  calculated_at: string;
};

export type FactorSemanticSubdimension = {
  label: string;
  score: number | null;
  status: string;
  problem_count: number;
  distinct_levels: number;
  dominant_level: string | null;
  dominant_share_pct: number | null;
  explanation: string;
  top_levels: { level: string; count: number; share_pct: number }[];
};

export type FactorSemanticAssessment = {
  assessment_id: string;
  prioritisation_run_id: string;
  factor_id: string;
  famd_run_id: string;
  semantic_evaluation: {
    subdimensions: Record<string, FactorSemanticSubdimension>;
    coverage_pct: number;
    assessed_dimensions: number;
    total_dimensions: number;
    rule: string;
    supporting_problem_ids: string[];
    contradictory_problem_ids: string[];
    nomenclature: Record<string, unknown>;
  };
  supporting_problem_ids: string[];
  contradictory_problem_ids: string[];
  assessment_status: string;
  coverage: number;
  reviewer_id?: string | null;
  review_status: string;
  review_note?: string | null;
  reviewed_at?: string | null;
  created_at: string;
};

export type FactorPrioritisationRunSummary = {
  prioritisation_run_id: string;
  famd_run_id: string;
  feedback_run_id?: string | null;
  feature_schema_version?: string | null;
  scoring_model_version: string;
  weight_configuration: Record<string, number>;
  membership_rule_version: string;
  representation_rule_version: string;
  semantic_rule_version: string;
  status: string;
  stage?: string | null;
  total_factor_count: number;
  eligible_factor_count: number;
  provisional_factor_count: number;
  excluded_factor_count: number;
  summary: {
    factor_count?: number;
    scored_factor_count?: number;
    validated_score_count?: number;
    provisional_score_count?: number;
    insufficient_score_count?: number;
    problems_analysed?: number;
    top_factor_id?: string | null;
    top_factor_name?: string | null;
    top_priority_score?: number | null;
    validation_warnings?: string[];
    [key: string]: unknown;
  };
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type FactorPrioritisationRun = FactorPrioritisationRunSummary & {
  scores: FactorPrioritisationScore[];
  semantic_assessments: FactorSemanticAssessment[];
};

export type FactorPrioritisationDetail = {
  score: FactorPrioritisationScore;
  evidence: {
    component_name: string;
    component_label: string;
    component_weight: number;
    component_score: number | null;
    weighted_contribution: number | null;
    raw_value: Record<string, unknown>;
    calculation_method: string;
    rule_version: string;
    source_table: string | null;
    assessment_status: string;
    explanation: string;
    evidence_reference: Record<string, unknown>;
  }[];
  semantic_assessment: FactorSemanticAssessment | null;
};

export type MappingFeedbackNode = {
  feedback_id: string;
  submitted_at?: string | null;
  source_type?: string | null;
  source_channel?: string | null;
  platform?: string | null;
  rating?: number | null;
  title: string;
  text: string;
  primary_theme_id?: string | null;
  primary_theme_order?: number;
  theme_count?: number;
};

export type MappingThemeNode = {
  problem_id: string;
  title: string;
  problem_statement: string;
  evidence_count?: number | null;
  distinct_customers?: number | null;
  negative_count?: number | null;
  journey_node_id?: string | null;
  journey_name?: string | null;
  lifecycle_status?: string | null;
  validation_status?: string | null;
  discovery_confidence?: number | null;
  primary_factor_id?: string | null;
  primary_factor_rank?: number;
  primary_factor_score?: number;
  mapped_feedback_count?: number;
};

export type MappingFactorNode = {
  factor_id: string;
  dimension_id: string;
  factor_name: string;
  rank: number;
  priority_score: number;
  score_status: string;
  eligibility_status: string;
  evidence_coverage: number;
};

export type MappingBacklogNode = {
  backlog_id: string;
  title: string;
  description?: string;
  product_area?: string | null;
  priority?: string | null;
  business_goal?: string | null;
  backlog_priority_rank?: number;
  overall_alignment?: string | null;
  priority_alignment_pct?: number | null;
  factor_coverage_pct?: number | null;
  covered_factor_count?: number;
  covered_factor_ids?: string[];
  covered_problem_count?: number;
  highest_priority_factor_rank?: number | null;
  best_factor_id?: string | null;
  best_relationship?: string | null;
};

export type MappingFeedbackThemeLink = {
  source: string;
  target: string;
  weight: number;
  evidence_count: number;
};

export type MappingThemeFactorLink = {
  source: string;
  target: string;
  score: number;
  margin: number;
  membership_type: string;
  is_ambiguous: boolean;
};

export type MappingFactorBacklogLink = {
  source: string;
  target: string;
  relationship?: string | null;
  coverage?: number | null;
  coverage_pct?: number | null;
  alignment_score?: number | null;
  embedding_distance?: number | null;
  priority_weighted_coverage?: number | null;
  supporting_feedback_count?: number | null;
  covered_problem_count?: number | null;
  problem_id?: string | null;
  problem_title?: string | null;
  rationale?: string | null;
};

export type MappingGraphCounts = {
  feedback_total: number;
  feedback_mapped: number;
  feedback_unmapped: number;
  themes: number;
  themes_with_factors: number;
  factors: number;
  backlogs: number;
  feedback_theme_links: number;
  theme_factor_links: number;
  factor_backlog_links: number;
};

export type MappingGraphResponse = {
  status: "READY" | "PARTIAL" | "NO_FEEDBACK_RUN" | "NO_THEMES";
  generated_at: string;
  feedback_run_id?: string | null;
  feedback_run_finished_at?: string | null;
  famd_run_id?: string | null;
  prioritisation_run_id?: string | null;
  report_id?: string | null;
  validation_run_id?: string | null;
  upload_id?: string | null;
  feedback: MappingFeedbackNode[];
  themes: MappingThemeNode[];
  factors: MappingFactorNode[];
  backlogs: MappingBacklogNode[];
  links: {
    feedback_theme: MappingFeedbackThemeLink[];
    theme_factor: MappingThemeFactorLink[];
    factor_backlog: MappingFactorBacklogLink[];
  };
  counts: MappingGraphCounts;
  warnings: string[];
  versions: Record<string, string | null | undefined>;
};

export type MappingNodeKind = "feedback" | "theme" | "factor" | "backlog";

export type MappingSelection = {
  kind: MappingNodeKind;
  id: string;
};

export type MappingFocusTarget = MappingSelection & {
  nonce: number;
};

export type MappingSearchResult = MappingSelection & {
  label: string;
  subtitle: string;
  score: number;
};
