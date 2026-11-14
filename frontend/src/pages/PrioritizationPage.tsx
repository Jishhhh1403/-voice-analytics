import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Play,
  RefreshCw,
  Scale,
  Sparkles,
  Target,
} from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Spinner,
  StatCard,
} from "../components/ui";
import {
  reviewFactorSemanticAssessment,
  startFactorPrioritisationRun,
} from "../lib/api";
import { dateTime, label, number } from "../lib/format";
import type {
  DimensionStatus,
  FactorPrioritisationRun,
  FactorPrioritisationRunSummary,
  FactorPrioritisationScore,
  FactorSemanticAssessment,
} from "../lib/types";
import { useFetch, usePolling } from "../lib/useFetch";

function score(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(2);
}

function coverage(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(0)}%`;
}

function statusTone(status?: string | null) {
  switch (status) {
    case "COMPLETED":
    case "VALIDATED":
    case "ELIGIBLE":
    case "APPROVED":
    case "OK":
      return "green" as const;
    case "PROVISIONAL":
    case "PENDING_REVIEW":
    case "PARTIAL":
    case "REVISION_REQUESTED":
      return "amber" as const;
    case "FAILED":
    case "EXCLUDED":
    case "REJECTED":
      return "red" as const;
    case "INSUFFICIENT_EVIDENCE":
      return "slate" as const;
    default:
      return "neutral" as const;
  }
}

function rawSummary(raw: Record<string, unknown>): string {
  const entries = Object.entries(raw || {}).filter(([, value]) => {
    if (value === null || value === undefined) return false;
    if (typeof value === "number") return true;
    if (typeof value === "string" || typeof value === "boolean") return true;
    return false;
  });
  if (!entries.length) return "No scalar evidence values.";
  return entries
    .slice(0, 8)
    .map(([key, value]) => `${label(key)}: ${typeof value === "number" ? number(Number(value)) : String(value)}`)
    .join(" · ");
}

function ComponentBar({ scoreValue }: { scoreValue: number | null }) {
  const width = scoreValue === null ? 0 : Math.max(0, Math.min(100, scoreValue));
  return (
    <div className="priority-bar" aria-label={scoreValue === null ? "No score" : `${scoreValue.toFixed(1)} out of 100`}>
      <span style={{ width: `${width}%` }} />
    </div>
  );
}

function FactorDetail({
  run,
  item,
  assessment,
  reviewer,
  note,
  onReviewed,
}: {
  run: FactorPrioritisationRun;
  item: FactorPrioritisationScore;
  assessment?: FactorSemanticAssessment;
  reviewer: string;
  note: string;
  onReviewed: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const subdimensions = assessment?.semantic_evaluation?.subdimensions || {};

  const review = async (decision: "approve" | "reject" | "request_revision") => {
    if (!assessment) return;
    if (!reviewer.trim()) {
      setError("Enter a reviewer before recording a decision.");
      return;
    }
    setBusy(decision);
    setMessage(null);
    setError(null);
    try {
      await reviewFactorSemanticAssessment(run.prioritisation_run_id, item.factor_id, {
        reviewer: reviewer.trim(),
        decision,
        note,
      });
      setMessage("Semantic review recorded.");
      onReviewed();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const description = item.explanation.nomenclature?.description;

  return (
    <div className="priority-detail">
      {description && (
        <div className="priority-factor-description">
          <h4>Factor description</h4>
          <p>{description}</p>
        </div>
      )}
      <div className="priority-detail-grid">
        <div>
          <h4>Why this score</h4>
          <ul className="priority-why">
            {item.explanation.why.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          <div className="priority-formula">{item.explanation.formula}</div>
        </div>

        <div>
          <h4>Evidence coverage</h4>
          <p className="footnote">
            {coverage(item.evidence_coverage)} of configured weight is supported by available evidence.
            Missing components are marked unknown, never zero.
          </p>
          <h4>Weights applied</h4>
          <div className="priority-weight-list">
            {Object.entries(item.weights).map(([key, value]) => (
              <div key={key}>
                <span>{label(key)}</span>
                <strong>{(value * 100).toFixed(0)}%</strong>
              </div>
            ))}
          </div>
        </div>
      </div>

      <h4>Component evidence</h4>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Component</th>
              <th>Weight</th>
              <th>Score</th>
              <th>Weighted</th>
              <th>Status</th>
              <th>Method</th>
              <th>Raw evidence</th>
            </tr>
          </thead>
          <tbody>
            {item.explanation.components.map((component) => (
              <tr key={component.name}>
                <td>
                  <strong>{component.label}</strong>
                  <div className="footnote">{component.explanation}</div>
                </td>
                <td>{(component.weight * 100).toFixed(0)}%</td>
                <td>
                  {score(component.score)}
                  <ComponentBar scoreValue={component.score} />
                </td>
                <td>{score(component.weighted_contribution)}</td>
                <td>
                  <Badge tone={statusTone(component.assessment_status)}>
                    {label(component.assessment_status)}
                  </Badge>
                </td>
                <td>
                  <div>{component.calculation_method}</div>
                  <div className="footnote">Rule {component.rule_version}</div>
                </td>
                <td className="footnote">{rawSummary(component.raw_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {assessment && (
        <div className="priority-semantic">
          <div className="priority-semantic-head">
            <div>
              <h4>Semantic evidence assessment</h4>
              <p className="footnote">
                Deterministic attribute concentration, not an LLM judgement. Rule:{" "}
                {assessment.semantic_evaluation.rule}.
              </p>
            </div>
            <Badge tone={statusTone(assessment.review_status)}>{label(assessment.review_status)}</Badge>
          </div>
          <div className="priority-semantic-grid">
            {Object.entries(subdimensions).map(([key, itemValue]) => (
              <div className="priority-semantic-card" key={key}>
                <div className="priority-semantic-card-head">
                  <strong>{itemValue.label}</strong>
                  <Badge tone={statusTone(itemValue.status)}>{label(itemValue.status)}</Badge>
                </div>
                <div className="priority-semantic-value">
                  {score(itemValue.score)}/100 · {coverage(itemValue.dominant_share_pct)}
                </div>
                <p>{itemValue.explanation}</p>
                <div className="dimension-chip-row">
                  {itemValue.top_levels.map((level) => (
                    <span className="dimension-chip" key={level.level}>
                      {level.level} · {level.count}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="priority-review">
            <button
              className="btn btn-primary"
              onClick={() => review("approve")}
              disabled={busy !== null}
            >
              {busy === "approve" ? <RefreshCw className="spin" size={14} /> : <Sparkles size={14} />}
              Approve coherence
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => review("request_revision")}
              disabled={busy !== null}
            >
              Request revision
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => review("reject")}
              disabled={busy !== null}
            >
              Reject
            </button>
            <span className="footnote">
              {assessment.reviewer_id
                ? `Last reviewed by ${assessment.reviewer_id} at ${dateTime(assessment.reviewed_at)}.`
                : "No semantic review recorded yet."}
            </span>
          </div>
          {message && <div className="inline-message success">{message}</div>}
          {error && <div className="inline-message error">{error}</div>}
        </div>
      )}

      {item.explanation.caveats.length > 0 && (
        <div className="priority-caveats">
          <AlertTriangle size={16} />
          <div>
            <strong>Interpretation limits.</strong>
            <ul>
              {item.explanation.caveats.map((caveat) => (
                <li key={caveat}>{caveat}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

export default function PrioritizationPage() {
  const status = useFetch<{
    enabled: boolean;
    model_version: string;
    weights: Record<string, number>;
    latest_run_id?: string | null;
  }>("/factor-prioritisation/status");
  const runs = useFetch<FactorPrioritisationRunSummary[]>("/factor-prioritisation/runs?limit=20");
  const dimensions = useFetch<DimensionStatus>("/problem-dimensions/status");

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedFactorRunId, setSelectedFactorRunId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("analyst@example.com");
  const [note, setNote] = useState("");
  const [running, setRunning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const run = useFetch<FactorPrioritisationRun>(
    selectedRunId ? `/factor-prioritisation/runs/${selectedRunId}` : null,
    [selectedRunId],
  );

  useEffect(() => {
    if (selectedRunId || !runs.data?.length) return;
    setSelectedRunId(runs.data[0].prioritisation_run_id);
  }, [runs.data, selectedRunId]);

  useEffect(() => {
    if (selectedFactorRunId || !dimensions.data?.latest_runs?.length) return;
    setSelectedFactorRunId(dimensions.data.latest_runs[0].run_id);
  }, [dimensions.data, selectedFactorRunId]);

  const inProgress = run.data?.status === "QUEUED" || run.data?.status === "CALCULATING";
  usePolling(() => {
    run.reload();
    runs.reload();
  }, inProgress);

  const assessments = useMemo(
    () => new Map((run.data?.semantic_assessments || []).map((item) => [item.factor_id, item])),
    [run.data],
  );

  const start = async () => {
    setRunning(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await startFactorPrioritisationRun({
        famd_run_id: selectedFactorRunId,
        force_rerun: true,
      });
      setSelectedRunId(result.run_id);
      setActionMessage("Prioritisation run queued. Scores will appear when calculation completes.");
      runs.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const latest = run.data;
  const scores = latest?.scores || [];

  return (
    <div className="page">
      <PageHeader
        eyebrow="Factor evidence"
        title="Prioritization"
        subtitle="Deterministic ranking of every retained FAMD factor using prevalence, statistical importance, representation strength and semantic coherence."
        actions={
          <button className="btn btn-primary" onClick={start} disabled={running || !selectedFactorRunId}>
            {running ? <RefreshCw className="spin" size={15} /> : <Play size={15} />}
            Calculate prioritisation
          </button>
        }
      />

      {actionMessage && <div className="inline-message success">{actionMessage}</div>}
      {actionError && <div className="inline-message error">{actionError}</div>}

      <Card
        title="Run configuration"
        hint="Select a completed factor run. Re-running with the same weights and model version reuses the existing calculation."
      >
        <div className="priority-controls">
          <label>
            <span>Factor run</span>
            <select
              value={selectedFactorRunId || ""}
              onChange={(event) => setSelectedFactorRunId(event.target.value || null)}
            >
              <option value="">Select a completed factor run</option>
              {(dimensions.data?.latest_runs || []).map((item) => (
                <option key={item.run_id} value={item.run_id}>
                  {item.run_id} · {label(item.status)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Prioritisation run</span>
            <select
              value={selectedRunId || ""}
              onChange={(event) => setSelectedRunId(event.target.value || null)}
            >
              <option value="">Select a prioritisation run</option>
              {(runs.data || []).map((item) => (
                <option key={item.prioritisation_run_id} value={item.prioritisation_run_id}>
                  {item.prioritisation_run_id} · {label(item.status)}
                </option>
              ))}
            </select>
          </label>
          <div className="priority-config-meta">
            <span>Model {status.data?.model_version || "factor-evidence-v1"}</span>
            <span>
              Weights{" "}
              {Object.entries(status.data?.weights || {})
                .map(([key, value]) => `${label(key)} ${(value * 100).toFixed(0)}%`)
                .join(" · ")}
            </span>
          </div>
        </div>
        <div className="priority-review-inputs">
          <label>
            <span>Reviewer</span>
            <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
          </label>
          <label>
            <span>Review note</span>
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Optional note for the semantic review"
            />
          </label>
        </div>
      </Card>

      {run.loading && <Spinner label="Loading prioritisation run..." />}
      {run.error && <ErrorState message={run.error} onRetry={run.reload} />}

      {!run.loading && !run.error && !latest && (
        <EmptyState
          title="No prioritisation run selected"
          detail="Choose a structurally complete factor run and calculate prioritisation."
        />
      )}

      {latest && (
        <>
          <div className="theme-map-stats">
            <StatCard
              label="Scored factors"
              value={`${latest.summary.scored_factor_count ?? scores.length}/${latest.total_factor_count}`}
              detail={`${latest.summary.problems_analysed ?? "-"} canonical problems in the FAMD denominator`}
              icon={<Target size={16} />}
              tone="accent"
            />
            <StatCard
              label="Top factor"
              value={latest.summary.top_factor_id || "-"}
              detail={latest.summary.top_factor_name || "Name not set in serialization"}
              icon={<FlaskConical size={16} />}
            />
            <StatCard
              label="Top priority"
              value={score(latest.summary.top_priority_score)}
              detail={`${latest.summary.validated_score_count ?? 0} validated · ${
                latest.summary.provisional_score_count ?? 0
              } provisional`}
              icon={<Scale size={16} />}
            />
            <StatCard
              label="Run status"
              value={label(latest.status)}
              detail={latest.completed_at ? dateTime(latest.completed_at) : "Calculation in progress"}
              icon={<Sparkles size={16} />}
              tone={latest.status === "FAILED" ? "danger" : "default"}
            />
          </div>

          {latest.error && <div className="inline-message error">{latest.error}</div>}
          {(latest.summary.validation_warnings || []).length > 0 && (
            <div className="inline-message warning">
              {(latest.summary.validation_warnings || []).join(" ")}
            </div>
          )}

          <Card
            title="Factor priority ranking"
            hint="Rows are ordered by final priority. Expand a factor to inspect every component score and its deterministic evidence trail."
          >
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th />
                    <th>Rank</th>
                    <th>Factor</th>
                    <th>Final priority</th>
                    <th>Prevalence</th>
                    <th>Statistical</th>
                    <th>Representation</th>
                    <th>Semantic</th>
                    <th>Coverage</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {scores.map((item) => {
                    const isExpanded = expanded === item.factor_id;
                    return (
                      <Fragment key={item.factor_id}>
                        <tr
                          className="priority-row"
                          onClick={() => setExpanded(isExpanded ? null : item.factor_id)}
                        >
                          <td>{isExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                          <td>
                            <strong>{item.rank ?? "-"}</strong>
                          </td>
                          <td>
                            <div className="priority-factor-name">
                              <strong>{item.factor_name || "Unnamed factor"}</strong>
                              <span className="footnote">
                                {item.factor_id} · {item.dimension_id}
                                {!item.factor_name && " · Generate factor names in Narrative serialization"}
                              </span>
                            </div>
                          </td>
                          <td>
                            <strong>{score(item.final_priority_score)}</strong>
                            <ComponentBar scoreValue={item.final_priority_score} />
                          </td>
                          <td>{score(item.prevalence_score)}</td>
                          <td>{score(item.statistical_importance_score)}</td>
                          <td>{score(item.representation_strength_score)}</td>
                          <td>{score(item.semantic_coherence_score)}</td>
                          <td>{coverage(item.evidence_coverage)}</td>
                          <td>
                            <Badge tone={statusTone(item.score_status)}>{label(item.score_status)}</Badge>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr key={`${item.factor_id}-detail`} className="priority-detail-row">
                            <td colSpan={10}>
                              <FactorDetail
                                run={latest}
                                item={item}
                                assessment={assessments.get(item.factor_id)}
                                reviewer={reviewer}
                                note={note}
                                onReviewed={run.reload}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                  {!scores.length && (
                    <tr>
                      <td colSpan={10}>
                        <EmptyState
                          title="No factor scores yet"
                          detail="The run completed without scored factors. Check the factor run evidence and configuration."
                        />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      <Card title="Method notes" hint="Fixed deterministic rules used for every factor in the run.">
        <div className="priority-method-grid">
          <div>
            <strong>Prevalence</strong>
            <p>Share of canonical FAMD problems that are members of the factor.</p>
          </div>
          <div>
            <strong>Statistical importance</strong>
            <p>Factor eigenvalue divided by total FAMD inertia, expressed as a percentage.</p>
          </div>
          <div>
            <strong>Representation</strong>
            <p>Share of problems whose row contribution meets the expected mean-contribution threshold.</p>
          </div>
          <div>
            <strong>Semantic coherence</strong>
            <p>
              Mean concentration of journey, aspect, intent, symptom and banking-process attributes
              across represented problems.
            </p>
          </div>
        </div>
        <div className="priority-caveats">
          <AlertTriangle size={16} />
          <div>
            Priority scores rank evidence strength, not causal impact, revenue or customer harm. Signed
            FAMD directions are preserved and are not treated as good or bad.
          </div>
        </div>
      </Card>
    </div>
  );
}
