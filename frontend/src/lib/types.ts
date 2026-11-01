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

export type Evidence = {
  feedback_id: string;
  evidence_span: string;
  submitted_at?: string;
  source_type?: string;
  source_channel?: string;
  platform?: string;
  rating?: number | null;
  synthetic_customer_ref?: string | null;
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
      ac_coverage: number;
      ac_gap_count: number;
      findings: Finding[];
      customer_evidence_alignment_note: string;
    }[];
    findings: Finding[];
    uncovered_high_evidence_problems: {
      problem_id: string;
      title: string;
      problem_statement: string;
      journey_name?: string;
      evidence_count: number;
      distinct_customers: number;
      last_seen?: string;
    }[];
    versions: Record<string, string>;
    limitations: string[];
  };
  reviews: { reviewer: string; decision: string; note: string; created_at: string }[];
};
