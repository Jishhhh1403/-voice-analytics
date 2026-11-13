import {
  Activity,
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Layers3,
  Quote,
  ShieldCheck,
  Star,
  Target,
  UserRound,
} from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner } from "../components/ui";
import { postJSON } from "../lib/api";
import { date, dateTime, label, number } from "../lib/format";
import type {
  MeasurementSnapshot,
  ProblemDetail,
  ProblemDimensions,
  ProblemMeasurement,
  ProblemPriority,
} from "../lib/types";
import { useFetch } from "../lib/useFetch";

const METRIC_LABELS: Record<string, string> = {
  evidence_volume: "Evidence volume (90d)",
  evidence_volume_lifetime: "Evidence volume (lifetime)",
  evidence_volume_30d: "Evidence volume (30d)",
  evidence_volume_previous_30d: "Evidence volume (previous 30d)",
  distinct_customers: "Distinct customers (90d)",
  distinct_customers_lifetime: "Distinct customers (lifetime)",
  negative_share: "Negative share (90d)",
  negative_share_30d: "Negative share (30d)",
  negative_share_previous_30d: "Negative share (previous 30d)",
  negative_share_change: "Negative share change",
  repeat_complaint_count: "Repeat complaints (90d)",
  source_diversity: "Source diversity (90d)",
  volume_growth_abs: "Volume growth (absolute)",
  volume_growth_pct: "Volume growth (%)",
  customer_growth_abs: "Customer growth (absolute)",
  customer_growth_pct: "Customer growth (%)",
  assessment_velocity_delta: "Velocity vs baseline",
};

const PRIMARY_METRICS = new Set([
  "evidence_volume",
  "evidence_volume_lifetime",
  "evidence_volume_30d",
  "evidence_volume_previous_30d",
  "distinct_customers",
  "negative_share",
  "negative_share_30d",
  "negative_share_previous_30d",
  "negative_share_change",
  "repeat_complaint_count",
  "source_diversity",
  "volume_growth_abs",
  "volume_growth_pct",
  "assessment_velocity_delta",
]);

type RiskIndicator = { term: string; weight: number };

const PRIORITY_COMPONENTS = [
  ["customer_impact_score", "Customer impact"],
  ["business_risk_score", "Risk indicator"],
  ["operational_impact_score", "Operational impact"],
  ["trend_score", "Trend"],
  ["strategic_score", "Strategic fit"],
] as const;

function metricValue(metric: MeasurementSnapshot): string {
  if (metric.metric_value === null || metric.metric_value === undefined) return "NO_DATA";
  if (metric.unit === "ratio") {
    if (metric.metric_name === "negative_share_change") {
      return `${metric.metric_value > 0 ? "+" : ""}${Math.round(metric.metric_value * 100)} pp`;
    }
    return `${Math.round(metric.metric_value * 100)}%`;
  }
  if (metric.unit === "records" && (metric.metric_name.includes("growth") || metric.metric_name === "assessment_velocity_delta")) {
    return `${metric.metric_value > 0 ? "+" : ""}${metric.metric_value}`;
  }
  return `${number(metric.metric_value)}${metric.unit ? ` ${metric.unit}` : ""}`;
}

function coverageLabel(metric: MeasurementSnapshot): string {
  const coverage = metric.metadata?.window_coverage;
  return typeof coverage === "string" ? coverage : "unknown";
}

export default function ProblemDetailPage() {
  const { problemId } = useParams();
  const { data, loading, error, reload } = useFetch<ProblemDetail>(problemId ? `/problems/${problemId}` : null, [problemId]);
  const measurement = useFetch<ProblemMeasurement>(problemId ? `/problems/${problemId}/measurement` : null, [problemId]);
  const priority = useFetch<ProblemPriority>(problemId ? `/problems/${problemId}/priority` : null, [problemId]);
  const dimensions = useFetch<ProblemDimensions>(
    problemId ? `/problem-dimensions/latest/problems/${problemId}` : null,
    [problemId],
  );
  const [reviewer, setReviewer] = useState("journey-expert");
  const [decision, setDecision] = useState("accept");
  const [note, setNote] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!problemId) return;
    setSaving(true);
    setMessage(null);
    setReviewError(null);
    try {
      await postJSON(`/problems/${problemId}/review`, {
        reviewer,
        decision,
        note,
        new_title: decision === "rename" ? newTitle : undefined,
      });
      setMessage("Review recorded in the audit trail.");
      setNote("");
      reload();
    } catch (err) {
      setReviewError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) return <Spinner label="Loading problem evidence…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const snapshots = measurement.data?.snapshots ?? [];
  const primarySnapshots = snapshots.filter((metric) => PRIMARY_METRICS.has(metric.metric_name));
  const secondarySnapshots = snapshots.filter((metric) => !PRIMARY_METRICS.has(metric.metric_name));
  const derivedMetrics: MeasurementSnapshot[] =
    snapshots.length > 0
      ? primarySnapshots.length > 0
        ? primarySnapshots
        : snapshots
      : [
          {
            snapshot_id: "derived-evidence",
            run_id: "",
            problem_id: data.problem_id,
            metric_name: "evidence_volume",
            metric_value: data.evidence_count,
            unit: "records",
            status: "DERIVED",
            dimensions: {},
            metadata: {},
          },
          {
            snapshot_id: "derived-customers",
            run_id: "",
            problem_id: data.problem_id,
            metric_name: "distinct_customers",
            metric_value: data.distinct_customers,
            unit: "customers",
            status: "DERIVED",
            dimensions: {},
            metadata: {},
          },
          {
            snapshot_id: "derived-negative",
            run_id: "",
            problem_id: data.problem_id,
            metric_name: "negative_share",
            metric_value: data.evidence_count ? data.negative_count / data.evidence_count : null,
            unit: "ratio",
            status: "DERIVED",
            dimensions: {},
            metadata: {},
          },
        ];
  const priorityData = priority.data;
  const supporting = priorityData?.supporting_evidence ?? {};
  const riskIndicators = Array.isArray(supporting.risk_indicators)
    ? (supporting.risk_indicators as RiskIndicator[])
    : [];
  const verifiedRisk = (supporting.verified_risk ?? {}) as { status?: string };
  const dataCompleteness =
    typeof supporting.data_completeness === "number" ? supporting.data_completeness : null;
  const primaryMapping = data.mappings[0];

  return (
    <div className="page">
      <Link to="/problems" className="back-link">
        <ArrowLeft size={15} />
        Back to problem explorer
      </Link>
      <PageHeader
        eyebrow={`${data.problem_id} · ${data.cluster_id || "cluster"}`}
        title={data.title}
        subtitle={data.problem_statement}
        actions={
          <div className="header-badges">
            <Badge tone={data.lifecycle_status === "accepted" ? "green" : "amber"}>{label(data.lifecycle_status)}</Badge>
            <Badge tone="blue">{number(data.evidence_count)} evidence links</Badge>
          </div>
        }
      />

      <div className="grid grid-4">
        <div className="stat-card tone-accent">
          <span className="stat-label">Distinct customers</span>
          <div className="stat-value">{number(data.distinct_customers)}</div>
          <span className="stat-detail">Pseudonymous synthetic references</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Negative evidence</span>
          <div className="stat-value">{number(data.negative_count)}</div>
          <span className="stat-detail">Not a severity score</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">First seen</span>
          <div className="stat-value small">{date(data.first_seen)}</div>
          <span className="stat-detail">Latest {date(data.last_seen)}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Journey</span>
          <div className="stat-value small">{data.journey_name || data.journey_node_id || "UNMAPPED"}</div>
          <span className="stat-detail">Taxonomy v{data.taxonomy_version}</span>
        </div>
      </div>

      <Card
        title="Problem impact measurement"
        hint="Windowed metrics with explicit status and provenance. Missing coverage is not treated as zero."
        actions={
          priorityData ? (
            <Badge tone={priorityData.escalation_status === "ESCALATE" ? "red" : priorityData.escalation_status === "WATCH" ? "amber" : "green"}>
              {label(priorityData.escalation_status)}
            </Badge>
          ) : null
        }
      >
        <div className="impact-layout">
          <div className="impact-metrics">
            {derivedMetrics.map((metric) => (
              <div className="impact-metric" key={metric.metric_name}>
                <div className="impact-metric-head">
                  <span>{METRIC_LABELS[metric.metric_name] || label(metric.metric_name)}</span>
                  <Badge tone={metric.status === "OK" ? "green" : metric.status === "DERIVED" ? "blue" : "amber"}>
                    {metric.status}
                  </Badge>
                </div>
                <strong>{metricValue(metric)}</strong>
                <small>
                  {metric.measurement_window_start
                    ? `${date(metric.measurement_window_start)} to ${date(metric.measurement_window_end)}`
                    : "Directly derived from linked evidence"}
                </small>
                {snapshots.length > 0 && <small>Coverage: {coverageLabel(metric)}</small>}
              </div>
            ))}
          </div>

          <div className="impact-priority">
            {priorityData ? (
              <>
                <div className="priority-score-row">
                  <div>
                    <span>Priority score</span>
                    <strong>{Math.round(priorityData.priority_score * 100)}<small>/100</small></strong>
                  </div>
                  <div>
                    <span>Rank</span>
                    <strong>#{priorityData.rank}</strong>
                  </div>
                  <Target size={18} />
                </div>
                <div className="priority-components">
                  {PRIORITY_COMPONENTS.map(([key, componentLabel]) => {
                    const value = Number(priorityData[key] || 0);
                    return (
                      <div className="priority-component" key={key}>
                        <span>{componentLabel}</span>
                        <div className="priority-track">
                          <span style={{ width: `${Math.round(value * 100)}%` }} />
                        </div>
                        <strong>{Math.round(value * 100)}%</strong>
                      </div>
                    );
                  })}
                </div>
                <div className="risk-indicator-box">
                  <span>Risk indicators, not verified incidents</span>
                  {riskIndicators.length > 0 ? (
                    <div className="header-badges">
                      {riskIndicators.slice(0, 6).map((indicator) => (
                        <Badge key={indicator.term} tone="amber">
                          {label(indicator.term)}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <small>No configured risk terms detected in linked evidence.</small>
                  )}
                  <small>Verification: {label(verifiedRisk.status || "NOT_VERIFIED")}</small>
                  {dataCompleteness !== null && <small>Data completeness: {Math.round(dataCompleteness * 100)}%</small>}
                </div>
                <p className="footnote">
                  Weighted customer-evidence prioritisation, not an organisational approval. Business risk is an
                  indicator score until verified. Methodology {priorityData.methodology_version}.
                </p>
              </>
            ) : (
              <EmptyState
                title="Priority snapshot not calculated"
                detail="Priority is calculated during the feedback pipeline run. This run predates the measurement engine; re-run the pipeline to populate it."
              />
            )}
          </div>
        </div>
        {secondarySnapshots.length > 0 && (
          <details className="window-detail">
            <summary>All measurement windows ({secondarySnapshots.length})</summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Value</th>
                    <th>Status</th>
                    <th>Window</th>
                    <th>Coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {secondarySnapshots.map((metric) => (
                    <tr key={metric.metric_name}>
                      <td>{METRIC_LABELS[metric.metric_name] || label(metric.metric_name)}</td>
                      <td>{metricValue(metric)}</td>
                      <td>{metric.status}</td>
                      <td>
                        {metric.measurement_window_start
                          ? `${date(metric.measurement_window_start)} to ${date(metric.measurement_window_end)}`
                          : "Lifetime"}
                      </td>
                      <td>{coverageLabel(metric)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
        {snapshots.length === 0 && (
          <p className="footnote">
            Showing directly derived counts from this problem’s linked evidence. Windowed snapshots such as repeat
            complaints, source diversity and velocity require a fresh pipeline run.
          </p>
        )}
        {(measurement.error || priority.error) && snapshots.length === 0 && (
          <p className="footnote">Measurement endpoints returned no snapshot for this run.</p>
        )}
      </Card>

      {dimensions.data && dimensions.data.scores.length > 0 && (
        <Card
          title="Experience dimensions"
          hint="Published FAMD pattern associations. These are exploratory dimensions, not proven root causes."
          actions={<Badge tone="violet">Published run</Badge>}
        >
          <div className="problem-dimension-layout">
            <div className="problem-dimension-dominant">
              <span>Dominant candidate dimension</span>
              <h3>{dimensions.data.dominant_dimension?.analyst_name || "Unnamed dimension"}</h3>
              <p>{dimensions.data.dominant_dimension?.description || "No reviewed description is available."}</p>
              <div className="header-badges">
                {dimensions.data.dominant_dimension?.membership_type && (
                  <Badge tone="blue">{label(dimensions.data.dominant_dimension.membership_type)}</Badge>
                )}
                {dimensions.data.ambiguous && <Badge tone="amber">Ambiguous assignment</Badge>}
                <Badge tone="neutral">
                  score{" "}
                  {dimensions.data.dominant_dimension?.coordinate !== undefined &&
                  dimensions.data.dominant_dimension?.coordinate !== null
                    ? dimensions.data.dominant_dimension.coordinate.toFixed(2)
                    : "-"}
                </Badge>
              </div>
              <Link
                className="btn btn-ghost btn-small"
                to={`/dimensions/${dimensions.data.dominant_dimension?.dimension_id}?run=${dimensions.data.run_id}`}
              >
                <Layers3 size={14} />
                Inspect dimension
              </Link>
            </div>
            <div className="problem-dimension-score-list">
              {dimensions.data.scores.map((score) => {
                const maxScore = Math.max(
                  0.0001,
                  ...dimensions.data!.scores.map((item) => Math.abs(item.coordinate)),
                );
                return (
                  <div className="problem-dimension-score" key={score.dimension_id}>
                    <div>
                      <strong>{score.analyst_name || score.dimension_id}</strong>
                      <span>
                        {score.dimension_id} · {label(score.membership_type || "unassigned")}
                        {score.relative_squared_coordinate_share_pct !== null &&
                        score.relative_squared_coordinate_share_pct !== undefined
                          ? ` · ${score.relative_squared_coordinate_share_pct.toFixed(1)}% squared share`
                          : ""}
                      </span>
                    </div>
                    <div className="problem-dimension-track">
                      <span style={{ width: `${Math.max(2, (Math.abs(score.coordinate) / maxScore) * 100)}%` }} />
                    </div>
                    <strong className="mono">{score.coordinate.toFixed(2)}</strong>
                  </div>
                );
              })}
            </div>
          </div>
          {dimensions.data.equation?.equation_text && (
            <div className="problem-dimension-equation">
              <span>Signed factor equation</span>
              <code>{dimensions.data.equation.equation_text}</code>
              <small>Coefficients are FAMD row coordinates, not causal effects.</small>
            </div>
          )}
          <p className="footnote">
            Coordinates are centered FAMD scores from run <span className="mono">{dimensions.data.run_id}</span>. A
            negative coordinate is the opposite side of the same pattern, not a separate dimension. Missing inputs are
            imputed for fitting and remain visible in the run quality report.
          </p>
        </Card>
      )}

      <div className="grid grid-detail">
        <div className="stack">
          <Card
            title="Supporting customer evidence"
            hint="Open any feedback item to inspect every computed signal and its mapping"
          >
            <div className="evidence-list">
              {data.evidence.length === 0 && <EmptyState title="No evidence links" />}
              {data.evidence.map((item, index) => {
                const insights = item.insights || [];
                return (
                  <details className="evidence-item" key={`${item.feedback_id}-${index}`}>
                    <summary className="evidence-summary">
                      <div className="evidence-head">
                        <div>
                          <Badge tone="neutral">{item.feedback_id}</Badge>
                          <span>{label(item.source_type)}</span>
                          <span>{item.platform}</span>
                        </div>
                        <div className="evidence-meta">
                          {item.rating && (
                            <span className="rating">
                              <Star size={13} fill="currentColor" />
                              {item.rating}
                            </span>
                          )}
                          <span>{date(item.submitted_at)}</span>
                          <ChevronDown size={15} className="evidence-chevron" />
                        </div>
                      </div>
                      <blockquote>
                        <Quote size={16} />
                        <span>{item.evidence_span}</span>
                      </blockquote>
                      <span className="evidence-expand-label">
                        <BrainCircuit size={13} />
                        Explore computed signals and mapping
                      </span>
                    </summary>

                    <div className="evidence-signals">
                      <div className="evidence-signal-title">
                        <Activity size={14} />
                        Computed signals
                      </div>
                      {insights.length === 0 && <p className="footnote">No insight record linked to this feedback item.</p>}
                      {insights.map((insight) => (
                        <div className="signal-panel" key={insight.insight_id}>
                          <div className="signal-panel-head">
                            <span className="mono">{insight.insight_id}</span>
                            <Badge tone={insight.sentiment === "positive" ? "green" : insight.sentiment === "mixed" ? "amber" : "red"}>
                              {label(insight.sentiment)}
                            </Badge>
                            <span className="signal-confidence">{Math.round(insight.confidence * 100)}% confidence</span>
                          </div>
                          <div className="signal-grid">
                            <div>
                              <span>Intent</span>
                              <strong>{label((insight.intents?.length ? insight.intents : [insight.customer_intent]).filter(Boolean).join(", "))}</strong>
                            </div>
                            <div>
                              <span>Aspect</span>
                              <strong>{label((insight.aspects?.length ? insight.aspects : [insight.aspect]).filter(Boolean).join(", "))}</strong>
                            </div>
                            <div>
                              <span>Symptom</span>
                              <strong>{label(insight.reported_symptom)}</strong>
                            </div>
                            <div>
                              <span>Emotion</span>
                              <strong>{label(insight.emotion)}</strong>
                            </div>
                            <div>
                              <span>Customer effort</span>
                              <strong>{label(insight.customer_effort)}</strong>
                            </div>
                            <div>
                              <span>Outcome</span>
                              <strong>{label(insight.reported_outcome)}</strong>
                            </div>
                            <div>
                              <span>Language</span>
                              <strong>{insight.language || "unknown"}</strong>
                            </div>
                            <div>
                              <span>Root cause</span>
                              <strong>{label(insight.technical_root_cause || "unknown")}</strong>
                            </div>
                          </div>
                          {insight.reported_problem && (
                            <p className="signal-problem">
                              <strong>Extracted problem:</strong> {insight.reported_problem}
                            </p>
                          )}
                          {Object.keys(insight.field_confidence || {}).length > 0 && (
                            <div className="signal-confidence-row">
                              {Object.entries(insight.field_confidence).map(([field, value]) => (
                                <span key={field}>
                                  {label(field)} <strong>{Math.round(Number(value) * 100)}%</strong>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}

                      <div className="evidence-signal-title">
                        <ShieldCheck size={14} />
                        Underlying problem and mapping
                      </div>
                      <div className="evidence-mapping">
                        <div>
                          <span>Canonical problem</span>
                          <strong>{data.title}</strong>
                          <p>{data.canonical_description || data.problem_statement}</p>
                        </div>
                        <div>
                          <span>Journey</span>
                          <strong>{data.journey_name || data.journey_node_id || "UNMAPPED"}</strong>
                        </div>
                        {primaryMapping ? (
                          <div>
                            <span>Taxonomy mapping</span>
                            <strong>
                              {primaryMapping.display_name || primaryMapping.node_id} ·{" "}
                              {Math.round(primaryMapping.confidence * 100)}%
                            </strong>
                            <p>{primaryMapping.rationale}</p>
                            <small>
                              {label(primaryMapping.mapping_type)} · {label(primaryMapping.status)} · taxonomy v
                              {data.taxonomy_version}
                            </small>
                          </div>
                        ) : (
                          <div>
                            <span>Taxonomy mapping</span>
                            <strong>UNMAPPED</strong>
                            <p>A taxonomy proposal should be reviewed before this problem is treated as canonical.</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </details>
                );
              })}
            </div>
          </Card>
        </div>

        <div className="stack">
          <Card title="Journey mapping" hint="Primary mapping and rationale">
            {data.mappings.length === 0 && <EmptyState title="Unmapped" detail="A taxonomy proposal should be reviewed." />}
            {data.mappings.map((mapping) => (
              <div className="mapping-block" key={mapping.mapping_id}>
                <div className="mapping-head">
                  <ShieldCheck size={16} />
                  <strong>{mapping.display_name || mapping.node_id}</strong>
                  <Badge tone="green">{Math.round(mapping.confidence * 100)}%</Badge>
                </div>
                <p>{mapping.rationale}</p>
                <div className="mapping-foot">
                  <span>{mapping.mapping_type}</span>
                  <span>{label(mapping.status)}</span>
                </div>
              </div>
            ))}
          </Card>

          <Card title="Reviewer decision" hint="Every action is auditable">
            <form className="form" onSubmit={submit}>
              <label>
                <span>Reviewer</span>
                <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} required />
              </label>
              <label>
                <span>Decision</span>
                <select value={decision} onChange={(event) => setDecision(event.target.value)}>
                  <option value="accept">Accept problem</option>
                  <option value="mark_in_review">Mark in review</option>
                  <option value="reject">Reject</option>
                  <option value="merge">Merge into another problem</option>
                  <option value="split">Split cluster</option>
                  <option value="rename">Rename</option>
                  <option value="deprecate">Deprecate</option>
                </select>
              </label>
              {decision === "rename" && (
                <label>
                  <span>New title</span>
                  <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} />
                </label>
              )}
              <label>
                <span>Audit note</span>
                <textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
              </label>
              <button className="btn btn-primary" disabled={saving}>
                <CheckCircle2 size={15} />
                {saving ? "Saving…" : "Record decision"}
              </button>
              {message && <p className="form-success">{message}</p>}
              {reviewError && <p className="form-error">{reviewError}</p>}
            </form>
          </Card>

          <Card title="Review history" hint="Newest first">
            {data.reviews.length === 0 && <EmptyState title="No reviews yet" />}
            <div className="timeline">
              {data.reviews.map((review, index) => (
                <div className="timeline-item" key={`${review.created_at}-${index}`}>
                  <UserRound size={14} />
                  <div>
                    <strong>{review.reviewer}</strong>
                    <span>
                      {label(review.decision)} · {dateTime(review.created_at)}
                    </span>
                    {review.note && <p>{review.note}</p>}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
