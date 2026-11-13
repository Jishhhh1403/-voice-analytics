import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  FileJson,
  FlaskConical,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
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
import { regeneratePortfolioNarrative, startPortfolioRun } from "../lib/api";
import { dateTime, label, number, percent } from "../lib/format";
import type {
  DimensionStatus,
  PipelineRun,
  PortfolioRun,
  PortfolioSerializationRow,
  PortfolioStatus,
} from "../lib/types";
import { useFetch, usePolling } from "../lib/useFetch";

function narrativeTone(status?: string | null) {
  switch (status) {
    case "PASSED":
      return "green" as const;
    case "WARNING":
      return "amber" as const;
    case "FAILED":
    case "UNAVAILABLE":
      return "red" as const;
    default:
      return "neutral" as const;
  }
}

function score(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(2);
}

export default function PortfolioPage() {
  const status = useFetch<PortfolioStatus>("/problem-portfolio/status");
  const feedbackRuns = useFetch<PipelineRun[]>("/feedback-pipelines");
  const dimensions = useFetch<DimensionStatus>("/problem-dimensions/status");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [feedbackRunId, setFeedbackRunId] = useState("");
  const [dimensionRunId, setDimensionRunId] = useState("");
  const [starting, setStarting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const run = useFetch<PortfolioRun>(
    selectedRunId ? `/problem-portfolio/runs/${selectedRunId}` : null,
    [selectedRunId],
  );
  const serialization = useFetch<PortfolioSerializationRow>(
    selectedRunId ? `/problem-portfolio/runs/${selectedRunId}/serialization` : null,
    [selectedRunId],
  );

  const completedFeedbackRuns = useMemo(
    () => (feedbackRuns.data || []).filter((item) => item.status === "completed"),
    [feedbackRuns.data],
  );
  const approvedDimensionRuns = useMemo(
    () =>
      (dimensions.data?.latest_runs || []).filter(
        (item) => item.status === "APPROVED" || item.status === "PUBLISHED",
      ),
    [dimensions.data],
  );
  const inProgress = Boolean(
    run.data && ["QUEUED", "BUILDING_SERIALIZATION", "GENERATING_NARRATIVE"].includes(run.data.status),
  );

  usePolling(() => {
    run.reload();
    serialization.reload();
    status.reload();
  }, inProgress);

  useEffect(() => {
    if (selectedRunId || !status.data) return;
    const next = status.data.latest_run_id || status.data.latest_runs[0]?.run_id;
    if (next) setSelectedRunId(next);
  }, [selectedRunId, status.data]);

  useEffect(() => {
    if (feedbackRunId || completedFeedbackRuns.length === 0) return;
    setFeedbackRunId(completedFeedbackRuns[0].run_id);
  }, [completedFeedbackRuns, feedbackRunId]);

  useEffect(() => {
    if (dimensionRunId || approvedDimensionRuns.length === 0) return;
    setDimensionRunId(approvedDimensionRuns[0].run_id);
  }, [approvedDimensionRuns, dimensionRunId]);

  const reload = () => {
    status.reload();
    run.reload();
    serialization.reload();
  };

  const start = async () => {
    if (!feedbackRunId) return;
    setStarting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const created = await startPortfolioRun({
        feedback_run_id: feedbackRunId,
        dimension_run_id: dimensionRunId || null,
        force_rerun: true,
        generate_narrative: true,
      });
      setSelectedRunId(created.run_id);
      setActionMessage(`Portfolio run ${created.run_id} started (${label(created.status)}).`);
      status.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const regenerate = async () => {
    if (!run.data) return;
    setRegenerating(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await regeneratePortfolioNarrative(run.data.run_id, true);
      setActionMessage("Narrative regenerated from the existing deterministic serialization.");
      run.reload();
      status.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setRegenerating(false);
    }
  };

  if (status.loading && !status.data) return <Spinner label="Loading portfolio intelligence…" />;
  if (status.error) return <ErrorState message={status.error} onRetry={status.reload} />;
  if (!status.data) return null;

  const payload = serialization.data?.payload;
  const narrative = run.data?.narrative?.narrative;
  const validation = run.data?.validation;
  const narrativeStatus = run.data?.narrative?.status;
  const canStart = status.data.enabled && Boolean(feedbackRunId) && !starting;
  const factorProfiles = run.data?.factor_profiles || [];

  return (
    <div className="page">
      <PageHeader
        eyebrow="Problem portfolio intelligence"
        title="Portfolio narrative"
        subtitle="Deterministic problem, factor and MDS serialization with a grounded, validated narrative. The model never replaces the statistical source of truth."
        actions={
          <div className="header-badges">
            <Badge tone={status.data.enabled ? "green" : "red"}>
              {status.data.enabled ? "Portfolio enabled" : "Disabled"}
            </Badge>
            <Badge tone={status.data.provider_configured ? "blue" : "amber"}>
              {status.data.provider_configured ? `${status.data.provider} · ${status.data.model}` : "Narrative unavailable"}
            </Badge>
          </div>
        }
      />

      {!status.data.enabled && (
        <Card>
          <EmptyState
            title="Problem portfolio analysis is disabled"
            detail="Set ENABLE_PROBLEM_PORTFOLIO=true to enable serialization and narrative generation."
          />
        </Card>
      )}

      {status.data.enabled && (
        <>
          <div className="theme-map-stats">
            <StatCard
              label="Problems serialized"
              value={number(run.data?.summary?.n_problems)}
              detail={`${number(run.data?.summary?.n_factors)} approved factors`}
              icon={<FlaskConical size={17} />}
            />
            <StatCard
              label="Narrative status"
              value={narrativeStatus ? label(narrativeStatus) : "-"}
              detail={validation ? `${validation.warnings.length} warnings · ${validation.errors.length} errors` : "Not generated yet"}
              icon={<BrainCircuit size={17} />}
              tone={narrativeStatus === "FAILED" || narrativeStatus === "UNAVAILABLE" ? "danger" : "accent"}
            />
            <StatCard
              label="MDS relationships"
              value={number(run.data?.summary?.n_mds_relationships)}
              detail="Euclidean neighbours from raw MDS coordinates"
              icon={<ShieldCheck size={17} />}
            />
            <StatCard
              label="Serialization"
              value={run.data?.serialization ? "Hashed" : "-"}
              detail={run.data?.serialization?.content_hash?.slice(0, 16) || "No deterministic payload yet"}
              icon={<FileJson size={17} />}
              tone={run.data?.serialization ? "accent" : "default"}
            />
          </div>

          <div className="grid grid-main">
            <div className="stack">
              <Card
                title="Generate portfolio analysis"
                hint="Uses an approved factor run and the latest OK MDS snapshot. Regeneration reuses the stored serialization without rerunning MDS or FAMD."
                actions={
                  <button className="btn btn-ghost btn-small" onClick={reload} disabled={run.loading}>
                    <RefreshCw size={14} className={run.loading ? "spin" : undefined} />
                    Refresh
                  </button>
                }
              >
                <div className="dimension-review-toolbar">
                  <label>
                    <span>Feedback run</span>
                    <select value={feedbackRunId} onChange={(event) => setFeedbackRunId(event.target.value)}>
                      {completedFeedbackRuns.map((item) => (
                        <option key={item.run_id} value={item.run_id}>
                          {item.run_id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Approved factor run</span>
                    <select value={dimensionRunId} onChange={(event) => setDimensionRunId(event.target.value)}>
                      <option value="">Latest approved / published</option>
                      {approvedDimensionRuns.map((item) => (
                        <option key={item.run_id} value={item.run_id}>
                          {item.run_id} · {label(item.status)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="dimension-actions">
                    <button className="btn btn-primary btn-small" onClick={start} disabled={!canStart}>
                      <Play size={14} />
                      {starting ? "Starting…" : "Run portfolio analysis"}
                    </button>
                    {run.data && (
                      <button
                        className="btn btn-ghost btn-small"
                        onClick={regenerate}
                        disabled={regenerating || !run.data.serialization}
                      >
                        <Sparkles size={14} />
                        {regenerating ? "Regenerating…" : "Regenerate narrative"}
                      </button>
                    )}
                  </div>
                </div>
                {approvedDimensionRuns.length === 0 && (
                  <p className="dimension-warning">
                    <AlertTriangle size={14} />
                    No approved or published factor run is available. Review factor names first.
                  </p>
                )}
                {!status.data.provider_configured && (
                  <p className="dimension-warning">
                    <AlertTriangle size={14} />
                    Narrative provider is not configured. Serialization still runs and remains available.
                  </p>
                )}
                {actionMessage && <p className="form-success">{actionMessage}</p>}
                {actionError && <p className="form-error">{actionError}</p>}
              </Card>

              {run.data && (
                <Card
                  title="Portfolio run"
                  hint="The serialized payload is immutable for a run; narratives are append-only and validation is deterministic."
                >
                  <div className="dimension-run-summary">
                    <div>
                      <span>Run</span>
                      <strong className="mono">{run.data.run_id}</strong>
                    </div>
                    <div>
                      <span>Status</span>
                      <Badge tone={relationshipTone(run.data.status)}>{label(run.data.status)}</Badge>
                    </div>
                    <div>
                      <span>Stage</span>
                      <strong>{label(run.data.stage)}</strong>
                    </div>
                    <div>
                      <span>Feedback run</span>
                      <strong className="mono">{run.data.feedback_run_id}</strong>
                    </div>
                    <div>
                      <span>Factor run</span>
                      <strong className="mono">{run.data.dimension_run_id}</strong>
                    </div>
                    <div>
                      <span>MDS</span>
                      <strong className="mono">{run.data.mds_id || "-"}</strong>
                    </div>
                    <div>
                      <span>Narrative model</span>
                      <strong>{run.data.narrative_model || "-"}</strong>
                    </div>
                    <div>
                      <span>Created</span>
                      <strong>{dateTime(run.data.created_at)}</strong>
                    </div>
                  </div>
                  {run.data.error && <ErrorState message={run.data.error} />}
                  {payload?.data_quality?.warnings?.length ? (
                    <div className="dimension-warning-list">
                      {payload.data_quality.warnings.map((warning) => (
                        <p className="dimension-warning" key={warning}>
                          <AlertTriangle size={14} />
                          {warning}
                        </p>
                      ))}
                    </div>
                  ) : null}
                </Card>
              )}

              {narrative && (
                <Card
                  title={narrative.title}
                  hint="Grounded in the serialized problem portfolio. Factor and MDS relationships are associations, not causal effects."
                  actions={
                    <Badge tone={narrativeTone(narrativeStatus)}>
                      {label(narrativeStatus)} · {run.data?.narrative?.generation_attempts || 0} attempt(s)
                    </Badge>
                  }
                >
                  <p className="portfolio-narrative-summary">{narrative.executive_summary}</p>

                  <h3 className="portfolio-section-title">Key findings</h3>
                  <div className="stack">
                    {narrative.key_findings.map((finding) => (
                      <div className="portfolio-narrative-card" key={finding.title}>
                        <div className="dimension-card-title">
                          <strong>{finding.title}</strong>
                          <Badge tone={finding.confidence === "high" ? "green" : finding.confidence === "medium" ? "blue" : "amber"}>
                            {finding.confidence} confidence
                          </Badge>
                        </div>
                        <p>{finding.narrative}</p>
                        <p className="footnote">{finding.business_implication}</p>
                        <div className="dimension-chip-row">
                          {finding.evidence.map((item, index) => (
                            <span className="dimension-chip" key={`${finding.title}-${index}`}>
                              {item.problem_id && (
                                <Link to={`/problems/${item.problem_id}`}>{item.problem_id}</Link>
                              )}
                              {item.factor_name && <strong>{item.factor_name}</strong>}
                              {item.metric_name && <small>{label(item.metric_name)}</small>}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <h3 className="portfolio-section-title">Factor interpretations</h3>
                  <div className="stack">
                    {narrative.factor_interpretations.map((item) => (
                      <div className="portfolio-narrative-card" key={item.factor_name}>
                        <div className="dimension-card-title">
                          <strong>{item.factor_name}</strong>
                          <Badge tone={item.confidence === "high" ? "green" : item.confidence === "medium" ? "blue" : "amber"}>
                            {item.confidence} confidence
                          </Badge>
                        </div>
                        <p>{item.interpretation}</p>
                        <p className="footnote">{item.business_implication}</p>
                        {item.common_problem_patterns.length > 0 && (
                          <div className="dimension-chip-row">
                            {item.common_problem_patterns.map((pattern) => (
                              <span className="dimension-chip" key={pattern}>
                                {pattern}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  <h3 className="portfolio-section-title">Recommended actions</h3>
                  <div className="stack">
                    {narrative.recommended_actions.map((item) => (
                      <div className="portfolio-narrative-card" key={item.action}>
                        <div className="dimension-card-title">
                          <strong>{item.action}</strong>
                          <Badge tone="blue">{label(item.horizon)}</Badge>
                        </div>
                        <p className="footnote">{item.rationale}</p>
                      </div>
                    ))}
                  </div>

                  {narrative.data_limitations.length > 0 && (
                    <>
                      <h3 className="portfolio-section-title">Data limitations</h3>
                      <ul className="portfolio-list">
                        {narrative.data_limitations.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {narrative.methodology_notes.length > 0 && (
                    <>
                      <h3 className="portfolio-section-title">Methodology notes</h3>
                      <ul className="portfolio-list">
                        {narrative.methodology_notes.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </Card>
              )}

              {!narrative && run.data?.narrative && (
                <Card title="Narrative unavailable">
                  <EmptyState
                    title={label(narrativeStatus)}
                    detail={run.data.narrative.error || "The deterministic serialization is available, but no validated narrative was produced."}
                  />
                </Card>
              )}

              {validation && (
                <Card
                  title="Narrative validation"
                  hint="Deterministic checks for grounded references, approved factor names, causal language and missing-value handling."
                  actions={<Badge tone={narrativeTone(validation.status)}>{label(validation.status)}</Badge>}
                >
                  {validation.errors.length > 0 && (
                    <div className="dimension-warning-list">
                      {validation.errors.map((error) => (
                        <p className="dimension-warning" key={error}>
                          <AlertTriangle size={14} />
                          {error}
                        </p>
                      ))}
                    </div>
                  )}
                  {validation.warnings.length > 0 && (
                    <ul className="portfolio-list">
                      {validation.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  )}
                  <div className="dimension-quality-list">
                    {validation.checks.map((check) => (
                      <div className={`dimension-quality-item ${check.status === "FAIL" ? "fail" : check.status === "WARN" ? "warn" : ""}`} key={check.name}>
                        {check.status === "PASS" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                        <div>
                          <strong>{label(check.name)}</strong>
                          <span>{check.message || check.status}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </div>

            <div className="stack">
              <Card title="Run history" hint="Latest portfolio runs across feedback and factor snapshots.">
                {status.data.latest_runs.length === 0 && <EmptyState title="No portfolio runs" detail="Run the analysis to create the first serialized portfolio." />}
                <div className="dimension-run-list">
                  {status.data.latest_runs.map((item) => (
                    <button
                      key={item.run_id}
                      className={`dimension-run-item ${selectedRunId === item.run_id ? "active" : ""}`}
                      onClick={() => setSelectedRunId(item.run_id)}
                    >
                      <strong className="mono">{item.run_id}</strong>
                      <span>
                        <Badge tone={relationshipTone(item.status)}>{label(item.status)}</Badge>
                        {item.summary?.n_problems !== undefined && <small>{number(item.summary.n_problems)} problems</small>}
                      </span>
                      <small>{dateTime(item.created_at)}</small>
                    </button>
                  ))}
                </div>
              </Card>

              {payload && (
                <Card title="Factor coverage" hint="Approved names and their serialized problem coverage.">
                  <div className="stack">
                    {factorProfiles.map((factor) => (
                      <div className="portfolio-factor-card" key={factor.factor_id}>
                        <div className="dimension-card-title">
                          <span className="mono">{factor.factor_id}</span>
                          <strong>{run.data?.factor_nomenclature.find((item) => item.factor_id === factor.factor_id)?.business_name || factor.dimension_id}</strong>
                          <Badge tone="neutral">{number(factor.problem_count)} problems</Badge>
                        </div>
                        <div className="dimension-run-summary">
                          <div>
                            <span>Variance</span>
                            <strong>{factor.explained_variance !== null && factor.explained_variance !== undefined ? `${factor.explained_variance.toFixed(1)}%` : "-"}</strong>
                          </div>
                          <div>
                            <span>Problem share</span>
                            <strong>{percent(factor.problem_share_pct !== null && factor.problem_share_pct !== undefined ? factor.problem_share_pct / 100 : null)}</strong>
                          </div>
                          <div>
                            <span>Mean |coef|</span>
                            <strong>{score(factor.mean_abs_coefficient)}</strong>
                          </div>
                          <div>
                            <span>Max |coef|</span>
                            <strong>{score(factor.max_abs_coefficient)}</strong>
                          </div>
                        </div>
                        <div className="dimension-chip-row">
                          {factor.top_variables.slice(0, 6).map((item) => (
                            <span className="dimension-chip" key={`${factor.factor_id}-${item.variable_name}-${item.category_level || ""}`}>
                              {label(item.variable_name)}
                              {item.category_level ? ` · ${label(item.category_level)}` : ""}
                              <strong>{item.direction_summary || "±"}</strong>
                              <small>{percent(item.contribution)}</small>
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {payload && (
                <Card title="Availability boundaries" hint="Attributes that are not available in the source data are never inferred.">
                  <div className="dimension-chip-row">
                    {payload.availability.unavailable.map((item) => (
                      <span className="dimension-chip" key={item.field} title={item.reason}>
                        {label(item.field)}
                      </span>
                    ))}
                  </div>
                  <p className="footnote">{payload.availability.missing_value_policy}</p>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
