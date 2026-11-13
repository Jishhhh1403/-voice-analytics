import { AlertTriangle, ArrowUpRight, Map, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner, StatCard, relationshipTone } from "../components/ui";
import { api } from "../lib/api";
import { label, number, percent } from "../lib/format";
import type { ThemeMapResponse, ThemeMapTheme } from "../lib/types";
import { useFetch } from "../lib/useFetch";

function bubbleColor(theme: ThemeMapTheme): string {
  const value = theme.priority_score;
  if (value === null || value === undefined) return "hsl(210, 10%, 62%)";
  const clamped = Math.max(0, Math.min(1, value));
  return `hsl(${210 - 202 * clamped}, 68%, 46%)`;
}

function growthStroke(theme: ThemeMapTheme): string {
  const growth = theme.volume_growth_pct;
  if (growth === null || growth === undefined) return "#94a3b8";
  if (growth >= 0.25) return "#cf3f2c";
  if (growth > 0) return "#d97706";
  if (growth <= -0.25) return "#0f9f7a";
  return "#64748b";
}

function score(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(2);
}

type BubbleProps = {
  cx?: number;
  cy?: number;
  payload?: ThemeMapTheme;
};

function Bubble({
  cx,
  cy,
  payload,
  maxVolume,
  selectedId,
  onSelect,
}: BubbleProps & {
  maxVolume: number;
  selectedId?: string;
  onSelect: (problemId: string) => void;
}) {
  if (!payload || cx === undefined || cy === undefined) return null;
  const volume = payload.evidence_volume || 0;
  const radius = 11 + 30 * Math.sqrt(volume / Math.max(1, maxVolume));
  const uncovered = payload.coverage_status === "uncovered" || payload.coverage_status === "needs_review";
  const selected = selectedId === payload.problem_id;
  return (
    <g
      onClick={() => onSelect(payload.problem_id)}
      style={{ cursor: "pointer" }}
      role="button"
      aria-label={`Select ${payload.title || payload.problem_id}`}
    >
      {selected && <circle cx={cx} cy={cy} r={radius + 5} fill="none" stroke="#17211d" strokeWidth={1.5} opacity={0.55} />}
      <circle
        cx={cx}
        cy={cy}
        r={radius}
        fill={bubbleColor(payload)}
        fillOpacity={0.82}
        stroke={growthStroke(payload)}
        strokeWidth={selected ? 3 : 1.8}
        strokeDasharray={uncovered ? "4 3" : undefined}
      />
      {volume > 0 && (
        <text x={cx} y={cy + 3.5} textAnchor="middle" fontSize={9} fontWeight={700} fill="#ffffff" pointerEvents="none">
          {volume > 99 ? "99+" : volume}
        </text>
      )}
    </g>
  );
}

function MapTooltip({ active, payload }: { active?: boolean; payload?: { payload?: ThemeMapTheme }[] }) {
  const theme = payload?.[0]?.payload;
  if (!active || !theme) return null;
  return (
    <div className="theme-map-tooltip">
      <strong>{theme.title || theme.problem_id}</strong>
      <span>{theme.journey_name || label(theme.journey_node_id) || "Unmapped"}</span>
      <div>
        <span>Evidence</span>
        <b>{number(theme.evidence_volume)}</b>
      </div>
      <div>
        <span>Negative share</span>
        <b>{percent(theme.negative_share)}</b>
      </div>
      <div>
        <span>Priority</span>
        <b>{score(theme.priority_score)}</b>
      </div>
      <div>
        <span>Coverage</span>
        <b>{label(theme.coverage_status)}</b>
      </div>
    </div>
  );
}

export default function ThemeMapPage() {
  const { data, loading, error, reload, setData } = useFetch<ThemeMapResponse>("/problem-map");
  const [selectedId, setSelectedId] = useState<string>();
  const [recomputing, setRecomputing] = useState(false);
  const [recomputeError, setRecomputeError] = useState<string | null>(null);

  const themes = data?.themes || [];
  const selected = themes.find((theme) => theme.problem_id === selectedId) || themes[0] || null;
  const maxVolume = Math.max(1, ...themes.map((theme) => theme.evidence_volume || 0));
  const extent = Math.max(
    1,
    ...themes.map((theme) => Math.max(Math.abs(theme.display_x), Math.abs(theme.display_y))),
  ) * 1.18;

  const recompute = async () => {
    setRecomputing(true);
    setRecomputeError(null);
    try {
      const next = await api<ThemeMapResponse>("/problem-map/recompute", { method: "POST" });
      setData(next);
      setSelectedId(undefined);
    } catch (err) {
      setRecomputeError(err instanceof Error ? err.message : "Could not rebuild the theme map");
    } finally {
      setRecomputing(false);
    }
  };

  if (loading && !data) return <Spinner label="Building theme map…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  if (!data || data.status !== "OK") {
    return (
      <div className="page">
        <PageHeader
          eyebrow="Semantic problem map"
          title="Theme map"
          subtitle="Canonical customer problems projected into two dimensions by semantic similarity."
          actions={
            <button className="btn btn-ghost" onClick={recompute} disabled={recomputing}>
              <RefreshCw size={15} className={recomputing ? "spin" : undefined} />
              Rebuild map
            </button>
          }
        />
        <Card>
          <EmptyState
            title={data?.status === "INSUFFICIENT_THEMES" ? "Not enough themes yet" : "Theme map unavailable"}
            detail={
              data?.status === "DISABLED"
                ? "MDS is disabled in this environment."
                : data?.status === "NO_RUN"
                  ? "Run a feedback pipeline before building a theme map."
                  : data?.notes?.[0] || "The map could not be computed for this run."
            }
          />
        </Card>
        {recomputeError && <ErrorState message={recomputeError} />}
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Semantic problem map"
        title="Theme map"
        subtitle="Each bubble is a canonical customer problem. Position means semantic similarity only; size shows evidence volume and colour shows priority."
        actions={
          <button className="btn btn-ghost" onClick={recompute} disabled={recomputing}>
            <RefreshCw size={15} className={recomputing ? "spin" : undefined} />
            {recomputing ? "Rebuilding…" : "Rebuild map"}
          </button>
        }
      />

      <div className="theme-map-stats">
        <StatCard label="Themes mapped" value={number(data.n_themes)} detail={data.methodology_version} icon={<Map size={17} />} tone="accent" />
        <StatCard
          label="MDS stress"
          value={data.stress === null || data.stress === undefined ? "-" : data.stress.toFixed(3)}
          detail={`${label(data.stress_status) || "unknown"} fit`}
          icon={<ShieldCheck size={17} />}
          tone={data.stress_status === "poor" ? "warning" : "default"}
        />
        <StatCard
          label="Uncovered themes"
          value={number(data.coverage_summary.uncovered || 0)}
          detail={`${number(data.coverage_summary.needs_review || 0)} need review`}
          icon={<AlertTriangle size={17} />}
          tone={(data.coverage_summary.uncovered || 0) > 0 ? "warning" : "default"}
        />
        <StatCard
          label="Escalations"
          value={number(themes.filter((theme) => theme.escalation_status === "ESCALATE").length)}
          detail="Customer-evidence escalation"
          icon={<ArrowUpRight size={17} />}
          tone="danger"
        />
      </div>

      <div className="theme-map-layout">
        <Card
          className="theme-map-card"
          title="Semantic space"
          hint="Bubble colour shows priority. Click a bubble to inspect its evidence, priority and backlog coverage."
        >
          <div className="theme-map-canvas">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 18, right: 18, left: 18, bottom: 18 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis
                  type="number"
                  dataKey="display_x"
                  name="MDS 1"
                  domain={[-extent, extent]}
                  tick={false}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  type="number"
                  dataKey="display_y"
                  name="MDS 2"
                  domain={[-extent, extent]}
                  tick={false}
                  axisLine={false}
                  tickLine={false}
                />
                <ZAxis dataKey="evidence_volume" range={[60, 520]} />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} content={<MapTooltip />} />
                <Scatter
                  data={themes}
                  shape={(props: BubbleProps) => (
                    <Bubble
                      {...props}
                      maxVolume={maxVolume}
                      selectedId={selected?.problem_id}
                      onSelect={setSelectedId}
                    />
                  )}
                />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="theme-map-legend">
            <span>
              <i className="legend-priority" /> low → high priority
            </span>
            <span>
              <i className="legend-bubble small" /> low evidence
            </span>
            <span>
              <i className="legend-bubble large" /> high evidence
            </span>
            <span>
              <i className="legend-line growth" /> rising volume
            </span>
            <span>
              <i className="legend-line uncovered" /> uncovered / needs review
            </span>
            <span className="theme-map-note">{data.notes[0]}</span>
          </div>
          {recomputeError && <ErrorState message={recomputeError} />}
        </Card>

        <Card className="theme-detail-card" title="Selected theme" hint={selected ? selected.problem_id : "Select a bubble"}>
          {selected ? (
            <div className="theme-detail">
              <div>
                <h3>{selected.title}</h3>
                <div className="theme-detail-tags">
                  <Badge tone="blue">{selected.journey_name || label(selected.journey_node_id) || "Unmapped"}</Badge>
                  <Badge tone={relationshipTone(selected.escalation_status || "neutral")}>
                    {label(selected.escalation_status || "not escalated")}
                  </Badge>
                  <Badge tone={relationshipTone(selected.coverage_status)}>{label(selected.coverage_status)}</Badge>
                </div>
              </div>
              <p>{selected.canonical_description || selected.problem_statement}</p>
              <div className="theme-detail-grid">
                <div>
                  <span>Evidence</span>
                  <strong>{number(selected.evidence_volume)}</strong>
                </div>
                <div>
                  <span>Customers</span>
                  <strong>{number(selected.distinct_customers)}</strong>
                </div>
                <div>
                  <span>Negative share</span>
                  <strong>{percent(selected.negative_share)}</strong>
                </div>
                <div>
                  <span>Volume growth</span>
                  <strong>{percent(selected.volume_growth_pct)}</strong>
                </div>
                <div>
                  <span>Priority</span>
                  <strong>{score(selected.priority_score)}</strong>
                </div>
                <div>
                  <span>Rank</span>
                  <strong>{selected.priority_rank ?? "-"}</strong>
                </div>
              </div>
              <div className="theme-component-bars">
                {[
                  ["Customer impact", selected.customer_impact_score],
                  ["Business risk", selected.business_risk_score],
                  ["Operational impact", selected.operational_impact_score],
                  ["Trend", selected.trend_score],
                  ["Strategic", selected.strategic_score],
                ].map(([name, value]) => (
                  <div className="theme-component" key={String(name)}>
                    <span>{name}</span>
                    <div className="theme-component-track">
                      <i style={{ width: `${Math.max(0, Math.min(1, Number(value) || 0)) * 100}%` }} />
                    </div>
                    <strong>{score(Number(value))}</strong>
                  </div>
                ))}
              </div>
              <div className="theme-neighbors">
                <div className="theme-section-title">Most similar themes</div>
                {selected.neighbors.length === 0 && <p className="muted">No neighbours available.</p>}
                {selected.neighbors.map((neighbor) => (
                  <button
                    className="theme-neighbor"
                    key={neighbor.problem_id}
                    onClick={() => setSelectedId(neighbor.problem_id)}
                  >
                    <span>{neighbor.title || neighbor.problem_id}</span>
                    <strong>{percent(neighbor.cosine_similarity)}</strong>
                  </button>
                ))}
              </div>
              <div className="theme-detail-actions">
                <Link className="btn btn-ghost btn-small" to={`/problems/${selected.problem_id}`}>
                  Open problem evidence
                  <ArrowUpRight size={14} />
                </Link>
                {selected.coverage_report_id && (
                  <Link className="btn btn-ghost btn-small" to={`/reports/${selected.coverage_report_id}`}>
                    Open validation report
                  </Link>
                )}
              </div>
            </div>
          ) : (
            <EmptyState title="Select a bubble" detail="The side panel shows evidence, priority and backlog coverage." />
          )}
        </Card>
      </div>

      <p className="footnote">
        {data.notes.join(" ")} Stress indicates how well two dimensions preserve the full semantic distances; it is not
        a measure of business risk.
      </p>
    </div>
  );
}
