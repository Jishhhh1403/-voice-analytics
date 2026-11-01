import { Activity, Clock3, Play, RefreshCw, ShieldAlert, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Progress, Spinner, relationshipTone } from "../components/ui";
import { postJSON } from "../lib/api";
import { dateTime, label, number } from "../lib/format";
import type { PipelineRun } from "../lib/types";
import { usePolling } from "../lib/useFetch";

type AdminOverview = {
  runs: PipelineRun[];
  quarantine: { run_id: string; row_number: number; source_feedback_id?: string; error_reason: string; created_at: string }[];
  audit: { actor: string; action: string; entity_type: string; entity_id: string; created_at: string }[];
  backlog_uploads: { upload_id: string; filename: string; status: string; created_at: string }[];
  reports: { report_id: string; upload_id: string; reviewer_status: string; created_at: string }[];
};

export default function RunsPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const load = async () => {
    try {
      const response = await fetch("/api/v1/admin/overview");
      if (!response.ok) throw new Error(`Failed to load runs (${response.status})`);
      setData(await response.json());
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const active = Boolean(data?.runs.some((run) => ["queued", "running", "ingesting", "extracting"].includes(run.status)));
  usePolling(load, active, 2000);

  const startRun = async () => {
    setStarting(true);
    try {
      await postJSON("/feedback-pipelines", { force_rerun: false }, `runs-${Date.now()}`);
      await load();
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="Operations"
        title="Pipeline runs"
        subtitle="Every run is versioned, stage-tracked and auditable. Quarantined rows stay visible rather than being silently dropped."
        actions={
          <>
            <button className="btn btn-ghost" onClick={load} disabled={loading}>
              <RefreshCw size={15} className={loading ? "spin" : ""} />
              Refresh
            </button>
            <button className="btn btn-primary" onClick={startRun} disabled={starting}>
              <Play size={15} />
              {starting ? "Starting..." : "New feedback run"}
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}
      {loading && !data && <Spinner />}

      {data && (
        <>
          {data.runs.length === 0 && (
            <Card>
              <EmptyState title="No pipeline runs yet" detail="Start a feedback run to ingest the sample dataset." />
            </Card>
          )}

          <div className="run-list">
            {data.runs.map((run) => {
              const stages = run.stages || [];
              const progress =
                stages.length > 0
                  ? stages.filter((stage) => ["succeeded", "completed"].includes(stage.status)).length / stages.length
                  : run.status === "completed"
                    ? 1
                    : 0;
              return (
                <Card key={run.run_id} className="run-card">
                  <div className="run-card-head">
                    <div>
                      <div className="run-card-title">
                        <TerminalSquare size={16} />
                        <strong>{run.run_id}</strong>
                        <Badge tone={relationshipTone(run.status)}>{label(run.status)}</Badge>
                        <Badge tone="neutral">{run.run_type}</Badge>
                      </div>
                      <div className="run-meta">
                        <span>
                          <Clock3 size={13} />
                          {dateTime(run.created_at)}
                        </span>
                        <span>{run.source_filename || run.input_uri || "sample source"}</span>
                        <span className="mono">{run.input_generation?.slice(0, 14) || "local"}</span>
                      </div>
                    </div>
                    <div className="run-progress">
                      <span>{Math.round(progress * 100)}%</span>
                      <Progress
                        value={progress}
                        tone={run.status === "failed" ? "red" : run.status === "completed" ? "green" : "accent"}
                      />
                    </div>
                  </div>

                  {run.error && <div className="alert alert-error">{run.error}</div>}

                  {stages.length > 0 && (
                    <div className="stage-row">
                      {stages.map((stage) => (
                        <div className={`stage-chip stage-${stage.status}`} key={stage.stage}>
                          <span className="stage-dot" />
                          <span>{label(stage.stage)}</span>
                          <small>
                            {stage.processed > 0 ? `${number(stage.processed)} rows` : label(stage.status)}
                          </small>
                        </div>
                      ))}
                    </div>
                  )}

                  {Object.keys(run.summary || {}).length > 0 && (
                    <div className="run-summary">
                      {Object.entries(run.summary)
                        .filter(([, value]) => typeof value !== "object")
                        .slice(0, 8)
                        .map(([key, value]) => (
                          <div key={key}>
                            <span>{label(key)}</span>
                            <strong>{String(value)}</strong>
                          </div>
                        ))}
                    </div>
                  )}

                  {run.status === "completed" && (
                    <div className="run-links">
                      <Link to="/" className="btn btn-ghost btn-small">
                        <Activity size={13} />
                        Overview
                      </Link>
                      <Link to="/problems" className="btn btn-ghost btn-small">
                        Problems
                      </Link>
                      <Link to="/journey" className="btn btn-ghost btn-small">
                        Journey
                      </Link>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>

          <div className="grid grid-2">
            <Card title="Quarantined rows" hint="Rejected ingestion rows with reasons" className="table-card">
              {data.quarantine.length === 0 && <EmptyState title="No quarantined rows" />}
              {data.quarantine.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Run</th>
                        <th className="num">Row</th>
                        <th>Feedback</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.quarantine.map((row, index) => (
                        <tr key={`${row.run_id}-${row.row_number}-${index}`}>
                          <td className="mono">{row.run_id.slice(0, 12)}</td>
                          <td className="num">{row.row_number}</td>
                          <td>{row.source_feedback_id || "—"}</td>
                          <td>
                            <span className="quarantine-reason">
                              <ShieldAlert size={13} />
                              {row.error_reason}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            <Card title="Audit trail" hint="Recent privileged actions" className="table-card">
              {data.audit.length === 0 && <EmptyState title="No audit events" />}
              {data.audit.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Actor</th>
                        <th>Action</th>
                        <th>Entity</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.audit.map((event, index) => (
                        <tr key={`${event.created_at}-${index}`}>
                          <td>{dateTime(event.created_at)}</td>
                          <td>{event.actor}</td>
                          <td>
                            <Badge tone="blue">{event.action}</Badge>
                          </td>
                          <td className="mono">
                            {event.entity_type} / {event.entity_id.slice(0, 16)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
