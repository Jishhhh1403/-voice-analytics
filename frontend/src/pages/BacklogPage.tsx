import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  FlaskConical,
  RefreshCw,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Progress, Spinner } from "../components/ui";
import { postForm, postJSON } from "../lib/api";
import { dateTime, label, number } from "../lib/format";
import type { BacklogUpload, PipelineRun, Report } from "../lib/types";
import { useFetch, usePolling } from "../lib/useFetch";

type ReportListItem = {
  report_id: string;
  upload_id: string;
  run_id: string;
  reviewer_status: string;
  created_at: string;
  filename?: string;
  summary: Record<string, any>;
};

export default function BacklogPage() {
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploads, setUploads] = useState<BacklogUpload[]>([]);
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [validationRun, setValidationRun] = useState<PipelineRun | null>(null);
  const [working, setWorking] = useState(false);
  const [loadingList, setLoadingList] = useState(true);

  const detail = useFetch<BacklogUpload>(selected ? `/backlog-uploads/${selected}` : null, [selected]);

  const loadLists = async () => {
    setLoadingList(true);
    try {
      const [uploadResponse, reportResponse] = await Promise.all([
        fetch("/api/v1/backlog-uploads").then((response) => response.json()),
        fetch("/api/v1/backlog-validation-reports").then((response) => response.json()),
      ]);
      setUploads(uploadResponse);
      setReports(reportResponse);
      if (!selected && uploadResponse.length > 0) setSelected(uploadResponse[0].upload_id);
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => {
    loadLists();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  usePolling(
    async () => {
      if (!validationRun) return;
      const run = await fetch(`/api/v1/backlog-validation-runs/${validationRun.run_id}`).then((response) => response.json());
      setValidationRun(run);
      if (run.status === "completed" && run.report_id) {
        navigate(`/reports/${run.report_id}`);
      }
      if (run.status === "failed") setWorking(false);
    },
    Boolean(validationRun && (validationRun.status === "queued" || validationRun.status === "running")),
    1500,
  );

  const upload = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await postForm<BacklogUpload>("/backlog-uploads", form);
      setSelected(result.upload_id);
      await loadLists();
    } catch (err) {
      setUploadError((err as Error).message);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const loadSample = async () => {
    setUploading(true);
    setUploadError(null);
    try {
      const result = await postJSON<BacklogUpload>("/backlog-uploads/sample", {});
      setSelected(result.upload_id);
      await loadLists();
    } catch (err) {
      setUploadError((err as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const validate = async () => {
    if (!selected) return;
    setWorking(true);
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

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) upload(file);
  };

  const onSelectFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) upload(file);
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="Backlog validation"
        title="Test the backlog against customer evidence"
        subtitle="Upload existing backlog items as CSV. The platform validates alignment, coverage gaps and acceptance-criteria gaps. It does not reprioritise or edit your backlog."
        actions={
          <>
            <a className="btn btn-ghost" href="/api/v1/backlog-template" download>
              <Download size={15} />
              CSV template
            </a>
            <button className="btn btn-primary" onClick={() => fileInput.current?.click()} disabled={uploading}>
              <UploadCloud size={15} />
              {uploading ? "Uploading…" : "Upload backlog"}
            </button>
          </>
        }
      />

      <input ref={fileInput} type="file" accept=".csv,text/csv" hidden onChange={onSelectFile} />

      <div className="grid grid-upload">
        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => fileInput.current?.click()}
        >
          <div className="dropzone-icon">
            <FileSpreadsheet size={28} />
          </div>
          <strong>Drop a backlog CSV here</strong>
          <span>Required columns: backlog_id, title, description. Optional: acceptance_criteria, product_area, priority, business_goal, source_system.</span>
          <div className="dropzone-actions">
            <span className="btn btn-ghost btn-small">Browse file</span>
            <button
              className="btn btn-ghost btn-small"
              onClick={(event) => {
                event.stopPropagation();
                loadSample();
              }}
              disabled={uploading}
            >
              <FlaskConical size={13} />
              Load sample backlog
            </button>
          </div>
        </div>

        <Card title="What gets validated" hint="Evidence alignment is separate from business priority">
          <ul className="policy-list">
            <li>Intent, problem and journey alignment against canonical problems.</li>
            <li>Acceptance-criteria coverage of the reported failure modes.</li>
            <li>Supporting feedback IDs and exact redacted evidence spans.</li>
            <li>High-evidence customer problems not addressed by the backlog.</li>
            <li>Uncertain or conflicting evidence is marked NEEDS_REVIEW.</li>
          </ul>
        </Card>
      </div>

      {uploadError && <div className="alert alert-error">{uploadError}</div>}

      <div className="grid grid-backlog">
        <Card title="Uploads" hint="Immutable source objects retained for audit" className="table-card">
          {loadingList && <Spinner />}
          {!loadingList && uploads.length === 0 && <EmptyState title="No backlog uploads yet" />}
          {uploads.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>File</th>
                    <th className="num">Rows</th>
                    <th>Status</th>
                    <th>Uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {uploads.map((uploadItem) => (
                    <tr
                      key={uploadItem.upload_id}
                      className={selected === uploadItem.upload_id ? "selected-row" : ""}
                      onClick={() => {
                        setSelected(uploadItem.upload_id);
                        setValidationRun(null);
                      }}
                    >
                      <td>
                        <div className="cell-title">{uploadItem.filename}</div>
                        <div className="cell-sub">{uploadItem.upload_id}</div>
                      </td>
                      <td className="num">
                        {uploadItem.valid_rows}/{uploadItem.total_rows}
                      </td>
                      <td>
                        <Badge
                          tone={
                            uploadItem.status === "validated"
                              ? "green"
                              : uploadItem.status === "validating"
                                ? "amber"
                                : "red"
                          }
                        >
                          {label(uploadItem.status)}
                        </Badge>
                      </td>
                      <td>{dateTime(uploadItem.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Validation reports" hint="Downloadable JSON and CSV" className="table-card">
          {reports.length === 0 && <EmptyState title="No reports yet" detail="Validate an uploaded backlog to create one." />}
          {reports.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Report</th>
                    <th>Source file</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {reports.map((report) => (
                    <tr key={report.report_id}>
                      <td>
                        <div className="cell-title">{report.report_id}</div>
                        <div className="cell-sub">{dateTime(report.created_at)}</div>
                      </td>
                      <td>{report.filename || report.upload_id}</td>
                      <td>
                        <Badge tone={label(report.reviewer_status) === "Pending" ? "amber" : "green"}>
                          {label(report.reviewer_status)}
                        </Badge>
                      </td>
                      <td>
                        <Link to={`/reports/${report.report_id}`} className="btn btn-ghost btn-small">
                          Open
                          <ArrowRight size={13} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

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
