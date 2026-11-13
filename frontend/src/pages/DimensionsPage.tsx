import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FlaskConical,
  Layers3,
  Play,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Spinner,
  StatCard,
  relationshipTone,
} from "../components/ui";
import {
  coefficientMatrixDownloadPath,
  coefficientMatrixPath,
  download,
  publishDimensionRun,
  reviewDimension,
  startDimensionRun,
} from "../lib/api";
import { dateTime, label, number, percent } from "../lib/format";
import type {
  DimensionCoefficientMatrix,
  DimensionDefinition,
  DimensionRun,
  DimensionStatus,
  PipelineRun,
} from "../lib/types";
import { useFetch, usePolling } from "../lib/useFetch";

function statusTone(status?: string | null) {
  switch (status) {
    case "PUBLISHED":
      return "green" as const;
    case "APPROVED":
      return "blue" as const;
    case "PENDING_REVIEW":
    case "QUEUED":
    case "RUNNING":
    case "BUILDING_FEATURES":
    case "VALIDATING_DATA":
    case "FITTING_FAMD":
    case "VALIDATING_RESULTS":
      return "amber" as const;
    case "FAILED":
    case "REJECTED":
      return "red" as const;
    default:
      return "neutral" as const;
  }
}

function variance(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(1)}%`;
}

function contribution(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(1)} pts`;
}

function DimensionReviewCard({
  run,
  definition,
  reviewer,
  note,
  onUpdated,
}: {
  run: DimensionRun;
  definition: DimensionDefinition;
  reviewer: string;
  note: string;
  onUpdated: () => void;
}) {
  const [name, setName] = useState(definition.analyst_name);
  const [description, setDescription] = useState(definition.description || "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const readOnly = run.status === "PUBLISHED" || run.status === "REJECTED";

  useEffect(() => {
    setName(definition.analyst_name);
    setDescription(definition.description || "");
  }, [definition.analyst_name, definition.description]);

  const submit = async (decision: "approve" | "reject" | "rename" | "request_revision") => {
    if (decision === "reject" && !window.confirm(`Reject ${definition.dimension_id}?`)) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await reviewDimension(run.run_id, definition.dimension_id, {
        reviewer,
        decision,
        name: name.trim() || undefined,
        description,
        note,
      });
      setMessage(decision === "approve" || decision === "rename" ? "Review saved." : "Review decision recorded.");
      onUpdated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const representative = definition.representative_problem_ids.slice(0, 5);

  return (
    <div className="dimension-card">
      <div className="dimension-card-head">
        <div>
          <div className="dimension-card-title">
            <span className="mono">{definition.dimension_id}</span>
            <Badge tone={relationshipTone(definition.review_status)}>{label(definition.review_status)}</Badge>
            <Badge tone="neutral">{contribution(definition.top_variables[0]?.contribution)} top load</Badge>
          </div>
          <h3>{definition.analyst_name}</h3>
        </div>
        <Link className="btn btn-ghost btn-small" to={`/dimensions/${definition.dimension_id}?run=${run.run_id}`}>
          Inspect
        </Link>
      </div>

      <p className="dimension-description">{definition.description}</p>

      <div className="dimension-chip-row">
        {definition.top_variables.slice(0, 6).map((item) => (
          <span className="dimension-chip" key={item.variable_name}>
            {label(item.variable_name)}
            <strong>{item.direction_summary || "±"}</strong>
            <small>{contribution(item.contribution)}</small>
          </span>
        ))}
      </div>

      <div className="dimension-representatives">
        <span>Representative problems</span>
        <div>
          {representative.length === 0 && <small>No representative problems recorded.</small>}
          {representative.map((problemId) => (
            <Link key={problemId} to={`/problems/${problemId}`} className="dimension-problem-link">
              {problemId}
            </Link>
          ))}
        </div>
      </div>

      {readOnly ? (
        <div className="dimension-review-meta">
          {definition.reviewer ? (
            <span>
              Reviewed by <strong>{definition.reviewer}</strong>
              {definition.reviewed_at ? ` · ${dateTime(definition.reviewed_at)}` : ""}
            </span>
          ) : (
            <span>No reviewer recorded.</span>
          )}
          {definition.review_note && <p>{definition.review_note}</p>}
        </div>
      ) : (
        <div className="dimension-review-form">
          <label>
            <span>Reviewed name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} maxLength={160} />
          </label>
          <label>
            <span>Reviewed description</span>
            <textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <div className="dimension-actions">
            <button className="btn btn-primary btn-small" disabled={saving} onClick={() => submit("approve")}>
              <CheckCircle2 size={14} />
              Approve
            </button>
            <button className="btn btn-ghost btn-small" disabled={saving} onClick={() => submit("rename")}>
              Save name
            </button>
            <button className="btn btn-ghost btn-small" disabled={saving} onClick={() => submit("request_revision")}>
              <RefreshCw size={14} />
              Request revision
            </button>
            <button className="btn btn-ghost btn-small danger" disabled={saving} onClick={() => submit("reject")}>
              <XCircle size={14} />
              Reject
            </button>
          </div>
          {message && <p className="form-success">{message}</p>}
          {error && <p className="form-error">{error}</p>}
        </div>
      )}
    </div>
  );
}

export default function DimensionsPage() {
  const status = useFetch<DimensionStatus>("/problem-dimensions/status");
  const feedbackRuns = useFetch<PipelineRun[]>("/feedback-pipelines");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [feedbackRunId, setFeedbackRunId] = useState("");
  const [maxComponents, setMaxComponents] = useState(5);
  const [reviewer, setReviewer] = useState("analyst@bank");
  const [note, setNote] = useState("");
  const [starting, setStarting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const completedRuns = useMemo(
    () => (feedbackRuns.data || []).filter((run) => run.status === "completed"),
    [feedbackRuns.data],
  );
  const run = useFetch<DimensionRun>(selectedRunId ? `/problem-dimensions/runs/${selectedRunId}` : null, [selectedRunId]);
  const matrix = useFetch<DimensionCoefficientMatrix>(
    selectedRunId ? coefficientMatrixPath(selectedRunId) : null,
    [selectedRunId],
  );
  const runInProgress = Boolean(
    run.data &&
      [
        "QUEUED",
        "RUNNING",
        "BUILDING_FEATURES",
        "VALIDATING_DATA",
        "FITTING_FAMD",
        "VALIDATING_RESULTS",
      ].includes(run.data.status),
  );

  usePolling(() => {
    run.reload();
    matrix.reload();
    status.reload();
  }, runInProgress);

  useEffect(() => {
    if (selectedRunId || !status.data) return;
    const next = status.data.latest_published_run_id || status.data.latest_runs[0]?.run_id;
    if (next) setSelectedRunId(next);
  }, [selectedRunId, status.data]);

  useEffect(() => {
    if (feedbackRunId || completedRuns.length === 0) return;
    setFeedbackRunId(completedRuns[0].run_id);
  }, [completedRuns, feedbackRunId]);

  const reload = () => {
    status.reload();
    run.reload();
    matrix.reload();
  };

  const start = async () => {
    if (!feedbackRunId) return;
    setStarting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const created = await startDimensionRun({
        feedback_run_id: feedbackRunId,
        max_components: maxComponents,
        force_rerun: true,
      });
      setSelectedRunId(created.run_id);
      setActionMessage(`Analysis run ${created.run_id} started (${label(created.status)}).`);
      status.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const publish = async () => {
    if (!run.data) return;
    if (
      run.data.status === "PUBLISHED" &&
      !window.confirm(`Republish ${run.data.run_id} as the latest published run?`)
    ) {
      return;
    }
    setPublishing(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await publishDimensionRun(run.data.run_id, reviewer, note);
      setActionMessage("Dimension run published as latest. Only the latest published run is shown on problem pages.");
      status.reload();
      run.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setPublishing(false);
    }
  };

  if (status.loading && !status.data) return <Spinner label="Loading dimension analysis…" />;
  if (status.error) return <ErrorState message={status.error} onRetry={status.reload} />;
  if (!status.data) return null;

  const definitions = run.data?.definitions || [];
  const allApproved = definitions.length > 0 && definitions.every((item) => item.review_status === "APPROVED");
  const diagnostics = run.data?.diagnostics;
  const dimensionSummaries = diagnostics?.dimensions || [];
  const retainedComponents = diagnostics?.retained_components || definitions.length;
  const qualityByName = new Map((run.data?.feature_quality || []).map((check) => [check.name, check]));
  const scree = (diagnostics?.eigenvalues || []).map((eigenvalue, index) => ({
    dimensionId: `D${index + 1}`,
    eigenvalue,
    variance: diagnostics?.percentage_of_variance?.[index],
    cumulative: diagnostics?.cumulative_percentage_of_variance?.[index],
  }));
  const featureRows = (run.data?.feature_dictionary || []).map((feature) => {
    const missing = qualityByName.get(`missingness:${feature.name}`)?.details as
      | { missing_count?: number; missing_share?: number }
      | undefined;
    const sparsity = qualityByName.get(`category_sparsity:${feature.name}`)?.details as
      | { levels?: Record<string, number> }
      | undefined;
    const levels = sparsity?.levels ? Object.entries(sparsity.levels) : null;
    return {
      ...feature,
      missingCount: missing?.missing_count ?? 0,
      missingShare: missing?.missing_share ?? 0,
      levels,
    };
  });
  const matrixDimensions = matrix.data?.dimensions || [];
  const matrixProblemIds = Array.from(
    new Set((matrix.data?.coefficients || []).map((item) => item.problem_id)),
  ).slice(0, 15);
  const coefficientLookup = new Map(
    (matrix.data?.coefficients || []).map((item) => [`${item.problem_id}:${item.dimension_id}`, item]),
  );
  const canStart = status.data.enabled && Boolean(feedbackRunId) && !starting;

  return (
    <div className="page">
      <PageHeader
        eyebrow="Canonical problem factor analysis"
        title="Customer problem factor analysis"
        subtitle="FAMD discovers candidate latent dimensions across canonical problems. Signed coefficients describe associations, not causal effects, and factor names require review before publication."
        actions={
          <div className="header-badges">
            <Badge tone={status.data.enabled ? "green" : "red"}>
              {status.data.enabled ? "FAMD enabled" : "Disabled"}
            </Badge>
            <Badge tone="blue">{status.data.methodology_version}</Badge>
          </div>
        }
      />

      {!status.data.enabled && (
        <Card>
          <EmptyState
            title="Dimension analysis is disabled"
            detail="Set ENABLE_PROBLEM_DIMENSIONS=true to expose the exploratory dimension pipeline."
          />
        </Card>
      )}

      {status.data.enabled && (
        <>
          <div className="theme-map-stats">
            <StatCard
              label="Latest published"
              value={status.data.latest_published_run_id ? "Available" : "None"}
              detail={
                status.data.latest_published_run_id
                  ? `${status.data.latest_published_run_id} · ${dateTime(status.data.latest_published_at)}`
                  : "Review and publish a run to expose dimensions on problem pages"
              }
              icon={<ShieldCheck size={17} />}
              tone={status.data.latest_published_run_id ? "accent" : "warning"}
            />
            <StatCard
              label="Problems analysed"
              value={number(diagnostics?.n_problems)}
              detail={`${number(diagnostics?.n_features)} active features`}
              icon={<Layers3 size={17} />}
            />
            <StatCard
              label="Retained dimensions"
              value={number(diagnostics?.retained_components ?? definitions.length)}
              detail={`${number(diagnostics?.fitted_components)} fitted components`}
              icon={<FlaskConical size={17} />}
            />
            <StatCard
              label="Quality gates"
              value={`${number(diagnostics?.quality_summary?.pass || 0)} pass`}
              detail={`${number(diagnostics?.quality_summary?.warn || 0)} warnings · ${number(
                diagnostics?.quality_summary?.fail || 0,
              )} failures`}
              icon={<AlertTriangle size={17} />}
              tone={(diagnostics?.quality_summary?.fail || 0) > 0 ? "danger" : "default"}
            />
          </div>

          <div className="grid grid-main">
            <div className="stack">
              <Card
                title="Analysis run"
                hint="Approval is per dimension. Publishing is append-only and does not alter canonical problems."
                actions={
                  <div className="card-actions">
                    <button className="btn btn-ghost btn-small" onClick={reload} disabled={run.loading}>
                      <RefreshCw size={14} className={run.loading ? "spin" : undefined} />
                      Refresh
                    </button>
                    {run.data && run.data.status !== "REJECTED" && definitions.length > 0 && (
                      <button
                        className="btn btn-primary btn-small"
                        onClick={publish}
                        disabled={!allApproved || publishing}
                        title={
                          allApproved
                            ? run.data.status === "PUBLISHED"
                              ? "Republish this run to roll back the latest publication"
                              : "Publish this reviewed run"
                            : "Every retained dimension must be approved"
                        }
                      >
                        <ShieldCheck size={14} />
                        {publishing
                          ? "Publishing…"
                          : run.data.status === "PUBLISHED"
                            ? "Republish as latest"
                            : "Publish run"}
                      </button>
                    )}
                  </div>
                }
              >
                {run.loading && !run.data && <Spinner label="Loading run…" />}
                {run.error && <ErrorState message={run.error} onRetry={run.reload} />}
                {run.data && (
                  <div className="dimension-run-summary">
                    <div>
                      <span>Run</span>
                      <strong className="mono">{run.data.run_id}</strong>
                    </div>
                    <div>
                      <span>Status</span>
                      <Badge tone={statusTone(run.data.status)}>{label(run.data.status)}</Badge>
                    </div>
                    <div>
                      <span>Feedback run</span>
                      <strong className="mono">{run.data.feedback_run_id || "-"}</strong>
                    </div>
                    <div>
                      <span>Input snapshot</span>
                      <strong className="mono">{run.data.input_snapshot_id || "-"}</strong>
                    </div>
                    <div>
                      <span>Method</span>
                      <strong>
                        {run.data.method} · {run.data.method_library_version || "prince"}
                      </strong>
                    </div>
                    <div>
                      <span>Created</span>
                      <strong>{dateTime(run.data.created_at)}</strong>
                    </div>
                    <div>
                      <span>Published</span>
                      <strong>{run.data.status === "PUBLISHED" ? "Immutable publication" : "Not published"}</strong>
                    </div>
                  </div>
                )}
                {run.data?.error && <ErrorState message={run.data.error} />}
                {run.data && dimensionSummaries.length > 0 && (
                  <div className="dimension-variance-row">
                    {dimensionSummaries.map((summary) => (
                      <div key={summary.dimension_id}>
                        <span>{summary.dimension_id}</span>
                        <strong>{variance(summary.explained_variance)}</strong>
                        <small>cum. {variance(summary.cumulative_variance)}</small>
                      </div>
                    ))}
                  </div>
                )}
                {diagnostics?.interpretation_warning && (
                  <p className="dimension-warning">
                    <AlertTriangle size={14} />
                    {diagnostics.interpretation_warning}
                  </p>
                )}
              </Card>

              {run.data && (
                <Card
                  title="Customer problem factor coefficients"
                  hint="Signed FAMD row coordinates. Coefficients describe association in latent-dimension space, not causal effects."
                  actions={
                    <button
                      className="btn btn-ghost btn-small"
                      onClick={() =>
                        download(
                          coefficientMatrixDownloadPath(run.data!.run_id),
                          `${run.data!.run_id}-coefficients.csv`,
                        )
                      }
                      disabled={!matrix.data?.coefficients.length}
                    >
                      <Download size={14} />
                      Export CSV
                    </button>
                  }
                >
                  {matrix.loading && !matrix.data && <Spinner label="Loading coefficients…" />}
                  {matrix.error && <ErrorState message={matrix.error} onRetry={matrix.reload} />}
                  {matrix.data && matrix.data.coefficients.length === 0 && (
                    <EmptyState
                      title="No coefficients available"
                      detail="Run the analysis to generate signed problem-factor coefficients."
                    />
                  )}
                  {matrix.data && matrix.data.coefficients.length > 0 && (
                    <>
                      <div className="dimension-coefficient-table-wrap">
                        <table className="dimension-coefficient-table">
                          <thead>
                            <tr>
                              <th>Problem</th>
                              {matrixDimensions.map((dimension) => (
                                <th key={dimension.dimension_id}>
                                  <span className="mono">{dimension.factor_id}</span>
                                  <small>{dimension.factor_name || dimension.dimension_id}</small>
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {matrixProblemIds.map((problemId) => (
                              <tr key={problemId}>
                                <th className="mono">
                                  <Link to={`/problems/${problemId}`}>{problemId}</Link>
                                </th>
                                {matrixDimensions.map((dimension) => {
                                  const cell = coefficientLookup.get(`${problemId}:${dimension.dimension_id}`);
                                  return (
                                    <td key={dimension.dimension_id}>
                                      {cell ? (
                                        <>
                                          <strong className={cell.coefficient < 0 ? "coefficient-negative" : "coefficient-positive"}>
                                            {cell.coefficient > 0 ? "+" : ""}
                                            {cell.coefficient.toFixed(4)}
                                          </strong>
                                          <small>
                                            {cell.relative_squared_coordinate_share_pct !== null &&
                                            cell.relative_squared_coordinate_share_pct !== undefined
                                              ? `${cell.relative_squared_coordinate_share_pct.toFixed(1)}% squared share`
                                              : "zero vector"}
                                          </small>
                                        </>
                                      ) : (
                                        <span className="muted">-</span>
                                      )}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <p className="footnote">
                        Showing {matrixProblemIds.length} of{" "}
                        {new Set(matrix.data.coefficients.map((item) => item.problem_id)).size} problems.{" "}
                        {matrix.data.share_definition}
                      </p>
                      <p className="dimension-warning">
                        <AlertTriangle size={14} />
                        {matrix.data.interpretation_warning}
                      </p>
                    </>
                  )}
                </Card>
              )}

              {run.data && (
                <div className="dimension-review-toolbar">
                  <label>
                    <span>Reviewer</span>
                    <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
                  </label>
                  <label>
                    <span>Review note applied to decisions</span>
                    <input value={note} onChange={(event) => setNote(event.target.value)} />
                  </label>
                  <div className="dimension-toolbar-state">
                    <Badge tone={allApproved ? "green" : "amber"}>
                      {definitions.filter((item) => item.review_status === "APPROVED").length}/{definitions.length} approved
                    </Badge>
                  </div>
                </div>
              )}

              {run.data && definitions.length === 0 && (
                <Card>
                  <EmptyState title="No dimensions retained" detail="The run did not produce reviewable dimensions." />
                </Card>
              )}
              {run.data &&
                definitions.map((definition) => (
                  <DimensionReviewCard
                    key={`${run.data!.run_id}-${definition.dimension_id}`}
                    run={run.data!}
                    definition={definition}
                    reviewer={reviewer}
                    note={note}
                    onUpdated={reload}
                  />
                ))}
              {actionMessage && <p className="form-success">{actionMessage}</p>}
              {actionError && <p className="form-error">{actionError}</p>}
            </div>

            <div className="stack">
              <Card title="Run analysis" hint="Runs in the background; this page refreshes while the analysis is active. Reuse is idempotent unless forced.">
                <div className="form">
                  <label>
                    <span>Completed feedback run</span>
                    <select value={feedbackRunId} onChange={(event) => setFeedbackRunId(event.target.value)}>
                      {completedRuns.length === 0 && <option value="">No completed feedback run</option>}
                      {completedRuns.map((item) => (
                        <option key={item.run_id} value={item.run_id}>
                          {item.run_id} · {item.source_filename || "feedback"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Components to fit</span>
                    <select value={maxComponents} onChange={(event) => setMaxComponents(Number(event.target.value))}>
                      {[1, 2, 3, 4, 5, 6, 8, 10].map((value) => (
                        <option key={value} value={value}>
                          {value} components
                        </option>
                      ))}
                    </select>
                  </label>
                  <button className="btn btn-primary" onClick={start} disabled={!canStart}>
                    <Play size={15} />
                    {starting ? "Starting analysis…" : "Start dimension analysis"}
                  </button>
                  <p className="footnote">
                    Review gate: {status.data.review_required ? "enabled" : "disabled"}. Published runs are resolved through
                    the append-only publication ledger.
                  </p>
                </div>
              </Card>

              <Card title="Run history" hint="Select a run to inspect or review it">
                {status.data.latest_runs.length === 0 && <EmptyState title="No dimension runs yet" />}
                <div className="dimension-run-list">
                  {status.data.latest_runs.map((item) => (
                    <button
                      key={item.run_id}
                      className={`dimension-run-item ${item.run_id === selectedRunId ? "active" : ""}`}
                      onClick={() => setSelectedRunId(item.run_id)}
                    >
                      <div>
                        <strong className="mono">{item.run_id}</strong>
                        <span>{dateTime(item.created_at)}</span>
                        <small>{item.feedback_run_id}</small>
                      </div>
                      <Badge tone={statusTone(item.status)}>{label(item.status)}</Badge>
                    </button>
                  ))}
                </div>
              </Card>

              <Card title="Feature quality" hint="Gates run before FAMD fitting">
                {(run.data?.feature_quality || []).length === 0 && <EmptyState title="No quality report" />}
                <div className="dimension-quality-list">
                  {(run.data?.feature_quality || [])
                    .filter((check) => check.status !== "PASS")
                    .slice(0, 12)
                    .map((check) => (
                      <div key={check.name} className={`dimension-quality-item ${check.status.toLowerCase()}`}>
                        <Badge tone={check.status === "FAIL" ? "red" : "amber"}>{check.status}</Badge>
                        <div>
                          <strong>{label(check.name)}</strong>
                          <span>{check.message}</span>
                        </div>
                      </div>
                    ))}
                  {(run.data?.feature_quality || []).every((check) => check.status === "PASS") && (
                    <p className="footnote">All feature quality checks passed.</p>
                  )}
                </div>
              </Card>

              <Card title="Scree and explained inertia" hint="All fitted components. Retained dimensions are marked for review.">
                {scree.length === 0 && <EmptyState title="No fitted components" />}
                <div className="dimension-scree-list">
                  {scree.map((item, index) => (
                    <div className={`dimension-scree-row ${index < retainedComponents ? "retained" : ""}`} key={item.dimensionId}>
                      <span className="mono">{item.dimensionId}</span>
                      <div className="dimension-scree-track">
                        <span style={{ width: `${Math.max(1, Math.min(100, item.variance || 0))}%` }} />
                      </div>
                      <strong>{item.variance !== undefined ? `${item.variance.toFixed(1)}%` : "-"}</strong>
                      <small>
                        eigen {item.eigenvalue.toFixed(2)}
                        {item.cumulative !== undefined ? ` · cum ${item.cumulative.toFixed(1)}%` : ""}
                      </small>
                    </div>
                  ))}
                </div>
                <p className="footnote">
                  Retained: {retainedComponents} of {scree.length || 0} fitted components. Component count remains an
                  analyst decision supported by interpretability and stability, not a fixed variance threshold.
                </p>
              </Card>

              <Card title="Feature dictionary and coverage" hint="Versioned inputs, transformations, missingness and category frequencies.">
                {featureRows.length === 0 && <EmptyState title="No feature dictionary" />}
                <div className="dimension-feature-list">
                  {featureRows.map((feature) => (
                    <div className="dimension-feature-row" key={feature.name}>
                      <div className="dimension-feature-main">
                        <strong>{feature.label}</strong>
                        <span>{feature.source}</span>
                      </div>
                      <div className="dimension-feature-meta">
                        <Badge tone="neutral">{feature.type}</Badge>
                        <span>{feature.transform}</span>
                        <span>
                          missing {number(feature.missingCount)} ({percent(feature.missingShare)})
                        </span>
                        {feature.levels && feature.levels.length > 0 && (
                          <span>
                            {feature.levels.length} levels ·{" "}
                            {feature.levels
                              .slice(0, 5)
                              .map(([level, count]) => `${label(level)} ${count}`)
                              .join(" · ")}
                          </span>
                        )}
                      </div>
                      <p>{feature.missing_policy || "Missing values preserved; imputed for model fitting only."}</p>
                    </div>
                  ))}
                </div>
              </Card>

              {diagnostics?.preprocessing_warnings && diagnostics.preprocessing_warnings.length > 0 && (
                <Card title="Preprocessing notes" hint="Missing values are imputed only for model fitting and remain visible here.">
                  <ul className="dimension-warning-list">
                    {diagnostics.preprocessing_warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </Card>
              )}

              {diagnostics?.stability?.status === "RUN" && (
                <Card title="Bootstrap stability" hint="Absolute cosine similarity of component subspaces across resamples.">
                  <div className="dimension-stability">
                    {(diagnostics.stability.components || []).map((component) => (
                      <div key={component.dimension_id}>
                        <span>{component.dimension_id}</span>
                        <strong>{component.mean_abs_cosine?.toFixed(2) || "-"}</strong>
                        <small>min {component.min_abs_cosine?.toFixed(2) || "-"}</small>
                      </div>
                    ))}
                    <p className="footnote">{diagnostics.stability.note}</p>
                  </div>
                </Card>
              )}

              {diagnostics?.efa?.status && diagnostics.efa.status !== "DISABLED" && (
                <Card title="Optional EFA check" hint="Numeric-feature Factor Analysis is a robustness aid only.">
                  <Badge tone={diagnostics.efa.status === "OK" ? "green" : "amber"}>{label(diagnostics.efa.status)}</Badge>
                  {diagnostics.efa.factors?.slice(0, 3).map((factor) => (
                    <div key={factor.factor_id} className="dimension-efa-factor">
                      <strong>{factor.factor_id}</strong>
                      <span>
                        {factor.loadings
                          .slice(0, 4)
                          .map((item) => `${label(item.variable_name)} ${item.loading.toFixed(2)}`)
                          .join(" · ")}
                      </span>
                    </div>
                  ))}
                  {diagnostics.efa.note && <p className="footnote">{diagnostics.efa.note}</p>}
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
