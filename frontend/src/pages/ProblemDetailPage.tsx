import { ArrowLeft, CheckCircle2, Quote, ShieldCheck, Star, UserRound } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner } from "../components/ui";
import { postJSON } from "../lib/api";
import { date, dateTime, label, number } from "../lib/format";
import type { ProblemDetail } from "../lib/types";
import { useFetch } from "../lib/useFetch";

export default function ProblemDetailPage() {
  const { problemId } = useParams();
  const { data, loading, error, reload } = useFetch<ProblemDetail>(problemId ? `/problems/${problemId}` : null, [problemId]);
  const [reviewer, setReviewer] = useState("journey-expert");
  const [decision, setDecision] = useState("accept");
  const [note, setNote] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!problemId) return;
    setSaving(true);
    setMessage(null);
    setReviewError(null);
    try {
      await postJSON(`/problems/${problemId}/review`, {
        reviewer,
        decision,
        note,
        new_title: decision === "rename" ? newTitle : undefined,
      });
      setMessage("Review recorded in the audit trail.");
      setNote("");
      reload();
    } catch (err) {
      setReviewError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) return <Spinner label="Loading problem evidence…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div className="page">
      <Link to="/problems" className="back-link">
        <ArrowLeft size={15} />
        Back to problem explorer
      </Link>
      <PageHeader
        eyebrow={`${data.problem_id} · ${data.cluster_id || "cluster"}`}
        title={data.title}
        subtitle={data.problem_statement}
        actions={
          <div className="header-badges">
            <Badge tone={data.lifecycle_status === "accepted" ? "green" : "amber"}>{label(data.lifecycle_status)}</Badge>
            <Badge tone="blue">{number(data.evidence_count)} evidence links</Badge>
          </div>
        }
      />

      <div className="grid grid-4">
        <div className="stat-card tone-accent">
          <span className="stat-label">Distinct customers</span>
          <div className="stat-value">{number(data.distinct_customers)}</div>
          <span className="stat-detail">Pseudonymous synthetic references</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Negative evidence</span>
          <div className="stat-value">{number(data.negative_count)}</div>
          <span className="stat-detail">Not a severity score</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">First seen</span>
          <div className="stat-value small">{date(data.first_seen)}</div>
          <span className="stat-detail">Latest {date(data.last_seen)}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Journey</span>
          <div className="stat-value small">{data.journey_name || data.journey_node_id || "UNMAPPED"}</div>
          <span className="stat-detail">Taxonomy v{data.taxonomy_version}</span>
        </div>
      </div>

      <div className="grid grid-detail">
        <div className="stack">
          <Card title="Supporting customer evidence" hint="Exact redacted spans extracted from feedback text">
            <div className="evidence-list">
              {data.evidence.length === 0 && <EmptyState title="No evidence links" />}
              {data.evidence.map((item, index) => (
                <article className="evidence-item" key={`${item.feedback_id}-${index}`}>
                  <div className="evidence-head">
                    <div>
                      <Badge tone="neutral">{item.feedback_id}</Badge>
                      <span>{label(item.source_type)}</span>
                      <span>{item.platform}</span>
                    </div>
                    <div className="evidence-meta">
                      {item.rating && (
                        <span className="rating">
                          <Star size={13} fill="currentColor" />
                          {item.rating}
                        </span>
                      )}
                      <span>{date(item.submitted_at)}</span>
                    </div>
                  </div>
                  <blockquote>
                    <Quote size={16} />
                    <span>{item.evidence_span}</span>
                  </blockquote>
                </article>
              ))}
            </div>
          </Card>

          <Card title="Extracted insight signals" hint="Sentence-level model output linked to this problem">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Intent</th>
                    <th>Aspect</th>
                    <th>Symptom</th>
                    <th>Sentiment</th>
                    <th>Effort</th>
                    <th>Outcome</th>
                    <th className="num">Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {data.insights.map((insight) => (
                    <tr key={insight.insight_id}>
                      <td>{label(insight.customer_intent)}</td>
                      <td>{label(insight.aspect)}</td>
                      <td>{label(insight.reported_symptom)}</td>
                      <td>
                        <Badge tone={insight.sentiment === "positive" ? "green" : insight.sentiment === "mixed" ? "amber" : "red"}>
                          {insight.sentiment}
                        </Badge>
                      </td>
                      <td>{label(insight.customer_effort)}</td>
                      <td>{label(insight.reported_outcome)}</td>
                      <td className="num">{Math.round(insight.confidence * 100)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="footnote">
              Confidence is a heuristic signal, not a calibrated probability. Root cause is never inferred from feedback
              text alone.
            </p>
          </Card>
        </div>

        <div className="stack">
          <Card title="Journey mapping" hint="Primary mapping and rationale">
            {data.mappings.length === 0 && <EmptyState title="Unmapped" detail="A taxonomy proposal should be reviewed." />}
            {data.mappings.map((mapping) => (
              <div className="mapping-block" key={mapping.mapping_id}>
                <div className="mapping-head">
                  <ShieldCheck size={16} />
                  <strong>{mapping.display_name || mapping.node_id}</strong>
                  <Badge tone="green">{Math.round(mapping.confidence * 100)}%</Badge>
                </div>
                <p>{mapping.rationale}</p>
                <div className="mapping-foot">
                  <span>{mapping.mapping_type}</span>
                  <span>{label(mapping.status)}</span>
                </div>
              </div>
            ))}
          </Card>

          <Card title="Reviewer decision" hint="Every action is auditable">
            <form className="form" onSubmit={submit}>
              <label>
                <span>Reviewer</span>
                <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} required />
              </label>
              <label>
                <span>Decision</span>
                <select value={decision} onChange={(event) => setDecision(event.target.value)}>
                  <option value="accept">Accept problem</option>
                  <option value="mark_in_review">Mark in review</option>
                  <option value="reject">Reject</option>
                  <option value="merge">Merge into another problem</option>
                  <option value="split">Split cluster</option>
                  <option value="rename">Rename</option>
                  <option value="deprecate">Deprecate</option>
                </select>
              </label>
              {decision === "rename" && (
                <label>
                  <span>New title</span>
                  <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} />
                </label>
              )}
              <label>
                <span>Audit note</span>
                <textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
              </label>
              <button className="btn btn-primary" disabled={saving}>
                <CheckCircle2 size={15} />
                {saving ? "Saving…" : "Record decision"}
              </button>
              {message && <p className="form-success">{message}</p>}
              {reviewError && <p className="form-error">{reviewError}</p>}
            </form>
          </Card>

          <Card title="Review history" hint="Newest first">
            {data.reviews.length === 0 && <EmptyState title="No reviews yet" />}
            <div className="timeline">
              {data.reviews.map((review, index) => (
                <div className="timeline-item" key={`${review.created_at}-${index}`}>
                  <UserRound size={14} />
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
          </Card>
        </div>
      </div>
    </div>
  );
}
