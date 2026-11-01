import {
  ArrowUpRight,
  BrainCircuit,
  CircleAlert,
  Database,
  GitBranch,
  MessageSquareText,
  Play,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import * as Charts from "../components/Charts";
import FilterBar from "../components/FilterBar";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton, StatCard } from "../components/ui";
import { postJSON } from "../lib/api";
import { dateTime, number } from "../lib/format";
import type { Summary } from "../lib/types";
import { useFetch } from "../lib/useFetch";

export default function OverviewPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [starting, setStarting] = useState(false);
  const query = params.toString();
  const { data, loading, error, reload } = useFetch<Summary>(`/feedback/summary${query ? `?${query}` : ""}`, [query]);

  const startPipeline = async () => {
    setStarting(true);
    try {
      await postJSON("/feedback-pipelines", { force_rerun: false }, `overview-${Date.now()}`);
      navigate("/runs");
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="Customer intelligence"
        title="Evidence before opinion"
        subtitle="See what customers are actually struggling with, how strongly it is evidenced, and which backlog items genuinely address it."
        actions={
          <>
            <button className="btn btn-ghost" onClick={reload} disabled={loading}>
              <RefreshCw size={15} className={loading ? "spin" : ""} />
              Refresh
            </button>
            <button className="btn btn-primary" onClick={startPipeline} disabled={starting}>
              <Play size={15} />
              {starting ? "Starting…" : "Run feedback pipeline"}
            </button>
          </>
        }
      />

      <FilterBar />

      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && (
        <div className="grid grid-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Card key={index}>
              <Skeleton rows={3} />
            </Card>
          ))}
        </div>
      )}

      {data && data.total_feedback === 0 && (
        <Card>
          <EmptyState
            title="No completed feedback run yet"
            detail="The sample pipeline may still be processing. Check Pipeline runs, or start a new run."
          />
        </Card>
      )}

      {data && data.total_feedback > 0 && (
        <>
          <div className="grid grid-4">
            <StatCard
              label="Feedback processed"
              value={number(data.total_feedback)}
              detail={`${number(data.total_insights)} evidence spans extracted`}
              icon={<MessageSquareText size={18} />}
              tone="accent"
            />
            <StatCard
              label="Canonical problems"
              value={number(data.total_problems)}
              detail={`${number(data.unmapped_problems)} awaiting taxonomy review`}
              icon={<CircleAlert size={18} />}
              tone="warning"
            />
            <StatCard
              label="Journeys covered"
              value={number(data.journey_breakdown.filter((item) => item.journey_node_id !== "unmapped").length)}
              detail="Hybrid taxonomy mapping"
              icon={<GitBranch size={18} />}
            />
            <StatCard
              label="Latest source run"
              value={<span className="stat-run">{data.run_id?.slice(0, 16) || "—"}</span>}
              detail={data.latest_run?.finished_at ? `Completed ${dateTime(data.latest_run.finished_at)}` : "In progress"}
              icon={<Database size={18} />}
            />
          </div>

          <div className="grid grid-main">
            <Card title="Feedback volume trend" hint="Monthly counts from the latest completed run">
              <Charts.TrendChart data={data.trend} />
            </Card>

            <Card title="Top problem themes" hint="Ranked by evidence volume, not by assumed severity">
              <div className="problem-mini-list">
                {data.top_problems.length === 0 && <EmptyState title="No problems found" />}
                {data.top_problems.map((problem, index) => (
                  <Link to={`/problems/${problem.problem_id}`} className="problem-mini" key={problem.problem_id}>
                    <span className="rank">{String(index + 1).padStart(2, "0")}</span>
                    <span className="problem-mini-body">
                      <strong>{problem.title}</strong>
                      <span>{problem.journey_node_id?.replace(/\./g, " / ") || "Unmapped"}</span>
                    </span>
                    <span className="problem-mini-count">
                      {number(problem.evidence_count)}
                      <small>mentions</small>
                    </span>
                    <ArrowUpRight size={16} />
                  </Link>
                ))}
              </div>
            </Card>
          </div>

          <div className="grid grid-2">
            <Card title="Sentiment by journey" hint="Aspect-level sentiment, grouped by banking module">
              <Charts.SentimentJourneyChart data={data.sentiment_by_journey} />
            </Card>
            <Card title="Feedback sources" hint="Source distribution after deduplication">
              <Charts.SourceDonut data={data.source_mix} />
            </Card>
          </div>

          <div className="grid grid-2">
            <Card title="Rating distribution" hint="Ratings are source metadata, not model output">
              <Charts.RatingBars data={data.rating_mix} />
            </Card>
            <Card
              title="Run health"
              hint="Pipeline provenance"
              actions={
                <Link className="btn btn-ghost btn-small" to="/runs">
                  View runs
                </Link>
              }
            >
              <div className="run-health">
                <div>
                  <span>Run ID</span>
                  <strong>{data.run_id || "—"}</strong>
                </div>
                <div>
                  <span>Source object</span>
                  <strong className="mono">{data.latest_run?.input_uri || "local sample"}</strong>
                </div>
                <div>
                  <span>Generation</span>
                  <strong className="mono">{data.latest_run?.input_generation?.slice(0, 16) || "—"}</strong>
                </div>
                <div>
                  <span>Status</span>
                  <Badge tone="green">{data.latest_run?.status || "unknown"}</Badge>
                </div>
              </div>
              <div className="insight-note">
                <BrainCircuit size={16} />
                <span>
                  Every problem links back to exact redacted evidence spans. Similarity is used only for retrieval;
                  grouping adds journey and failure-mode checks.
                </span>
              </div>
            </Card>
          </div>

          <div className="journey-strip">
            {data.journey_breakdown.slice(0, 12).map((item) => (
              <Link key={item.journey_node_id} to={`/problems?journey=${item.journey_node_id}`} className="journey-chip">
                <Sparkles size={14} />
                <span>{item.journey_node_id.replace(/\./g, " / ")}</span>
                <strong>{item.problems}</strong>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
