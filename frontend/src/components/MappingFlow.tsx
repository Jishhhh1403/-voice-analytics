import { useMemo, useState } from "react";
import { number, truncate } from "../lib/format";
import type { MappingGraphResponse, MappingSelection } from "../lib/types";

type Tone = "teal" | "blue" | "amber" | "green" | "red" | "slate";

type FlowNode = {
  id: string;
  title: string;
  subtitle: string;
  value: number;
  tone: Tone;
  selection?: MappingSelection;
  note?: [string, string];
  detached?: boolean;
};

type FlowLink = {
  source: string;
  target: string;
  value: number;
  tone: Tone;
};

const COLUMN_X = [20, 222, 424, 626, 828];
const NODE_WIDTH = 182;
const NODE_HEIGHT = 56;
const NODE_GAP = 13;
const NODE_TOP = 74;
const NOTE_HEIGHT = 38;
const DETACH_GAP = 20;
const VIEW_WIDTH = 1030;

const TONES: Record<Tone, { fill: string; stroke: string; accent: string; text: string }> = {
  teal: { fill: "#e8f6f1", stroke: "#b3dfce", accent: "#0f9f7a", text: "#0c4f3f" },
  blue: { fill: "#eaf1fb", stroke: "#c1d5f2", accent: "#3c72d1", text: "#1d3d73" },
  amber: { fill: "#fdf4e3", stroke: "#f0d9a8", accent: "#c88918", text: "#6f4b0c" },
  green: { fill: "#e8f7ea", stroke: "#b9e0bd", accent: "#24924a", text: "#155c2c" },
  red: { fill: "#fdecea", stroke: "#f2c5bf", accent: "#c9483a", text: "#7f2b21" },
  slate: { fill: "#f1f4f3", stroke: "#d4dcd8", accent: "#74837c", text: "#3b4a44" },
};

const STAGES = [
  { key: "feedback", label: "Feedback" },
  { key: "signals", label: "Signals" },
  { key: "problems", label: "Canonical problems" },
  { key: "backlogs", label: "Backlogs" },
  { key: "outcomes", label: "Coverage outcome" },
] as const;

function columnHeight(column: FlowNode[]): number {
  return (
    column.reduce(
      (sum, node, index) =>
        sum + NODE_HEIGHT + (node.note ? NOTE_HEIGHT + 5 : 0) + (node.detached && index ? DETACH_GAP : 0),
      0,
    ) +
    Math.max(0, column.length - 1) * NODE_GAP
  );
}

function stageTotals(data: MappingGraphResponse, flowBacklogCount: number): number[] {
  return [
    data.counts.feedback_total,
    data.counts.signals_total,
    data.counts.themes,
    flowBacklogCount,
    Object.values(data.coverage).reduce((sum, value) => sum + value, 0),
  ];
}

function buildFlow(data: MappingGraphResponse) {
  const signalGroups = data.signals.filter((group) => group.count > 0);
  const signalGroupsById = new Map(signalGroups.map((group) => [group.id, group]));

  const ranked = [...data.themes].sort(
    (a, b) => (b.signal_count || 0) - (a.signal_count || 0) || (b.evidence_count || 0) - (a.evidence_count || 0),
  );
  const featured = ranked.slice(0, 6);
  const featuredIds = new Set(featured.map((item) => item.problem_id));
  const otherCount = Math.max(0, data.themes.length - featured.length);
  const otherSignalCount = data.signal_links
    .filter((link) => !featuredIds.has(link.target))
    .reduce((sum, link) => sum + link.count, 0);

  const visibleBacklogs = data.coverage_backlogs.filter((item) => item.backlog_priority_rank !== 6);
  const featuredBacklogs = [...visibleBacklogs]
    .sort((a, b) => (a.backlog_priority_rank || 99) - (b.backlog_priority_rank || 99))
    .slice(0, 5);
  const featuredBacklogIds = new Set(featuredBacklogs.map((item) => item.backlog_id));
  const otherBacklogCount = Math.max(0, visibleBacklogs.length - featuredBacklogs.length);

  const feedback: FlowNode[] = [
    {
      id: "feedback",
      title: "Customer feedback",
      subtitle: `${number(data.counts.feedback_mapped)} mapped · ${number(data.counts.feedback_unmapped)} unmapped`,
      value: data.counts.feedback_total,
      tone: "teal",
    },
  ];

  const signals: FlowNode[] = signalGroups.map((group) => ({
    id: `signal:${group.id}`,
    title: group.id === "problem" ? "Problem signals" : "Context signals",
    subtitle: `${number(group.count)} linked to problems`,
    value: group.count,
    tone: "amber",
    note:
      group.id === "problem"
        ? ["intent · aspect · symptom", "sentiment · emotion · effort"]
        : undefined,
  }));

  const problems: FlowNode[] = featured.map((theme) => ({
    id: `problem:${theme.problem_id}`,
    title: theme.title || theme.problem_id,
    subtitle: `${number(theme.signal_count || 0)} signals · ${theme.coverage_status === "covered" ? "covered" : theme.coverage_status === "grey_zone" ? "partial" : "not covered"}`,
    value: theme.signal_count || 0,
    tone: "blue",
    selection: { kind: "theme", id: theme.problem_id },
  }));
  if (otherCount) {
    problems.push({
      id: "problem:other",
      title: `${number(otherCount)} other problems`,
      subtitle: `${number(otherSignalCount)} linked signals`,
      value: otherSignalCount,
      tone: "slate",
    });
  }

  const backlogs: FlowNode[] = featuredBacklogs.map((item) => ({
    id: `backlog:${item.backlog_id}`,
    title: item.title || item.backlog_id,
    subtitle: `#${item.backlog_priority_rank || "—"} · ${item.product_area || item.backlog_id}`,
    value: data.links.problem_backlog.filter((link) => link.target === item.backlog_id).length,
    tone: "teal",
    selection: { kind: "backlog", id: item.backlog_id },
  }));
  if (otherBacklogCount) {
    backlogs.push({
      id: "backlog:other",
      title: `${number(otherBacklogCount)} other backlog${otherBacklogCount === 1 ? "" : "s"}`,
      subtitle: "outside the top five",
      value: data.links.problem_backlog.filter(
        (link) => link.target && !featuredBacklogIds.has(link.target) && link.status !== "not_covered",
      ).length,
      tone: "slate",
    });
  }

  const outcomes: FlowNode[] = [
    { id: "outcome:covered", title: "Covered", subtitle: "problems fully addressed", value: data.coverage.covered, tone: "green" },
    { id: "outcome:grey_zone", title: "Partially covered", subtitle: "needs review", value: data.coverage.grey_zone, tone: "amber" },
    {
      id: "outcome:not_covered",
      title: "Not covered",
      subtitle: "no backlog mapping",
      value: data.coverage.not_covered,
      tone: "red",
      detached: true,
    },
  ];
  if (data.coverage.unassessed) {
    outcomes.push({
      id: "outcome:unassessed",
      title: "Unassessed",
      subtitle: "no backlog mapping",
      value: data.coverage.unassessed,
      tone: "slate",
      detached: true,
    });
  }

  const signalToProblem = new Map<string, number>();
  for (const link of data.signal_links) {
    if (!signalGroupsById.has(link.source)) continue;
    const problemId = featuredIds.has(link.target) ? `problem:${link.target}` : "problem:other";
    const key = `${link.source}|${problemId}`;
    signalToProblem.set(key, (signalToProblem.get(key) || 0) + link.count);
  }

  const problemToBacklog = new Map<string, number>();
  const backlogToOutcome = new Map<string, number>();
  const outcomeForStatus: Record<string, string> = {
    covered: "outcome:covered",
    grey_zone: "outcome:grey_zone",
  };
  for (const link of data.links.problem_backlog) {
    const outcomeNode = outcomeForStatus[link.status];
    if (!outcomeNode || !link.target) continue;
    const problemNode = featuredIds.has(link.source) ? `problem:${link.source}` : "problem:other";
    const backlogNode = featuredBacklogIds.has(link.target) ? `backlog:${link.target}` : "backlog:other";
    problemToBacklog.set(`${problemNode}|${backlogNode}`, (problemToBacklog.get(`${problemNode}|${backlogNode}`) || 0) + 1);
    const outcomeKey = `${backlogNode}|${outcomeNode}`;
    backlogToOutcome.set(outcomeKey, (backlogToOutcome.get(outcomeKey) || 0) + 1);
  }

  const links: FlowLink[] = [
    ...signalGroups.map((group) => ({
      source: "feedback",
      target: `signal:${group.id}`,
      value: group.count,
      tone: "teal" as const,
    })),
    ...[...signalToProblem].map(([key, value]) => {
      const [source, target] = key.split("|");
      return { source: `signal:${source}`, target, value, tone: "amber" as const };
    }),
    ...[...problemToBacklog].map(([key, value]) => {
      const [source, target] = key.split("|");
      return { source, target, value, tone: "blue" as const };
    }),
    ...[...backlogToOutcome].map(([key, value]) => {
      const [source, target] = key.split("|");
      const status = target.replace("outcome:", "");
      return {
        source,
        target,
        value,
        tone: (status === "covered" ? "green" : "amber") as Tone,
      };
    }),
  ];

  return {
    columns: [feedback, signals, problems, backlogs, outcomes],
    links,
    backlogCount: visibleBacklogs.length,
  };
}

function ribbonWidth(value: number): number {
  return Math.max(1.6, Math.min(15, 2 + Math.log10(value + 1) * 3.2));
}

export default function MappingFlow({
  data,
  selection,
  onSelect,
}: {
  data: MappingGraphResponse;
  selection: MappingSelection | null;
  onSelect: (selection: MappingSelection | null) => void;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const flow = useMemo(() => buildFlow(data), [data]);
  const height = Math.max(520, NODE_TOP + Math.max(...flow.columns.map(columnHeight)) + 40);
  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number; width: number; height: number }>();
    flow.columns.forEach((column, columnIndex) => {
      let y = NODE_TOP + Math.max(0, (height - NODE_TOP - columnHeight(column) - 24) / 2);
      column.forEach((node, index) => {
        if (node.detached && index) y += DETACH_GAP;
        map.set(node.id, { x: COLUMN_X[columnIndex], y, width: NODE_WIDTH, height: NODE_HEIGHT });
        y += NODE_HEIGHT + NODE_GAP + (node.note ? NOTE_HEIGHT + 5 : 0);
      });
    });
    return map;
  }, [flow.columns, height]);

  const activeId =
    hovered || (selection ? `${selection.kind === "theme" ? "problem" : selection.kind}:${selection.id}` : null);
  const noMapping = activeId === "outcome:not_covered" || activeId === "outcome:unassessed";
  const connected = useMemo(() => {
    if (!activeId || noMapping) return null;
    const found = new Set<string>([activeId]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const link of flow.links) {
        if (found.has(link.source) && !found.has(link.target)) {
          found.add(link.target);
          changed = true;
        }
        if (found.has(link.target) && !found.has(link.source)) {
          found.add(link.source);
          changed = true;
        }
      }
    }
    return found;
  }, [activeId, flow.links, noMapping]);
  const totals = stageTotals(data, flow.backlogCount);

  return (
    <div className="mapping-flow-diagram">
      <svg viewBox={`0 0 ${VIEW_WIDTH} ${height}`} role="img" aria-label="Flow from feedback through signals and canonical problems to backlog coverage">
        <defs>
          {[
            ["ribbon-teal", "#1cb990", "#4f9bea"],
            ["ribbon-amber", "#e5a93b", "#5b9ce9"],
            ["ribbon-blue", "#5b9ce9", "#1cb990"],
            ["ribbon-green", "#34b865", "#34b865"],
            ["ribbon-red", "#e06858", "#e06858"],
          ].map(([id, from, to]) => (
            <linearGradient key={id} id={id} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={from} />
              <stop offset="100%" stopColor={to} />
            </linearGradient>
          ))}
          <marker id="mapping-flow-arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#9aa9a2" />
          </marker>
        </defs>

        {STAGES.map((stage, index) => (
          <g key={stage.key}>
            <text className="mapping-flow-stage-index" x={COLUMN_X[index] + 1} y={26}>
              {String(index + 1).padStart(2, "0")}
            </text>
            <text className="mapping-flow-stage-label" x={COLUMN_X[index] + 28} y={26}>
              {stage.label}
            </text>
            <text className="mapping-flow-stage-total" x={COLUMN_X[index] + 1} y={47}>
              {number(totals[index])}
            </text>
          </g>
        ))}

        <g className="mapping-flow-ribbons">
          {flow.links.map((link, index) => {
            const source = positions.get(link.source);
            const target = positions.get(link.target);
            if (!source || !target) return null;
            const x1 = source.x + source.width;
            const y1 = source.y + source.height / 2;
            const x2 = target.x;
            const y2 = target.y + target.height / 2;
            const middle = (x1 + x2) / 2;
            const active = !connected || (connected.has(link.source) && connected.has(link.target));
            return (
              <path
                key={`${link.source}-${link.target}-${index}`}
                d={`M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`}
                stroke={`url(#ribbon-${link.tone})`}
                strokeWidth={ribbonWidth(link.value)}
                opacity={active ? 0.72 : 0.16}
              >
                <title>{`${link.source.replace(/^[^:]+:/, "")} → ${link.target.replace(/^[^:]+:/, "")}: ${number(link.value)}`}</title>
              </path>
            );
          })}
        </g>

        {flow.columns.map((column) =>
          column.map((node) => {
            const position = positions.get(node.id);
            if (!position) return null;
            const tone = TONES[node.tone];
            const active = !connected || connected.has(node.id);
            return (
              <g
                key={node.id}
                className={`mapping-flow-node ${node.selection ? "clickable" : ""}`}
                opacity={active ? 1 : 0.7}
                onMouseEnter={() => setHovered(node.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => node.selection && onSelect(node.selection)}
              >
                <rect
                  x={position.x}
                  y={position.y}
                  width={position.width}
                  height={position.height}
                  rx="11"
                  fill={tone.fill}
                  stroke={active ? tone.stroke : tone.fill}
                  strokeWidth="1.5"
                  strokeDasharray={node.detached ? "5 4" : undefined}
                />
                <rect x={position.x} y={position.y + 10} width="3.5" height={position.height - 20} rx="1.75" fill={tone.accent} />
                <text className="mapping-flow-node-title" x={position.x + 13} y={position.y + 23} fill={tone.text}>
                  {truncate(node.title, 24)}
                </text>
                <text className="mapping-flow-node-subtitle" x={position.x + 13} y={position.y + 42} fill={tone.text}>
                  {truncate(node.subtitle, 27)}
                </text>
                <text className="mapping-flow-node-value" x={position.x + position.width - 11} y={position.y + 23} fill={tone.accent} textAnchor="end">
                  {number(node.value)}
                </text>
                {node.note && (
                  <g>
                    <rect
                      x={position.x}
                      y={position.y + NODE_HEIGHT + 5}
                      width={position.width}
                      height={NOTE_HEIGHT}
                      rx="8"
                      fill="#fffaf0"
                      stroke="#f0d9a8"
                    />
                    <text className="mapping-flow-note" x={position.x + 10} y={position.y + NODE_HEIGHT + 19} fill="#6f4b0c">
                      {node.note[0]}
                    </text>
                    <text className="mapping-flow-note" x={position.x + 10} y={position.y + NODE_HEIGHT + 32} fill="#6f4b0c">
                      {node.note[1]}
                    </text>
                  </g>
                )}
              </g>
            );
          }),
        )}

        {STAGES.slice(0, -1).map((stage, index) => (
          <path
            key={`arrow-${stage.key}`}
            className="mapping-flow-arrow"
            d={`M ${COLUMN_X[index] + NODE_WIDTH + 5} 48 L ${COLUMN_X[index + 1] - 9} 48`}
            stroke="#9aa9a2"
            strokeWidth="1.5"
            markerEnd="url(#mapping-flow-arrowhead)"
          />
        ))}
      </svg>
      <div className="mapping-flow-caption">
        <span><i className="mapping-dot feedback" /> Feedback volume</span>
        <span><i className="mapping-dot theme" /> Signals</span>
        <span><i className="mapping-dot factor" /> Canonical problems</span>
        <span><i className="mapping-dot backlog" /> Backlogs</span>
        <span className="mapping-legend-note">
          Covered and partially covered problems map through a backlog; not-covered problems have no backlog mapping.
          The six largest problems and five backlog items are named; the remainder is grouped.
        </span>
      </div>
    </div>
  );
}
