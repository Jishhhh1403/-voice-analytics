import { ChevronLeft, ChevronRight, Search, ShieldAlert, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner } from "../components/ui";
import { date, label, number } from "../lib/format";
import type { ProblemListItem } from "../lib/types";
import { useFetch } from "../lib/useFetch";

type ProblemResponse = {
  items: ProblemListItem[];
  total: number;
  page: number;
  page_size: number;
};

export default function ProblemsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [search, setSearch] = useState(params.get("search") || "");
  const page = Number(params.get("page") || "1");
  const [options, setOptions] = useState<{ node_id: string; display_name: string; node_type: string }[]>([]);

  useEffect(() => {
    fetch("/api/v1/feedback/options")
      .then((response) => response.json())
      .then((data) => setOptions(data.journeys || []))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = new URLSearchParams(params);
      if (search) next.set("search", search);
      else next.delete("search");
      next.delete("page");
      if (next.toString() !== params.toString()) setParams(next, { replace: true });
    }, 320);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const query = params.toString();
  const { data, loading, error, reload } = useFetch<ProblemResponse>(`/problems${query ? `?${query}` : ""}`, [query]);
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="page">
      <PageHeader
        eyebrow="Problem explorer"
        title="Canonical customer problems"
        subtitle="Distinct, evidence-backed problem clusters. Every row is traceable to redacted customer comments and a journey mapping."
        actions={
          <div className="search-box">
            <Search size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search problem statements…"
              aria-label="Search problems"
            />
          </div>
        }
      />

      <div className="toolbar">
        <label>
          <span>Journey</span>
          <select value={params.get("journey") || ""} onChange={(event) => set("journey", event.target.value)}>
            <option value="">All journeys</option>
            {options
              .filter((item) => item.node_type === "module")
              .map((item) => (
                <option value={item.node_id} key={item.node_id}>
                  {item.display_name}
                </option>
              ))}
          </select>
        </label>
        <label>
          <span>Lifecycle</span>
          <select value={params.get("status") || ""} onChange={(event) => set("status", event.target.value)}>
            <option value="">All states</option>
            <option value="candidate">Candidate</option>
            <option value="in_review">In review</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
            <option value="merged">Merged</option>
            <option value="deprecated">Deprecated</option>
          </select>
        </label>
        <label>
          <span>Sort</span>
          <select value={params.get("sort") || "evidence"} onChange={(event) => set("sort", event.target.value)}>
            <option value="evidence">Evidence volume</option>
            <option value="recent">Most recent</option>
            <option value="negative">Negative evidence</option>
            <option value="title">Title</option>
          </select>
        </label>
        <div className="toolbar-spacer" />
        <div className="toolbar-count">
          <ShieldAlert size={15} />
          {data ? `${number(data.total)} problems` : "Loading…"}
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <Spinner />}
      {data && data.items.length === 0 && (
        <Card>
          <EmptyState title="No problems match these filters" detail="Try clearing the journey or search filters." />
        </Card>
      )}

      {data && data.items.length > 0 && (
        <Card className="table-card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Problem</th>
                  <th>Journey</th>
                  <th>Symptom</th>
                  <th className="num">Evidence</th>
                  <th className="num">Customers</th>
                  <th>Status</th>
                  <th>Latest</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((problem) => (
                  <tr key={problem.problem_id} onClick={() => navigate(`/problems/${problem.problem_id}`)}>
                    <td>
                      <div className="cell-title">{problem.title}</div>
                      <div className="cell-sub">{problem.problem_id}</div>
                    </td>
                    <td>
                      <span className="journey-tag">
                        <Sparkles size={13} />
                        {problem.journey_name || problem.journey_node_id || "UNMAPPED"}
                      </span>
                    </td>
                    <td>{label(problem.symptom_category)}</td>
                    <td className="num">
                      <strong>{number(problem.evidence_count)}</strong>
                    </td>
                    <td className="num">{number(problem.distinct_customers)}</td>
                    <td>
                      <Badge tone={problem.lifecycle_status === "accepted" ? "green" : "neutral"}>
                        {label(problem.lifecycle_status)}
                      </Badge>
                    </td>
                    <td>{date(problem.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button className="btn btn-ghost btn-small" disabled={page <= 1} onClick={() => set("page", String(page - 1))}>
              <ChevronLeft size={14} />
              Previous
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button
              className="btn btn-ghost btn-small"
              disabled={page >= totalPages}
              onClick={() => set("page", String(page + 1))}
            >
              Next
              <ChevronRight size={14} />
            </button>
          </div>
        </Card>
      )}

      <p className="footnote">
        Customer evidence alignment is not the same as organisational priority. A low complaint count does not make a
        regulatory or security-critical item unimportant.
      </p>
    </div>
  );
}
