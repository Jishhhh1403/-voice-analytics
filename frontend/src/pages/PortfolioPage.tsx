import {
  AlertTriangle,
  BrainCircuit,
  FlaskConical,
  Play,
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
import {
  coefficientMatrixPath,
  generateNarrativeSerialization,
  narrativeSerializationPath,
} from "../lib/api";
import { dateTime, label, number, percent } from "../lib/format";
import type {
  DimensionCoefficientMatrix,
  DimensionNarrativeSerializationResponse,
  DimensionStatus,
} from "../lib/types";
import { useFetch } from "../lib/useFetch";

function narrativeTone(status?: string | null) {
  switch (status) {
    case "COMPLETED":
      return "green" as const;
    case "FAILED":
    case "UNAVAILABLE":
      return "red" as const;
    default:
      return "neutral" as const;
  }
}

function score(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(4);
}

function variance(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(1)}%`;
}

export default function PortfolioPage() {
  const dimensions = useFetch<DimensionStatus>("/problem-dimensions/status");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const matrix = useFetch<DimensionCoefficientMatrix>(
    selectedRunId ? coefficientMatrixPath(selectedRunId) : null,
    [selectedRunId],
  );
  const serialization = useFetch<DimensionNarrativeSerializationResponse>(
    selectedRunId ? narrativeSerializationPath(selectedRunId) : null,
    [selectedRunId],
  );

  useEffect(() => {
    if (selectedRunId || !dimensions.data?.latest_runs?.length) return;
    setSelectedRunId(dimensions.data.latest_runs[0].run_id);
  }, [dimensions.data, selectedRunId]);

  const selectedRun = useMemo(
    () => dimensions.data?.latest_runs.find((item) => item.run_id === selectedRunId),
    [dimensions.data, selectedRunId],
  );

  const matrixDimensions = matrix.data?.dimensions || [];
  const problemIds = useMemo(
    () => Array.from(new Set((matrix.data?.coefficients || []).map((item) => item.problem_id))),
    [matrix.data],
  );
  const coefficientLookup = useMemo(
    () => new Map((matrix.data?.coefficients || []).map((item) => [`${item.problem_id}:${item.dimension_id}`, item])),
    [matrix.data],
  );

  const record = serialization.data?.serialization;
  const narrative = record?.payload;
  const factors = narrative?.factors || [];
  const canGenerate = Boolean(serialization.data?.available && selectedRunId) && !generating;

  const generate = async () => {
    if (!selectedRunId) return;
    setGenerating(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const response = (await generateNarrativeSerialization(
        selectedRunId,
      )) as DimensionNarrativeSerializationResponse;
      serialization.setData(response);
      if (response.serialization?.status === "COMPLETED") {
        setActionMessage(
          `The LangChain agent named and described ${response.serialization.payload.total_factors ?? 0} factors from ${response.serialization.payload.total_problems ?? 0} problem equations.`,
        );
        matrix.reload();
      } else {
        setActionError(response.serialization?.error || "Factor narrative serialization did not complete.");
      }
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  if (dimensions.loading && !dimensions.data) return <Spinner label="Loading factor analysis runs…" />;
  if (dimensions.error) return <ErrorState message={dimensions.error} onRetry={dimensions.reload} />;
  if (!dimensions.data) return null;
  if (!dimensions.data.enabled) {
    return (
      <div className="page">
        <PageHeader eyebrow="Problem portfolio intelligence" title="Narrative serialization" />
        <Card>
          <EmptyState
            title="Problem dimension analysis is disabled"
            detail="Set ENABLE_PROBLEM_DIMENSIONS=true to enable factor analysis and narrative serialization."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Problem portfolio intelligence"
        title="Narrative serialization"
        subtitle="All identified problems and factor coefficients for one factor-analysis run. The LangChain agent names and describes every factor from the complete problem equations and the repository banking taxonomy."
        actions={
          <div className="header-badges">
            <Badge tone={serialization.data?.available ? "blue" : "amber"}>
              {serialization.data?.available ? "Narrative agent available" : "Narrative agent unavailable"}
            </Badge>
          </div>
        }
      />

      <div className="theme-map-stats">
        <StatCard
          label="Problems identified"
          value={number(problemIds.length)}
          detail="Complete customer problem population"
          icon={<FlaskConical size={17} />}
        />
        <StatCard
          label="Factors"
          value={number(matrixDimensions.length)}
          detail="Retained factors in the selected run"
          icon={<BrainCircuit size={17} />}
        />
        <StatCard
          label="Factor narrative"
          value={record ? label(record.status) : "Not generated"}
          detail={record ? `${record.model_name || "LLM"} · ${factors.length} named factors` : "Run the agent to generate all factor narratives"}
          icon={<Sparkles size={17} />}
          tone={record?.status === "COMPLETED" ? "accent" : "default"}
        />
        <StatCard
          label="Selected run"
          value={selectedRun ? label(selectedRun.status) : "-"}
          detail={selectedRunId || "No factor-analysis run selected"}
          icon={<ShieldCheck size={17} />}
        />
      </div>

      <div className="grid grid-main">
        <div className="stack">
          <Card
            title="Customer problem factor coefficients"
            hint="Signed FAMD coefficients for the selected factor-analysis run. Every identified problem is shown; no problem is sampled or omitted."
            actions={
              <button className="btn btn-primary btn-small" onClick={generate} disabled={!canGenerate}>
                <Sparkles size={14} />
                {generating ? "Serializing factors…" : "Run narrative serialization of factors identified"}
              </button>
            }
          >
            {actionMessage && <p className="form-success">{actionMessage}</p>}
            {actionError && <p className="form-error">{actionError}</p>}
            {serialization.data && !serialization.data.available && (
              <p className="dimension-warning">
                <AlertTriangle size={14} />
                No LangChain chat model is configured. Set the problem-dimension LLM provider to enable factor narrative generation.
              </p>
            )}
            {matrix.loading && !matrix.data && <Spinner label="Loading coefficients…" />}
            {matrix.error && <ErrorState message={matrix.error} onRetry={matrix.reload} />}
            {matrix.data && problemIds.length === 0 && (
              <EmptyState
                title="No coefficients available"
                detail="Run factor analysis to generate problem-factor coefficients."
              />
            )}
            {matrix.data && problemIds.length > 0 && (
              <>
                <div className="dimension-coefficient-table-wrap">
                  <table className="dimension-coefficient-table">
                    <thead>
                      <tr>
                        <th>Problem</th>
                        {matrixDimensions.map((dimension) => (
                          <th key={dimension.dimension_id}>
                            <span className="mono">{dimension.factor_id}</span>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {problemIds.map((problemId) => (
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
                                    <strong
                                      className={
                                        cell.coefficient < 0 ? "coefficient-negative" : "coefficient-positive"
                                      }
                                    >
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
                  Showing all {problemIds.length} identified problems across {matrixDimensions.length} factors.{" "}
                  {matrix.data.share_definition}
                </p>
                <p className="dimension-warning">
                  <AlertTriangle size={14} />
                  {matrix.data.interpretation_warning}
                </p>
              </>
            )}
          </Card>

          {!record && (
            <Card title="Factors identified">
              <EmptyState
                title="Factor narrative not generated"
                detail="Use the button above to run the LangChain agent over all problem equations, factor coefficients and the repository banking taxonomy."
              />
            </Card>
          )}

          {record && record.status !== "COMPLETED" && (
            <Card
              title="Factors identified"
              actions={<Badge tone={narrativeTone(record.status)}>{label(record.status)}</Badge>}
            >
              <EmptyState
                title={label(record.status)}
                detail={record.error || narrative?.reason || "The factor narrative agent did not return a complete result."}
              />
            </Card>
          )}

          {record?.status === "COMPLETED" && narrative && (
            <Card
              title="Factors identified"
              hint="Factor names, descriptions and interpretations are generated by the LangChain agent from all problem equations and the banking taxonomy. Statistical metrics are merged from the FAMD run."
              actions={
                <Badge tone="green">
                  {number(narrative.total_factors ?? factors.length)} factors · {number(narrative.total_problems ?? problemIds.length)} problems
                </Badge>
              }
            >
              {narrative.summary && <p className="portfolio-narrative-summary">{narrative.summary}</p>}
              <div className="stack">
                {factors.map((factor) => (
                  <div className="portfolio-narrative-card" key={factor.factor_id}>
                    <div className="dimension-card-title">
                      <span className="mono">{factor.factor_id}</span>
                      <strong>{factor.name}</strong>
                      <Badge tone={factor.confidence >= 0.75 ? "green" : factor.confidence >= 0.5 ? "blue" : "amber"}>
                        {Math.round(factor.confidence * 100)}% confidence
                      </Badge>
                    </div>
                    <p>{factor.description}</p>
                    <p className="footnote">{factor.business_interpretation}</p>
                    <div className="dimension-chip-row">
                      <span className="dimension-chip">{factor.banking_domain}</span>
                      {factor.journey_scope && <span className="dimension-chip">{factor.journey_scope}</span>}
                    </div>
                    <div className="dimension-run-summary">
                      <div>
                        <span>Problems covered</span>
                        <strong>{number(factor.problem_count)}</strong>
                      </div>
                      <div>
                        <span>Problem share</span>
                        <strong>{percent(factor.problem_share_pct / 100)}</strong>
                      </div>
                      <div>
                        <span>Variance</span>
                        <strong>{variance(factor.explained_variance_pct)}</strong>
                      </div>
                      <div>
                        <span>Cumulative variance</span>
                        <strong>{variance(factor.cumulative_variance_pct)}</strong>
                      </div>
                      <div>
                        <span>Mean coefficient</span>
                        <strong>{score(factor.mean_coefficient)}</strong>
                      </div>
                      <div>
                        <span>Mean |coefficient|</span>
                        <strong>{score(factor.mean_abs_coefficient)}</strong>
                      </div>
                      <div>
                        <span>Min coefficient</span>
                        <strong>{score(factor.min_coefficient)}</strong>
                      </div>
                      <div>
                        <span>Max coefficient</span>
                        <strong>{score(factor.max_coefficient)}</strong>
                      </div>
                      <div>
                        <span>Max |coefficient|</span>
                        <strong>{score(factor.max_abs_coefficient)}</strong>
                      </div>
                    </div>
                    {factor.top_features.length > 0 && (
                      <div className="dimension-chip-row">
                        {factor.top_features.map((feature) => (
                          <span className="dimension-chip" key={`${factor.factor_id}-${feature.feature_name}`}>
                            {label(feature.feature_name)}
                            <strong>{feature.direction_summary || "±"}</strong>
                            <small>{percent(feature.contribution_pct / 100)}</small>
                          </span>
                        ))}
                      </div>
                    )}
                    <p className="footnote">
                      <strong>Positive problem pattern:</strong> {factor.positive_problem_pattern}
                    </p>
                    <p className="footnote">
                      <strong>Negative problem pattern:</strong> {factor.negative_problem_pattern}
                    </p>
                    <p className="footnote">
                      <strong>Core customer experience:</strong> {factor.core_customer_experience}
                    </p>
                    {factor.representative_problem_ids.length > 0 && (
                      <div className="dimension-chip-row">
                        {factor.representative_problem_ids.map((problemId) => (
                          <span className="dimension-chip" key={`${factor.factor_id}-${problemId}`}>
                            <Link to={`/problems/${problemId}`}>{problemId}</Link>
                          </span>
                        ))}
                      </div>
                    )}
                    <p className="footnote">{factor.confidence_explanation}</p>
                  </div>
                ))}
              </div>
              <p className="footnote">
                Grounded with taxonomy {narrative.taxonomy_version || "-"} · prompt {record.prompt_version} · agent{" "}
                {record.agent_version || "-"}
              </p>
            </Card>
          )}
        </div>

        <div className="stack">
          <Card title="Run history" hint="Latest factor-analysis runs available for coefficient and narrative serialization.">
            {dimensions.data.latest_runs.length === 0 && (
              <EmptyState
                title="No factor-analysis runs"
                detail="Run factor analysis to create the first coefficient matrix."
              />
            )}
            <div className="dimension-run-list">
              {dimensions.data.latest_runs.map((item) => (
                <button
                  key={item.run_id}
                  className={`dimension-run-item ${selectedRunId === item.run_id ? "active" : ""}`}
                  onClick={() => {
                    setSelectedRunId(item.run_id);
                    setActionError(null);
                    setActionMessage(null);
                  }}
                >
                  <strong className="mono">{item.run_id}</strong>
                  <span>
                    <Badge tone={relationshipTone(item.status)}>{label(item.status)}</Badge>
                    <small>{dateTime(item.created_at)}</small>
                  </span>
                  <small>{item.feedback_run_id || "No feedback run"}</small>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
