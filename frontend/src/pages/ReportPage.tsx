import { ArrowLeft, Download, FileJson, FileText, Quote, ShieldAlert, Star } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner, relationshipTone } from "../components/ui";
import { download, postJSON } from "../lib/api";
import { date, dateTime, label, number } from "../lib/format";
import type { Report } from "../lib/types";
import { useFetch } from "../lib/useFetch";

const ALIGNMENTS = ["strong", "partial", "weak", "unsupported", "needs_review"];

export default function ReportPage() {
  const { reportId } = useParams();
  const { data, loading, error, reload } = useFetch<Report>(reportId ? `/backlog-validation-reports/${reportId}` : null, [
    reportId,
  ]);
  const [reviewer, setReviewer] = useState("product-owner");
  const [decision, setDecision] = useState("accepted");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!reportId) return;
    setSaving(true);
    setMessage(null);
    setReviewError(null);
    try {
      await postJSON(`/backlog-validation-reports/${reportId}/review`, { reviewer, decision, note });
      setMessage("Product-owner decision recorded.");
      setNote("");
      reload();
    } catch (err) {
      setReviewError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) return <Spinner label="Loading validation report..." />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const report = data.report;
  const summary = report.summary;
  const relationships = (summary.relationships || {}) as Record<string, number>;
  const totalFindings = Number(summary.findings || 0);

  const downloadFile = async (format: "json" | "csv") => {
    await download(`/backlog-validation-reports/${data.report_id}/download?format=${format}`, `${data.report_id}.${format}`);
  };

  return (
    <div className="page">
      <Link to="/backlog" className="back-link">
        <ArrowLeft size={15} />
        Back to backlog validation
      </Link>
      <PageHeader
        eyebrow={`Report ${data.report_id}`}
        title="Backlog validation report"
        subtitle={`${data.filename || data.upload_id} · generated ${dateTime(report.generated_at)}`}
        actions={
          <>
            <button className="btn btn-ghost" onClick={() => downloadFile("csv")}>
              <FileText size={15} />
              CSV
            </button>
            <button className="btn btn-ghost" onClick={() => downloadFile("json")}>
              <FileJson size={15} />
              JSON
            </button>
            <Badge tone={data.reviewer_status === "pending" ? "amber" : "green"}>{label(data.reviewer_status)}</Badge>
          </>
        }
      />

      <div className="grid grid-4">
        <div className="stat-card tone-accent">
          <span className="stat-label">Backlog items</span>
          <div className="stat-value">{number(summary.backlog_count)}</div>
          <span className="stat-detail">{number(summary.canonical_problem_count)} canonical problems compared</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Findings</span>
          <div className="stat-value">{number(totalFindings)}</div>
          <span className="stat-detail">Item-to-problem relationships</span>
        </div>
        <div className="stat-card tone-warning">
          <span className="stat-label">High-evidence uncovered</span>
          <div className="stat-value">{number(summary.high_evidence_uncovered_problems)}</div>
          <span className="stat-detail">Problems with 5+ mentions</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Evidence run</span>
          <div className="stat-value small mono">{report.feedback_run_id.slice(0, 18)}</div>
          <span className="stat-detail">Taxonomy v{report.versions.taxonomy}</span>
        </div>
      </div>

      <div className="grid grid-2">
        <Card title="Relationship distribution" hint="Backlog item to customer problem">
          <div className="relationship-bars">
            {Object.keys(relationships).length === 0 && <EmptyState title="No relationships recorded" />}
            {Object.entries(relationships)
              .sort((a, b) => b[1] - a[1])
              .map(([key, value]) => (
                <div className="relationship-row" key={key}>
                  <span>{label(key)}</span>
                  <div className="relationship-track">
                    <span
                      className={`relationship-fill tone-${relationshipTone(key)}`}
                      style={{ width: `${(value / Math.max(1, totalFindings)) * 100}%` }}
                    />
                  </div>
                  <strong>{value}</strong>
                </div>
              ))}
          </div>
          <p className="footnote">
            Customer-evidence alignment only. Organisational priority, regulatory obligations, delivery cost and
            strategic value are not inferred from customer text.
          </p>
        </Card>

        <Card title="Alignment by backlog item" hint="Overall relationship classification">
          <div className="alignment-stack">
            {ALIGNMENTS.map((alignment) => {
              const count = Number((summary.alignment || {})[alignment] || 0);
              return (
                <div className="alignment-block" key={alignment}>
                  <div className="alignment-head">
                    <Badge tone={relationshipTone(alignment)}>{label(alignment)}</Badge>
                    <strong>{count}</strong>
                  </div>
                  <div className="alignment-track">
                    <span
                      className={`alignment-fill tone-${relationshipTone(alignment)}`}
                      style={{ width: `${(count / Math.max(1, Number(summary.backlog_count || 1))) * 100}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="version-row">
            {Object.entries(report.versions).map(([key, value]) => (
              <span key={key}>
                {label(key)} <strong className="mono">{value}</strong>
              </span>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Backlog item findings" hint="Expand any item to inspect supporting evidence and AC gaps">
        <div className="report-items">
          {report.backlog_items.length === 0 && <EmptyState title="No backlog items in this report" />}
          {report.backlog_items.map((item) => (
            <details className="report-item" key={item.backlog_id} open={item.overall_alignment !== "unsupported"}>
              <summary>
                <div className="report-item-title">
                  <span className="mono">{item.backlog_id}</span>
                  <strong>{item.title}</strong>
                  <Badge tone={relationshipTone(item.overall_alignment)}>{label(item.overall_alignment)}</Badge>
                </div>
                <div className="report-item-meta">
                  <span>{item.journey_name}</span>
                  <span>{Math.round(item.ac_coverage * 100)}% AC coverage</span>
                  <span>{item.findings.length} findings</span>
                  <span className="priority">{item.priority || "No source priority"}</span>
                </div>
              </summary>
              <div className="report-item-body">
                <p className="report-description">{item.description}</p>
                {item.business_goal && item.business_goal !== "NOT_PROVIDED" && (
                  <p className="report-goal">
                    <strong>Stated business goal:</strong> {item.business_goal}
                  </p>
                )}
                <div className="finding-list">
                  {item.findings.length === 0 && <EmptyState title="No customer problems matched" />}
                  {item.findings.map((finding) => (
                    <article className="finding" key={finding.finding_id}>
                      <div className="finding-head">
                        <Badge tone={relationshipTone(finding.relationship)}>{label(finding.relationship)}</Badge>
                        <Link to={finding.problem_id ? `/problems/${finding.problem_id}` : "#"} className="finding-title">
                          {finding.problem_title || "No matched problem"}
                        </Link>
                        <span className="finding-score">{Math.round(finding.alignment_score * 100)}%</span>
                      </div>
                      <p className="finding-rationale">{finding.rationale}</p>
                      {finding.uncertainty && (
                        <div className="alert alert-warning compact">
                          <ShieldAlert size={14} />
                          {finding.uncertainty}
                        </div>
                      )}
                      {finding.evidence.length > 0 && (
                        <div className="finding-evidence">
                          {finding.evidence.map((evidence, index) => (
                            <blockquote key={`${evidence.feedback_id}-${index}`}>
                              <Quote size={13} />
                              <div>
                                <span>{evidence.evidence_span}</span>
                                <small>
                                  {evidence.feedback_id} · {label(evidence.source_type || "")} · {date(evidence.submitted_at)}
                                  {evidence.rating ? (
                                    <>
                                      {" "}
                                      · <Star size={11} fill="currentColor" /> {evidence.rating}
                                    </>
                                  ) : null}
                                </small>
                              </div>
                            </blockquote>
                          ))}
                        </div>
                      )}
                      {finding.ac_gaps.length > 0 && (
                        <ul className="ac-gaps">
                          {finding.ac_gaps.map((gap, index) => (
                            <li key={index}>{gap}</li>
                          ))}
                        </ul>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            </details>
          ))}
        </div>
      </Card>

      <div className="grid grid-2">
        <Card title="High-evidence customer problems not addressed" hint="Backlog coverage gaps">
          {report.uncovered_high_evidence_problems.length === 0 && (
            <EmptyState title="No high-evidence gaps found" detail="Every problem with 5+ mentions had at least a partial match." />
          )}
          <div className="uncovered-list">
            {report.uncovered_high_evidence_problems.map((problem) => (
              <Link to={`/problems/${problem.problem_id}`} className="uncovered-item" key={problem.problem_id}>
                <div>
                  <strong>{problem.title}</strong>
                  <span>{problem.journey_name || "Unmapped"}</span>
                </div>
                <div className="uncovered-count">
                  {problem.evidence_count}
                  <small>mentions</small>
                </div>
              </Link>
            ))}
          </div>
        </Card>

        <Card title="Product-owner review" hint="Required before treating this report as a decision">
          <form className="form" onSubmit={submit}>
            <label>
              <span>Reviewer</span>
              <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} required />
            </label>
            <label>
              <span>Decision</span>
              <select value={decision} onChange={(event) => setDecision(event.target.value)}>
                <option value="accepted">Accept report</option>
                <option value="accepted_with_changes">Accept with changes</option>
                <option value="needs_more_evidence">Needs more evidence</option>
                <option value="rejected">Reject</option>
              </select>
            </label>
            <label>
              <span>Note</span>
              <textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
            </label>
            <button className="btn btn-primary" disabled={saving}>
              <Download size={15} />
              {saving ? "Saving..." : "Record review"}
            </button>
            {message && <p className="form-success">{message}</p>}
            {reviewError && <p className="form-error">{reviewError}</p>}
          </form>
          {data.reviews.length > 0 && (
            <div className="timeline">
              {data.reviews.map((review, index) => (
                <div className="timeline-item" key={`${review.created_at}-${index}`}>
                  <FileText size={14} />
                  <div>
                    <strong>{review.reviewer}</strong>
                    <span>
                      {label(review.decision)} · {dateTime(review.created_at)}
                    </span>
                    {review.note && <p>{review.note}</p>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Method and limitations" hint="Read before citing this report">
        <ul className="policy-list">
          {report.limitations.map((limitation, index) => (
            <li key={index}>{limitation}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
