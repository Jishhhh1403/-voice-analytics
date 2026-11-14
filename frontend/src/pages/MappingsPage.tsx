import {
  ArrowRight,
  Crosshair,
  GitBranch,
  Search,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from "lucide-react";
import { KeyboardEvent, useMemo, useState } from "react";
import MappingGraph from "../components/MappingGraph";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner, StatCard, relationshipTone } from "../components/ui";
import { buildMappingIndex, factorColor, searchMappings } from "../lib/mappingGraph";
import { dateTime, label, number } from "../lib/format";
import type {
  MappingFactorNode,
  MappingGraphResponse,
  MappingNodeKind,
  MappingSelection,
} from "../lib/types";
import { useFetch } from "../lib/useFetch";

const RELATIONSHIPS = ["ALL", "COVERS", "PARTIALLY_COVERS", "RELATED", "NOT_COVERED", "NEEDS_REVIEW"];

const KIND_LABELS: Record<MappingNodeKind, string> = {
  feedback: "Feedback",
  theme: "Theme",
  factor: "Factor",
  backlog: "Backlog",
};

function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function SelectionLinks({
  items,
  onSelect,
}: {
  items: { kind: MappingNodeKind; id: string; label: string; detail?: string; badge?: string }[];
  onSelect: (selection: MappingSelection) => void;
}) {
  if (!items.length) return <p className="mapping-muted">No linked nodes.</p>;
  return (
    <div className="mapping-link-list">
      {items.map((item) => (
        <button
          className="mapping-link-row"
          key={`${item.kind}:${item.id}`}
          onClick={() => onSelect({ kind: item.kind, id: item.id })}
        >
          <span>
            <strong>{item.label}</strong>
            <small>{item.detail || item.id}</small>
          </span>
          {item.badge && <Badge tone={relationshipTone(item.badge)}>{label(item.badge)}</Badge>}
          <ArrowRight size={13} />
        </button>
      ))}
    </div>
  );
}

function FactorRow({ factor }: { factor: MappingFactorNode }) {
  return (
    <span className="mapping-factor-inline">
      <i style={{ background: factorColor(factor.rank) }}>{factor.factor_id}</i>
      {factor.factor_name}
    </span>
  );
}

export default function MappingsPage() {
  const { data, loading, error, reload } = useFetch<MappingGraphResponse>("/mappings");
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [mappedOnly, setMappedOnly] = useState(false);
  const [relationship, setRelationship] = useState("ALL");
  const [selected, setSelected] = useState<MappingSelection | null>(null);
  const [focusTarget, setFocusTarget] = useState<(MappingSelection & { nonce: number }) | null>(null);

  const index = useMemo(() => (data ? buildMappingIndex(data) : null), [data]);
  const searchResults = useMemo(() => (data ? searchMappings(data, search) : []), [data, search]);

  const goTo = (selection: MappingSelection) => {
    setSelected(selection);
    setFocusTarget({ ...selection, nonce: Date.now() });
    setSearchOpen(false);
  };

  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && searchResults[0]) {
      event.preventDefault();
      goTo(searchResults[0]);
    }
    if (event.key === "Escape") setSearchOpen(false);
  };

  if (loading && !data) return <Spinner label="Loading the end-to-end mapping graph..." />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  if (data.status !== "READY" && data.status !== "PARTIAL") {
    return (
      <div className="page">
        <PageHeader
          eyebrow="Evidence graph"
          title="Mappings"
          subtitle="Trace every feedback record through themes and prioritized factors into validated backlog items."
        />
        <Card>
          <EmptyState
            title="Mapping graph is not available yet"
            detail={data.warnings[0] || "Complete a feedback run, factor analysis and backlog validation first."}
          />
        </Card>
      </div>
    );
  }

  const selectedFeedback =
    selected?.kind === "feedback" ? index?.feedbackById.get(selected.id) || null : null;
  const selectedTheme =
    selected?.kind === "theme" ? index?.themeById.get(selected.id) || null : null;
  const selectedFactor =
    selected?.kind === "factor" ? data.factors.find((item) => item.factor_id === selected.id) || null : null;
  const selectedBacklog =
    selected?.kind === "backlog" ? data.backlogs.find((item) => item.backlog_id === selected.id) || null : null;

  const themeFactorItems = selectedTheme
    ? (index?.themeFactorBySource.get(selectedTheme.problem_id) || [])
        .map((link) => {
          const factor = data.factors.find((item) => item.factor_id === link.target);
          return factor
            ? {
                kind: "factor" as const,
                id: factor.factor_id,
                label: `#${factor.rank} ${factor.factor_name}`,
                detail: `${factor.factor_id} · score ${link.score.toFixed(2)} · ${label(link.membership_type)}`,
              }
            : null;
        })
        .filter((item): item is NonNullable<typeof item> => Boolean(item))
    : [];

  const feedbackThemeItems = selectedFeedback
    ? (index?.feedbackThemeBySource.get(selectedFeedback.feedback_id) || [])
        .map((link) => {
          const theme = index?.themeById.get(link.target);
          return theme
            ? {
                kind: "theme" as const,
                id: theme.problem_id,
                label: theme.title,
                detail: `${theme.journey_name || "theme"} · ${theme.evidence_count || 0} evidence · weight ${link.weight.toFixed(2)}`,
              }
            : null;
        })
        .filter((item): item is NonNullable<typeof item> => Boolean(item))
    : [];

  const themeFeedbackItems = selectedTheme
    ? (index?.feedbackThemeByTarget.get(selectedTheme.problem_id) || [])
        .slice(0, 10)
        .map((link) => {
          const feedback = index?.feedbackById.get(link.source);
          return feedback
            ? {
                kind: "feedback" as const,
                id: feedback.feedback_id,
                label: feedback.title || feedback.feedback_id,
                detail: `${feedback.feedback_id} · ${feedback.source_type || "feedback"}`,
              }
            : null;
        })
        .filter((item): item is NonNullable<typeof item> => Boolean(item))
    : [];

  const factorThemeItems = selectedFactor
    ? (index?.themeFactorByTarget.get(selectedFactor.factor_id) || [])
        .slice(0, 12)
        .map((link) => {
          const theme = index?.themeById.get(link.source);
          return theme
            ? {
                kind: "theme" as const,
                id: theme.problem_id,
                label: theme.title,
                detail: `${theme.evidence_count || 0} evidence · ${theme.mapped_feedback_count || 0} feedback links`,
              }
            : null;
        })
        .filter((item): item is NonNullable<typeof item> => Boolean(item))
    : [];

  const factorBacklogItems = selectedFactor
    ? (index?.factorBacklogBySource.get(selectedFactor.factor_id) || []).map((link) => {
        const backlog = data.backlogs.find((item) => item.backlog_id === link.target);
        return {
          kind: "backlog" as const,
          id: link.target,
          label: backlog?.title || link.target,
          detail: `${link.target} · ${link.coverage_pct ?? 0}% coverage`,
          badge: link.relationship || undefined,
        };
      })
    : [];

  const backlogFactorItems = selectedBacklog
    ? (index?.factorBacklogByTarget.get(selectedBacklog.backlog_id) || []).map((link) => {
        const factor = data.factors.find((item) => item.factor_id === link.source);
        return {
          kind: "factor" as const,
          id: link.source,
          label: factor ? `#${factor.rank} ${factor.factor_name}` : link.source,
          detail: `${link.source} · ${link.coverage_pct ?? 0}% coverage · distance ${link.embedding_distance?.toFixed(3) ?? "—"}`,
          badge: link.relationship || undefined,
        };
      })
    : [];

  const visibleBacklogLinks =
    relationship === "ALL"
      ? data.links.factor_backlog.length
      : data.links.factor_backlog.filter((link) => link.relationship === relationship).length;

  const detailTitle = selected ? `${KIND_LABELS[selected.kind]} ${selected.id}` : "Trace a path";
  const detailHint = selected
    ? "Connected nodes are clickable. Use focus to center this node in the graph."
    : "Click any node in the graph, or search for a feedback record, theme, factor or backlog.";

  return (
    <div className="page mapping-page">
      <PageHeader
        eyebrow="End-to-end evidence graph"
        title="Mappings"
        subtitle="Every persisted feedback-theme link, every theme-factor membership and every factor-backlog finding in one directed graph."
        actions={
          <>
            <Badge tone={data.status === "READY" ? "green" : "amber"}>{label(data.status)}</Badge>
            <Badge tone="blue">{data.feedback_run_id}</Badge>
          </>
        }
      />

      <div className="grid grid-4 mapping-stats">
        <StatCard
          label="Feedback mapped"
          value={`${number(data.counts.feedback_mapped)} / ${number(data.counts.feedback_total)}`}
          detail={`${number(data.counts.feedback_unmapped)} records without theme evidence`}
          icon={<GitBranch size={17} />}
          tone="accent"
        />
        <StatCard
          label="Themes"
          value={number(data.counts.themes)}
          detail={`${number(data.counts.feedback_theme_links)} feedback-theme links`}
          icon={<Waypoints size={17} />}
        />
        <StatCard
          label="Factors"
          value={number(data.counts.factors)}
          detail={`${number(data.counts.theme_factor_links)} theme-factor memberships`}
          icon={<Sparkles size={17} />}
        />
        <StatCard
          label="Backlogs"
          value={number(data.counts.backlogs)}
          detail={`${number(visibleBacklogLinks)} visible factor-backlog findings`}
          icon={<ShieldCheck size={17} />}
          tone={data.counts.backlogs ? "default" : "warning"}
        />
      </div>

      {data.warnings.length > 0 && (
        <div className="mapping-warnings">
          {data.warnings.map((warning) => (
            <span key={warning}>{warning}</span>
          ))}
        </div>
      )}

      <div className="mapping-layout">
        <Card className="mapping-graph-card" title="Mapping graph" hint="Left-to-right: feedback → themes → factors → backlogs">
          <div className="mapping-toolbar">
            <div className="mapping-search">
              <div className="search-box">
                <Search size={14} />
                <input
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setSearchOpen(true);
                  }}
                  onFocus={() => setSearchOpen(true)}
                  onKeyDown={onSearchKeyDown}
                  placeholder="Search feedback, theme, factor or backlog"
                  aria-label="Search mapping graph"
                />
                {search && (
                  <button
                    className="mapping-search-clear"
                    onClick={() => {
                      setSearch("");
                      setSearchOpen(false);
                    }}
                    aria-label="Clear search"
                  >
                    ×
                  </button>
                )}
              </div>
              {searchOpen && search.trim().length >= 2 && (
                <div className="mapping-search-results">
                  {searchResults.length === 0 && <span className="mapping-search-empty">No matching nodes.</span>}
                  {searchResults.map((result) => (
                    <button
                      key={`${result.kind}:${result.id}`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => goTo(result)}
                    >
                      <Badge tone="neutral">{KIND_LABELS[result.kind]}</Badge>
                      <span>
                        <strong>{truncate(result.label, 56)}</strong>
                        <small>{result.subtitle}</small>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <label className="mapping-check">
              <input
                type="checkbox"
                checked={mappedOnly}
                onChange={(event) => {
                  setMappedOnly(event.target.checked);
                  setFocusTarget(null);
                }}
              />
              <span>
                Mapped feedback only
                <small>Hide {number(data.counts.feedback_unmapped)} unmapped records</small>
              </span>
            </label>
            <label className="mapping-select">
              <span>Factor → backlog edge</span>
              <select value={relationship} onChange={(event) => setRelationship(event.target.value)}>
                {RELATIONSHIPS.map((item) => (
                  <option key={item} value={item}>
                    {item === "ALL" ? "All relationships" : label(item)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <MappingGraph
            data={data}
            mappedOnly={mappedOnly}
            relationship={relationship}
            selection={selected}
            onSelect={(next) => {
              setSelected(next);
              setFocusTarget(null);
            }}
            focusTarget={focusTarget}
            search={search}
          />
          <div className="mapping-legend">
            <span>
              <i className="mapping-dot feedback" /> feedback
            </span>
            <span>
              <i className="mapping-dot theme" /> theme
            </span>
            <span>
              <i className="mapping-dot factor" /> factor
            </span>
            <span>
              <i className="mapping-dot backlog" /> backlog
            </span>
            <span>
              <i className="mapping-line covers" /> covers
            </span>
            <span>
              <i className="mapping-line partial" /> partially covers
            </span>
            <span>
              <i className="mapping-line related" /> related
            </span>
            <span>
              <i className="mapping-line gap" /> not covered
            </span>
            <span className="mapping-legend-note">
              Theme and feedback colours follow their primary factor. Edge colour on the last hop follows the
              relationship.
            </span>
          </div>
        </Card>

        <Card
          className="mapping-detail-card"
          title={detailTitle}
          hint={detailHint}
          actions={
            selected && (
              <button
                className="btn btn-ghost"
                onClick={() => setFocusTarget({ ...selected, nonce: Date.now() })}
              >
                <Crosshair size={14} />
                Focus
              </button>
            )
          }
        >
          {!selected && (
            <div className="mapping-detail-empty">
              <div className="mapping-flow">
                <span>Feedback</span>
                <ArrowRight size={14} />
                <span>Themes</span>
                <ArrowRight size={14} />
                <span>Factors</span>
                <ArrowRight size={14} />
                <span>Backlogs</span>
              </div>
              <p>
                Use the graph to inspect how individual customer feedback rolls up into themes, how themes load on
                prioritized factors, and which backlog items those factors support.
              </p>
              <div className="mapping-detail-kv">
                <div>
                  <span>Feedback run</span>
                  <strong className="mono">{data.feedback_run_id}</strong>
                </div>
                <div>
                  <span>Factor run</span>
                  <strong className="mono">{data.prioritisation_run_id || "—"}</strong>
                </div>
                <div>
                  <span>FAMD run</span>
                  <strong className="mono">{data.famd_run_id || "—"}</strong>
                </div>
                <div>
                  <span>Validation report</span>
                  <strong className="mono">{data.report_id || "—"}</strong>
                </div>
              </div>
            </div>
          )}

          {selectedFeedback && (
            <div className="mapping-detail">
              <div className="mapping-detail-tags">
                <Badge tone="neutral">Feedback</Badge>
                <Badge tone="blue">{selectedFeedback.source_type || "unknown source"}</Badge>
                {selectedFeedback.primary_theme_id ? (
                  <Badge tone="green">mapped</Badge>
                ) : (
                  <Badge tone="amber">unmapped</Badge>
                )}
              </div>
              <h3>{selectedFeedback.title || selectedFeedback.feedback_id}</h3>
              <p className="mapping-quote">{selectedFeedback.text || "No feedback text persisted."}</p>
              <div className="mapping-detail-kv">
                <div>
                  <span>Feedback ID</span>
                  <strong className="mono">{selectedFeedback.feedback_id}</strong>
                </div>
                <div>
                  <span>Submitted</span>
                  <strong>{selectedFeedback.submitted_at ? dateTime(selectedFeedback.submitted_at) : "—"}</strong>
                </div>
                <div>
                  <span>Source</span>
                  <strong>{selectedFeedback.source_channel || selectedFeedback.source_type || "—"}</strong>
                </div>
                <div>
                  <span>Themes</span>
                  <strong>{selectedFeedback.theme_count || 0}</strong>
                </div>
              </div>
              <h4>Mapped themes</h4>
              <SelectionLinks items={feedbackThemeItems} onSelect={goTo} />
            </div>
          )}

          {selectedTheme && (
            <div className="mapping-detail">
              <div className="mapping-detail-tags">
                <Badge tone="neutral">Theme</Badge>
                {selectedTheme.journey_name && <Badge tone="blue">{selectedTheme.journey_name}</Badge>}
                {selectedTheme.primary_factor_id && (
                  <Badge tone="green">primary {selectedTheme.primary_factor_id}</Badge>
                )}
              </div>
              <h3>{selectedTheme.title}</h3>
              <p>{selectedTheme.problem_statement}</p>
              <div className="mapping-detail-kv">
                <div>
                  <span>Theme ID</span>
                  <strong className="mono">{selectedTheme.problem_id}</strong>
                </div>
                <div>
                  <span>Evidence</span>
                  <strong>{number(selectedTheme.evidence_count || 0)}</strong>
                </div>
                <div>
                  <span>Mapped feedback</span>
                  <strong>{number(selectedTheme.mapped_feedback_count || 0)}</strong>
                </div>
                <div>
                  <span>Primary factor</span>
                  <strong>{selectedTheme.primary_factor_id || "—"}</strong>
                </div>
              </div>
              <h4>Factor memberships</h4>
              <SelectionLinks items={themeFactorItems} onSelect={goTo} />
              <h4>Feedback sample</h4>
              <SelectionLinks items={themeFeedbackItems} onSelect={goTo} />
              {(selectedTheme.mapped_feedback_count || 0) > themeFeedbackItems.length && (
                <p className="mapping-muted">
                  Showing {themeFeedbackItems.length} of {number(selectedTheme.mapped_feedback_count || 0)} linked
                  feedback records.
                </p>
              )}
            </div>
          )}

          {selectedFactor && (
            <div className="mapping-detail">
              <div className="mapping-detail-tags">
                <Badge tone="neutral">Factor</Badge>
                <Badge tone={relationshipTone(selectedFactor.score_status)}>{label(selectedFactor.score_status)}</Badge>
                <Badge tone="blue">{selectedFactor.dimension_id}</Badge>
              </div>
              <h3>
                <FactorRow factor={selectedFactor} />
              </h3>
              <div className="mapping-detail-kv">
                <div>
                  <span>Priority rank</span>
                  <strong>#{selectedFactor.rank}</strong>
                </div>
                <div>
                  <span>Priority score</span>
                  <strong>{selectedFactor.priority_score.toFixed(2)}</strong>
                </div>
                <div>
                  <span>Evidence coverage</span>
                  <strong>{selectedFactor.evidence_coverage.toFixed(0)}%</strong>
                </div>
                <div>
                  <span>Eligibility</span>
                  <strong>{label(selectedFactor.eligibility_status)}</strong>
                </div>
              </div>
              <h4>Top member themes</h4>
              <SelectionLinks items={factorThemeItems} onSelect={goTo} />
              <h4>Backlog coverage</h4>
              <SelectionLinks items={factorBacklogItems} onSelect={goTo} />
            </div>
          )}

          {selectedBacklog && (
            <div className="mapping-detail">
              <div className="mapping-detail-tags">
                <Badge tone="neutral">Backlog</Badge>
                {selectedBacklog.priority && <Badge tone="amber">{selectedBacklog.priority}</Badge>}
                {selectedBacklog.overall_alignment && (
                  <Badge tone={relationshipTone(selectedBacklog.overall_alignment)}>
                    {label(selectedBacklog.overall_alignment)}
                  </Badge>
                )}
              </div>
              <h3>{selectedBacklog.title}</h3>
              <p>{selectedBacklog.description}</p>
              <div className="mapping-detail-kv">
                <div>
                  <span>Backlog ID</span>
                  <strong className="mono">{selectedBacklog.backlog_id}</strong>
                </div>
                <div>
                  <span>Priority rank</span>
                  <strong>#{selectedBacklog.backlog_priority_rank || "—"}</strong>
                </div>
                <div>
                  <span>Factors covered</span>
                  <strong>{selectedBacklog.covered_factor_count || 0}</strong>
                </div>
                <div>
                  <span>Priority alignment</span>
                  <strong>
                    {selectedBacklog.priority_alignment_pct !== null && selectedBacklog.priority_alignment_pct !== undefined
                      ? `${selectedBacklog.priority_alignment_pct.toFixed(1)}%`
                      : "—"}
                  </strong>
                </div>
              </div>
              <h4>Connected factors</h4>
              <SelectionLinks items={backlogFactorItems} onSelect={goTo} />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
