import { AlertTriangle, CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Progress, Spinner } from "../components/ui";
import { postJSON } from "../lib/api";
import { label, number } from "../lib/format";
import type { BacklogUpload, PipelineRun } from "../lib/types";
import { useFetch, usePolling } from "../lib/useFetch";

export default function BacklogPage() {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [validationRun, setValidationRun] = useState<PipelineRun | null>(null);
  const [working, setWorking] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const detail = useFetch<BacklogUpload>(selected ? `/backlog-uploads/${selected}` : null, [selected]);

  useEffect(() => {
    fetch("/api/v1/backlog-uploads")
      .then((response) => response.json())
      .then((uploads: BacklogUpload[]) => {
        if (uploads.length > 0) setSelected(uploads[0].upload_id);
      })
      .catch(() => undefined)
      .finally(() => setLoadingList(false));
  }, []);

  usePolling(
    async () => {
      if (!validationRun) return;
      const run = await fetch(`/api/v1/backlog-validation-runs/${validationRun.run_id}`).then((response) =>
        response.json(),
      );
      setValidationRun(run);
      if (run.status === "completed" && run.report_id) {
        navigate(`/reports/${run.report_id}`);
      }
      if (run.status === "failed") setWorking(false);
    },
    Boolean(validationRun && (validationRun.status === "queued" || validationRun.status === "running")),
    1500,
  );

  const validate = async () => {
    if (!selected) return;
    setWorking(true);
    setUploadError(null);
    try {
      const run = await postJSON<{ run_id: string; status: string; correlation_id: string }>(
        `/backlog-uploads/${selected}/validate`,
        { force_rerun: true },
        `validate-${selected}-${Date.now()}`,
      );
      setValidationRun({
        run_id: run.run_id,
        tenant_id: "",
        run_type: "backlog_validation",
        status: "queued",
        created_at: new Date().toISOString(),
        summary: {},
        stages: [],
      });
    } catch (err) {
      setUploadError((err as Error).message);
      setWorking(false);
    }
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="Backlog validation"
        title="Validate a backlog against customer problems"
        subtitle="Inspect the uploaded backlog and check whether each item is supported by customer evidence. The platform does not reprioritise or edit your backlog."
      />

      {loadingList && <Spinner label="Loading backlog upload…" />}
      {!loadingList && !selected && (
        <Card>
          <EmptyState title="No backlog upload available" detail="Upload a backlog through the API to validate it here." />
        </Card>
      )}

      {uploadError && <div className="alert alert-error">{uploadError}</div>}
      {detail.error && <ErrorState message={detail.error} onRetry={detail.reload} />}
      {detail.loading && !detail.data && <Spinner />}

      {detail.data && (
        <Card
          title={`Upload detail · ${detail.data.filename}`}
          hint={`Object ${detail.data.source_uri} @ ${detail.data.generation.slice(0, 16)}`}
          actions={
            <div className="card-actions">
              <button className="btn btn-ghost btn-small" onClick={detail.reload}>
                <RefreshCw size={13} />
                Refresh
              </button>
              <button
                className="btn btn-primary btn-small"
                onClick={validate}
                disabled={working || detail.data.valid_rows === 0}
              >
                <CheckCircle2 size={14} />
                {working ? "Validating…" : "Validate against customer problems"}
              </button>
            </div>
          }
        >
          <div className="upload-summary">
            <div>
              <span>Valid rows</span>
              <strong>{number(detail.data.valid_rows)}</strong>
            </div>
            <div>
              <span>Invalid rows</span>
              <strong>{number(detail.data.invalid_rows)}</strong>
            </div>
            <div>
              <span>Status</span>
              <Badge tone={detail.data.status === "validated" ? "green" : "amber"}>{label(detail.data.status)}</Badge>
            </div>
            <div>
              <span>Generation</span>
              <strong className="mono">{detail.data.generation.slice(0, 14)}</strong>
            </div>
          </div>

          {validationRun && (
            <div className="validation-live">
              <div>
                <span className="pulse-dot" />
                Validation run <strong>{validationRun.run_id}</strong>
                <Badge tone={validationRun.status === "completed" ? "green" : "amber"}>{validationRun.status}</Badge>
              </div>
              <Progress value={validationRun.status === "completed" ? 1 : 0.55} tone="accent" />
            </div>
          )}

          {detail.data.errors.length > 0 && (
            <div className="alert alert-error">
              <div className="alert-head">
                <XCircle size={16} />
                {detail.data.errors.length} row-level error(s)
              </div>
              <ul>
                {detail.data.errors.map((row, index) => (
                  <li key={index}>
                    Row {row.row_number} ({row.backlog_id || "no id"}): {row.errors.join(", ")}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {detail.data.warnings.length > 0 && (
            <div className="alert alert-warning">
              <div className="alert-head">
                <AlertTriangle size={16} />
                Upload warnings
              </div>
              <ul>
                {detail.data.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Title</th>
                  <th>Product area</th>
                  <th>Priority</th>
                  <th>Acceptance criteria</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.items.map((item) => (
                  <tr key={item.backlog_id}>
                    <td className="mono">{item.backlog_id}</td>
                    <td>
                      <div className="cell-title">{item.title}</div>
                      <div className="cell-sub">{item.description}</div>
                    </td>
                    <td>{item.product_area || "—"}</td>
                    <td>{item.priority || "—"}</td>
                    <td className="criteria-cell">{item.acceptance_criteria || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
