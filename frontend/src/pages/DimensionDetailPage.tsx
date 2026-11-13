import { ArrowLeft, ArrowUpRight, BarChart3, GitBranch, ShieldAlert, ShieldCheck } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Progress, Spinner, relationshipTone } from "../components/ui";
import { dateTime, label, number, percent } from "../lib/format";
import type { DimensionDetail, DimensionPublication, DimensionRun, DimensionTrend } from "../lib/types";
import { useFetch } from "../lib/useFetch";

const TREND_LABELS: Record<string, string> = {
  problem_count: "Problems",
  evidence_volume_sum: "Evidence links",
  distinct_customers_sum: "Distinct customers",
  evidence_per_problem_mean: "Evidence per problem",
  negative_share_mean: "Mean negative share",
  high_effort_share_mean: "Mean high-effort share",
  outcome_failure_share_mean: "Mean task-failure share",
  negative_emotion_share_mean: "Mean negative-emotion share",
};

function contribution(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(1)} pts`;
}

function trendValue(trend: DimensionTrend): string {
  if (trend.metric_value === null || trend.metric_value === undefined) return "NO DATA";
  if (trend.metric_name.endsWith("_share_mean")) return percent(trend.metric_value);
  if (trend.metric_name.endsWith("_mean")) return trend.metric_value.toFixed(2);
  return number(trend.metric_value);
}

function coordinate(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

export default function DimensionDetailPage() {
  const { dimensionId } = useParams();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const detail = useFetch<DimensionDetail>(
    dimensionId
      ? runId
        ? `/problem-dimensions/runs/${runId}/dimensions/${dimensionId}`
        : `/problem-dimensions/latest/dimensions/${dimensionId}`
      : null,
    [dimensionId, runId],
  );
  const run = useFetch<DimensionRun>(runId ? `/problem-dimensions/runs/${runId}` : null, [runId]);
  const latest = useFetch<DimensionPublication>(!runId ? "/problem-dimensions/latest" : null);
  const runData = run.data || latest.data?.run;

  if (detail.loading && !detail.data) return <Spinner label="Loading dimension diagnostics…" />;
  if (detail.error) return <ErrorState message={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return null;

  const definition = detail.data.definition;
  const variableContributions = detail.data.contributions
    .filter((item) => !item.category_level)
    .sort((left, right) => Math.abs(right.contribution) - Math.abs(left.contribution));
  const categoryContributions = detail.data.contributions
    .filter((item) => item.category_level)
    .sort((left, right) => right.contribution - left.contribution);
  const maxVariableContribution = Math.max(0.0001, ...variableContributions.map((item) => item.contribution));
  const dimensionSummary = runData?.diagnostics.dimensions?.find(
    (item) => item.dimension_id === definition.dimension_id,
  );
  const journeyDistribution = Object.entries(
    detail.data.top_problems.reduce<Record<string, number>>((counts, problem) => {
      if (problem.journey_node_id) {
        counts[problem.journey_node_id] = (counts[problem.journey_node_id] || 0) + 1;
      }
      return counts;
    }, {}),
  ).sort((left, right) => right[1] - left[1]);

  return (
    <div className="page">
      <Link to={runId ? `/dimensions?run=${runId}` : "/dimensions"} className="back-link">
        <ArrowLeft size={15} />
        Back to dimensions
      </Link>

      <PageHeader
        eyebrow={`${definition.dimension_id} · ${detail.data.run_id}`}
        title={definition.analyst_name}
        subtitle={definition.description || "No reviewed description has been saved for this dimension."}
        actions={
          <div className="header-badges">
            {definition.dimension_number && <Badge tone="neutral">F{definition.dimension_number}</Badge>}
            <Badge tone={relationshipTone(definition.review_status)}>{label(definition.review_status)}</Badge>
            <Badge tone="blue">{label(detail.data.run_status)}</Badge>
            {dimensionSummary?.explained_variance !== undefined && dimensionSummary?.explained_variance !== null && (
              <Badge tone="violet">{dimensionSummary.explained_variance.toFixed(1)}% variance</Badge>
            )}
          </div>
        }
      />

      <div className="theme-map-stats">
        <div className="stat-card tone-accent">
          <span className="stat-label">Representative problems</span>
          <div className="stat-value">{number(definition.representative_problem_ids.length)}</div>
          <span className="stat-detail">Problems with the strongest coordinate</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Active variables</span>
          <div className="stat-value">{number(variableContributions.length)}</div>
          <span className="stat-detail">Ranked by FAMD contribution</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Category levels</span>
          <div className="stat-value">{number(categoryContributions.length)}</div>
          <span className="stat-detail">Most influential one-hot levels</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Component eigenvalue</span>
          <div className="stat-value small">
            {dimensionSummary?.eigenvalue ? dimensionSummary.eigenvalue.toFixed(2) : "-"}
          </div>
          <span className="stat-detail">FAMD eigenvalue</span>
        </div>
      </div>

      <div className="grid grid-detail">
        <div className="stack">
          <Card
            title="Variable contributions"
            hint="Contribution explains how much a variable shapes this component. Direction is the variable coordinate sign; it is not a causal claim."
          >
            {variableContributions.length === 0 && <EmptyState title="No variable contributions" />}
            <div className="dimension-contribution-list">
              {variableContributions.map((item) => (
                <div className="dimension-contribution-row" key={item.variable_name}>
                  <div className="dimension-contribution-name">
                    <strong>{label(item.variable_name)}</strong>
                    <span>
                      {item.direction_summary === "-" ? "negative" : item.direction_summary === "+" ? "positive" : "mixed"}{" "}
                      coordinate {coordinate(item.coordinate)}
                    </span>
                  </div>
                  <div className="dimension-contribution-track">
                    <Progress value={item.contribution / maxVariableContribution} />
                  </div>
                  <strong className="dimension-contribution-value">{contribution(item.contribution)}</strong>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Influential category levels" hint="Categorical levels that pull problems toward this dimension.">
            {categoryContributions.length === 0 && <EmptyState title="No category contributions" />}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Variable</th>
                    <th>Category</th>
                    <th>Contribution</th>
                  </tr>
                </thead>
                <tbody>
                  {categoryContributions.slice(0, 30).map((item) => (
                    <tr key={`${item.variable_name}-${item.category_level}`}>
                      <td>{label(item.variable_name)}</td>
                      <td>{label(item.category_level)}</td>
                      <td>{contribution(item.contribution)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Dimension trends" hint="Descriptive aggregates for problems associated with this dimension. Not a forecast.">
            {detail.data.trends.length === 0 && <EmptyState title="No trend metrics computed" />}
            <div className="dimension-trend-grid">
              {detail.data.trends.map((trend) => (
                <div key={`${trend.time_window}-${trend.metric_name}`} className="dimension-trend">
                  <span>{TREND_LABELS[trend.metric_name] || label(trend.metric_name)}</span>
                  <strong>{trendValue(trend)}</strong>
                  <small>
                    {trend.time_window} window · {label(trend.status)}
                  </small>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="stack">
          <Card title="Review provenance" hint="Human decisions are recorded in the audit trail.">
            <div className="dimension-provenance">
              <div>
                <span>Status</span>
                <Badge tone={relationshipTone(definition.review_status)}>{label(definition.review_status)}</Badge>
              </div>
              <div>
                <span>Reviewer</span>
                <strong>{definition.reviewer || "Not reviewed"}</strong>
              </div>
              <div>
                <span>Reviewed at</span>
                <strong>{definition.reviewed_at ? dateTime(definition.reviewed_at) : "-"}</strong>
              </div>
              <div>
                <span>Run status</span>
                <Badge tone={detail.data.run_status === "PUBLISHED" ? "green" : "amber"}>
                  {label(detail.data.run_status)}
                </Badge>
              </div>
              {definition.review_note && <p>{definition.review_note}</p>}
            </div>
            <p className="footnote">
              <ShieldCheck size={13} /> Dimension names, descriptions and publication require analyst review. This page
              never asserts a root cause.
            </p>
          </Card>

          <Card title="Top problems" hint="Ordered by absolute dimension coordinate.">
            {detail.data.top_problems.length === 0 && <EmptyState title="No scored problems" />}
            {journeyDistribution.length > 0 && (
              <div className="dimension-journey-distribution">
                {journeyDistribution.map(([journey, count]) => (
                  <span className="dimension-journey-chip" key={journey}>
                    {label(journey)}
                    <strong>{count}</strong>
                  </span>
                ))}
              </div>
            )}
            <div className="dimension-problem-list">
              {detail.data.top_problems.map((problem, index) => (
                <Link key={problem.problem_id} to={`/problems/${problem.problem_id}`} className="dimension-problem-row">
                  <span className="dimension-rank">{index + 1}</span>
                  <div>
                    <strong>{problem.title || problem.problem_id}</strong>
                    <small>
                      {label(problem.aspect)} · {label(problem.symptom_category)}
                    </small>
                  </div>
                  <strong className="mono">{coordinate(problem.coordinate)}</strong>
                </Link>
              ))}
            </div>
          </Card>

          <Card title="Evidence and provenance" hint="Traceable inputs and explicit limitations">
            <div className="dimension-provenance">
              <div>
                <span>Feedback run</span>
                <strong className="mono">{runId || detail.data.run_id}</strong>
              </div>
              <div>
                <span>Feature snapshot</span>
                <strong className="mono">{runData?.input_snapshot_id || "not loaded"}</strong>
              </div>
              <div>
                <span>Method</span>
                <strong>
                  {runData?.method || "FAMD"} · {runData?.method_version || "famd"}
                </strong>
              </div>
              <div>
                <span>Library</span>
                <strong>{runData?.method_library_version || "prince"}</strong>
              </div>
            </div>
            <div className="dimension-callout">
              <GitBranch size={15} />
              <span>
                Dimension coordinates are centered FAMD scores. A high coordinate means a problem is strongly associated
                with the pattern, not that the pattern causes the problem.
              </span>
            </div>
            <div className="dimension-callout warning">
              <ShieldAlert size={15} />
              <span>
                Missing measurement windows are imputed only for model fitting. Check the run quality report before using
                these dimensions for decisions.
              </span>
            </div>
            {detail.data.top_problems[0]?.problem_id && (
              <Link
                to={`/problems/${detail.data.top_problems[0].problem_id}`}
                className="btn btn-ghost btn-small"
                style={{ marginTop: 10 }}
              >
                <BarChart3 size={14} />
                Open a representative problem
                <ArrowUpRight size={13} />
              </Link>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
