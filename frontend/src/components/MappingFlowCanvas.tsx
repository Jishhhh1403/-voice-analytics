import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { number, truncate } from "../lib/format";
import type { MappingGraphResponse, MappingSelection } from "../lib/types";

type Vec = { x: number; y: number };
type Status = "covered" | "grey_zone" | "not_covered";
type View = { scale: number; x: number; y: number };

type Layout = {
  feedback: Map<string, Vec>;
  feedbackByStatus: Record<Status, Vec[]>;
  problems: Map<string, Vec>;
  problemStatus: Map<string, Status>;
  backlogs: Map<string, Vec>;
  outcomes: Record<string, Vec>;
  feedbackToProblems: Map<string, string[]>;
  problemToFeedback: Map<string, string[]>;
  problemToBacklogs: Map<string, { id: string; status: Status }[]>;
  worldWidth: number;
  worldHeight: number;
  columns: { feedback: number; signals: number; problems: number; backlogs: number; outcomes: number };
};

type Hovered = { selection: MappingSelection; x: number; y: number } | null;

const WORLD_WIDTH = 2800;
const FEEDBACK_PITCH = 3.4;
const STATUS_COLOR: Record<Status, string> = {
  covered: "#24924a",
  grey_zone: "#d99b2b",
  not_covered: "#c9564a",
};
const STATUS_LABEL: Record<Status, string> = {
  covered: "covered",
  grey_zone: "partially covered",
  not_covered: "not covered",
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function nodeKey(kind: string, id: string): string {
  return `${kind}:${id}`;
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
  ctx.lineTo(x + width, y + height - radius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  ctx.lineTo(x + radius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

function computeLayout(data: MappingGraphResponse): Layout {
  const statusOf = new Map<string, Status>();
  for (const theme of data.themes) {
    const status = theme.coverage_status;
    statusOf.set(theme.problem_id, status === "covered" || status === "grey_zone" ? status : "not_covered");
  }

  const feedbackToProblems = new Map<string, string[]>();
  const problemToFeedback = new Map<string, string[]>();
  for (const link of data.links.feedback_theme) {
    if (!statusOf.has(link.target)) continue;
    const problems = feedbackToProblems.get(link.source) || [];
    problems.push(link.target);
    feedbackToProblems.set(link.source, problems);
    const feedback = problemToFeedback.get(link.target) || [];
    feedback.push(link.source);
    problemToFeedback.set(link.target, feedback);
  }

  const grouped = new Map<string, typeof data.feedback>();
  for (const theme of data.themes) grouped.set(theme.problem_id, []);
  const unmapped: typeof data.feedback = [];
  for (const item of data.feedback) {
    const primary = item.primary_theme_id && grouped.has(item.primary_theme_id) ? item.primary_theme_id : null;
    if (primary) grouped.get(primary)?.push(item);
    else unmapped.push(item);
  }

  const feedback = new Map<string, Vec>();
  const problems = new Map<string, Vec>();
  const feedbackByStatus: Record<Status, Vec[]> = { covered: [], grey_zone: [], not_covered: [] };
  let cursor = 60;
  for (const theme of data.themes) {
    const items = grouped.get(theme.problem_id) || [];
    const bandHeight = Math.max(7, items.length * FEEDBACK_PITCH + 5);
    const center = cursor + bandHeight / 2;
    problems.set(theme.problem_id, { x: 0, y: center });
    const pitch = items.length ? bandHeight / items.length : 0;
    items.forEach((item, index) => {
      const point = { x: 0, y: cursor + (index + 0.5) * pitch };
      feedback.set(item.feedback_id, point);
      feedbackByStatus[statusOf.get(theme.problem_id) || "not_covered"].push(point);
    });
    cursor += bandHeight + 4;
  }
  if (unmapped.length) {
    cursor += 40;
    const bandHeight = Math.max(40, unmapped.length * FEEDBACK_PITCH);
    const pitch = bandHeight / unmapped.length;
    unmapped.forEach((item, index) => {
      const point = { x: 0, y: cursor + (index + 0.5) * pitch };
      feedback.set(item.feedback_id, point);
      feedbackByStatus.not_covered.push(point);
    });
    cursor += bandHeight + 40;
  }
  const worldHeight = cursor + 60;

  const problemToBacklogs = new Map<string, { id: string; status: Status }[]>();
  const backlogProblems = new Map<string, string[]>();
  for (const link of data.links.problem_backlog) {
    const status = link.status === "covered" || link.status === "grey_zone" ? link.status : null;
    if (!status || !link.target) continue;
    const links = problemToBacklogs.get(link.source) || [];
    links.push({ id: link.target, status });
    problemToBacklogs.set(link.source, links);
    const ids = backlogProblems.get(link.target) || [];
    ids.push(link.source);
    backlogProblems.set(link.target, ids);
  }

  const visibleBacklogs = data.coverage_backlogs.filter((item) => item.backlog_priority_rank !== 6);
  const rawBacklogs = visibleBacklogs.map((item) => {
    const anchors = (backlogProblems.get(item.backlog_id) || [])
      .map((id) => problems.get(id)?.y)
      .filter((value): value is number => value !== undefined);
    return {
      id: item.backlog_id,
      y: anchors.length ? anchors.reduce((sum, value) => sum + value, 0) / anchors.length : worldHeight / 2,
    };
  });
  rawBacklogs.sort((a, b) => a.y - b.y);
  const gap = Math.max(120, worldHeight / Math.max(1, rawBacklogs.length + 2));
  let previous = -Infinity;
  for (const item of rawBacklogs) {
    item.y = Math.max(item.y, previous + gap, 70);
    previous = item.y;
  }
  const overflow = previous - (worldHeight - 70);
  if (overflow > 0) {
    for (const item of rawBacklogs) item.y -= overflow;
    previous = -Infinity;
    for (const item of rawBacklogs) {
      item.y = Math.max(item.y, previous + gap, 70);
      previous = item.y;
    }
  }

  const columns = {
    feedback: 90,
    signals: WORLD_WIDTH * 0.24,
    problems: WORLD_WIDTH * 0.5,
    backlogs: WORLD_WIDTH * 0.75,
    outcomes: WORLD_WIDTH * 0.92,
  };
  for (const point of feedback.values()) point.x = columns.feedback;
  for (const point of problems.values()) point.x = columns.problems;

  return {
    feedback,
    feedbackByStatus,
    problems,
    problemStatus: statusOf,
    backlogs: new Map(rawBacklogs.map((item) => [item.id, { x: columns.backlogs, y: item.y }])),
    outcomes: {
      covered: { x: columns.outcomes, y: worldHeight * 0.3 },
      grey_zone: { x: columns.outcomes, y: worldHeight * 0.45 },
      not_covered: { x: columns.outcomes, y: worldHeight * 0.65 },
    },
    feedbackToProblems,
    problemToFeedback,
    problemToBacklogs,
    worldWidth: WORLD_WIDTH,
    worldHeight,
    columns,
  };
}

function fitView(layout: Layout, width: number, height: number): View {
  const padding = 40;
  const scale = Math.min((width - padding * 2) / layout.worldWidth, (height - padding * 2) / layout.worldHeight);
  const safe = Number.isFinite(scale) && scale > 0 ? scale : 0.005;
  return { scale: safe, x: (width - layout.worldWidth * safe) / 2, y: (height - layout.worldHeight * safe) / 2 };
}

function highlightFor(selection: MappingSelection | null, layout: Layout) {
  const nodes = new Set<string>();
  const edges = new Set<string>();
  if (!selection) return { nodes, edges };

  const addProblem = (id: string) => {
    nodes.add(nodeKey("theme", id));
    for (const feedback of layout.problemToFeedback.get(id) || []) {
      edges.add(`ft:${feedback}:${id}`);
      nodes.add(nodeKey("feedback", feedback));
    }
    for (const link of layout.problemToBacklogs.get(id) || []) {
      edges.add(`pb:${id}:${link.id}`);
      nodes.add(nodeKey("backlog", link.id));
      edges.add(`bo:${link.id}:${link.status}`);
    }
  };
  const addFeedback = (id: string) => {
    nodes.add(nodeKey("feedback", id));
    for (const problem of layout.feedbackToProblems.get(id) || []) {
      edges.add(`ft:${id}:${problem}`);
      addProblem(problem);
    }
  };

  if (selection.kind === "feedback") addFeedback(selection.id);
  else if (selection.kind === "theme") addProblem(selection.id);
  else if (selection.kind === "backlog") {
    nodes.add(nodeKey("backlog", selection.id));
    for (const [problem, links] of layout.problemToBacklogs) {
      if (!links.some((link) => link.id === selection.id)) continue;
      edges.add(`pb:${problem}:${selection.id}`);
      addProblem(problem);
    }
  }
  return { nodes, edges };
}

export default function MappingFlowCanvas({
  data,
  selection,
  onSelect,
  focusTarget,
}: {
  data: MappingGraphResponse;
  selection: MappingSelection | null;
  onSelect: (selection: MappingSelection | null) => void;
  focusTarget: (MappingSelection & { nonce: number }) | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const viewRef = useRef<View>({ scale: 0.005, x: 0, y: 0 });
  const fitKeyRef = useRef("");
  const dragRef = useRef<{ x: number; y: number; view: View; moved: boolean } | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [view, setView] = useState<View>({ scale: 0.005, x: 0, y: 0 });
  const [hovered, setHovered] = useState<Hovered>(null);

  const layout = useMemo(() => computeLayout(data), [data]);
  const highlight = useMemo(() => highlightFor(selection, layout), [layout, selection]);
  const outcomeEdgeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const link of data.links.problem_backlog) {
      if (!link.target || (link.status !== "covered" && link.status !== "grey_zone")) continue;
      const key = `${link.target}:${link.status}`;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return counts;
  }, [data.links.problem_backlog]);
  viewRef.current = view;
  sizeRef.current = size;

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setSize({ width: Math.max(1, entry.contentRect.width), height: Math.max(1, entry.contentRect.height) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fit = useCallback(() => {
    if (!sizeRef.current.width || !sizeRef.current.height) return;
    const next = fitView(layout, sizeRef.current.width, sizeRef.current.height);
    setView(next);
    viewRef.current = next;
  }, [layout]);

  useEffect(() => {
    if (!size.width || !size.height) return;
    const key = `${data.feedback_run_id}:${data.coverage_report_id}:${layout.worldWidth}:${layout.worldHeight}`;
    if (fitKeyRef.current === key) return;
    fitKeyRef.current = key;
    fit();
  }, [data.coverage_report_id, data.feedback_run_id, fit, layout.worldHeight, layout.worldWidth, size.height, size.width]);

  const setZoom = useCallback(
    (factor: number, anchorX?: number, anchorY?: number) => {
      const current = viewRef.current;
      const ax = anchorX ?? sizeRef.current.width / 2;
      const ay = anchorY ?? sizeRef.current.height / 2;
      const base = fitView(layout, sizeRef.current.width, sizeRef.current.height);
      const nextScale = clamp(current.scale * factor, base.scale * 0.7, 8);
      const worldX = (ax - current.x) / current.scale;
      const worldY = (ay - current.y) / current.scale;
      const next = { scale: nextScale, x: ax - worldX * nextScale, y: ay - worldY * nextScale };
      setView(next);
      viewRef.current = next;
    },
    [layout],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const handler = (event: WheelEvent) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      setZoom(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
    };
    canvas.addEventListener("wheel", handler, { passive: false });
    return () => canvas.removeEventListener("wheel", handler);
  }, [setZoom]);

  const pointFor = useCallback(
    (target: MappingSelection): Vec | null => {
      if (target.kind === "feedback") return layout.feedback.get(target.id) || null;
      if (target.kind === "theme") return layout.problems.get(target.id) || null;
      if (target.kind === "backlog") return layout.backlogs.get(target.id) || null;
      return null;
    },
    [layout],
  );

  useEffect(() => {
    if (!focusTarget || !sizeRef.current.width) return;
    const point = pointFor(focusTarget);
    if (!point) return;
    const scale = focusTarget.kind === "feedback" ? 1.1 : focusTarget.kind === "theme" ? 0.32 : 0.5;
    const next = { scale, x: sizeRef.current.width / 2 - point.x * scale, y: sizeRef.current.height / 2 - point.y * scale };
    setView(next);
    viewRef.current = next;
  }, [focusTarget, pointFor]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !size.width || !size.height) return;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(size.width * dpr) || canvas.height !== Math.round(size.height * dpr)) {
      canvas.width = Math.round(size.width * dpr);
      canvas.height = Math.round(size.height * dpr);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.width, size.height);

    const { scale, x, y } = view;
    const sx = (value: number) => value * scale + x;
    const sy = (value: number) => value * scale + y;
    const hasHighlight = highlight.nodes.size > 0;

    ctx.save();
    ctx.strokeStyle = "rgba(148, 163, 184, 0.3)";
    ctx.setLineDash([4, 7]);
    ctx.lineWidth = 1;
    for (const column of [layout.columns.feedback, layout.columns.signals, layout.columns.problems, layout.columns.backlogs, layout.columns.outcomes]) {
      const px = sx(column);
      if (px < -20 || px > size.width + 20) continue;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, size.height);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(217, 169, 59, 0.06)";
    const signalLeft = sx(layout.columns.signals - 80);
    const signalRight = sx(layout.columns.signals + 80);
    ctx.fillRect(signalLeft, 0, signalRight - signalLeft, size.height);
    ctx.restore();

    const drawEdge = (source: Vec, target: Vec, color: string, alpha: number, width: number, key: string) => {
      const x1 = sx(source.x);
      const y1 = sy(source.y);
      const x2 = sx(target.x);
      const y2 = sy(target.y);
      if ((x1 < -10 && x2 < -10) || (x1 > size.width + 10 && x2 > size.width + 10)) return;
      if ((y1 < -10 && y2 < -10) || (y1 > size.height + 10 && y2 > size.height + 10)) return;
      const active = !hasHighlight || highlight.edges.has(key);
      ctx.globalAlpha = hasHighlight ? (active ? alpha * 2.4 : alpha * 0.05) : alpha;
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      const mid = (x1 + x2) / 2;
      ctx.bezierCurveTo(mid, y1, mid, y2, x2, y2);
      ctx.stroke();
    };

    for (const link of data.links.feedback_theme) {
      const source = layout.feedback.get(link.source);
      const target = layout.problems.get(link.target);
      if (!source || !target) continue;
      drawEdge(source, target, STATUS_COLOR[layout.problemStatus.get(link.target) || "not_covered"], 0.05, 0.6, `ft:${link.source}:${link.target}`);
    }
    for (const [problem, links] of layout.problemToBacklogs) {
      const source = layout.problems.get(problem);
      if (!source) continue;
      for (const link of links) {
        const target = layout.backlogs.get(link.id);
        if (!target) continue;
        drawEdge(source, target, STATUS_COLOR[link.status], 0.45, 1, `pb:${problem}:${link.id}`);
      }
    }
    for (const [backlog, point] of layout.backlogs) {
      for (const status of ["covered", "grey_zone"] as Status[]) {
        if (!outcomeEdgeCounts.get(`${backlog}:${status}`)) continue;
        drawEdge(point, layout.outcomes[status], STATUS_COLOR[status], 0.7, 1.4, `bo:${backlog}:${status}`);
      }
    }
    ctx.globalAlpha = 1;

    for (const status of ["not_covered", "grey_zone", "covered"] as Status[]) {
      ctx.fillStyle = STATUS_COLOR[status];
      for (const point of layout.feedbackByStatus[status]) {
        const px = sx(point.x);
        const py = sy(point.y);
        if (px < -4 || px > size.width + 4 || py < -4 || py > size.height + 4) continue;
        const radius = scale > 0.06 ? 1.3 : 0.7;
        ctx.fillRect(px - radius, py - radius, radius * 2, radius * 2);
      }
    }

    const problemRadius = 2.2 * clamp(scale / 0.02, 0.7, 1.8);
    for (const theme of data.themes) {
      const point = layout.problems.get(theme.problem_id);
      if (!point) continue;
      const screen = { x: sx(point.x), y: sy(point.y) };
      const radius = problemRadius * (1 + Math.min(1.4, Math.sqrt(theme.signal_count || 0) / 4));
      if (screen.x < -10 || screen.x > size.width + 10 || screen.y < -10 || screen.y > size.height + 10) continue;
      const key = nodeKey("theme", theme.problem_id);
      const active = !hasHighlight || highlight.nodes.has(key);
      ctx.globalAlpha = hasHighlight ? (active ? 1 : 0.12) : 0.88;
      ctx.fillStyle = STATUS_COLOR[layout.problemStatus.get(theme.problem_id) || "not_covered"];
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
      ctx.fill();
      if (scale > 0.06 || active) {
        ctx.globalAlpha = hasHighlight && !active ? 0.2 : 0.9;
        ctx.fillStyle = "#2b3a34";
        ctx.font = "500 10px ui-sans-serif, system-ui, sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(truncate(theme.title, 34), screen.x + radius + 4, screen.y + 3, 180);
      }
    }
    ctx.globalAlpha = 1;

    for (const [id, point] of layout.backlogs) {
      const backlog = data.coverage_backlogs.find((item) => item.backlog_id === id);
      if (!backlog) continue;
      const screen = { x: sx(point.x), y: sy(point.y) };
      const active = !hasHighlight || highlight.nodes.has(nodeKey("backlog", id));
      ctx.globalAlpha = hasHighlight ? (active ? 1 : 0.18) : 1;
      ctx.fillStyle = "#e8f6f1";
      ctx.strokeStyle = "#0f9f7a";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#155c47";
      ctx.font = "600 10px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(`#${backlog.backlog_priority_rank || "—"} ${truncate(backlog.title, 30)}`, screen.x + 12, screen.y + 3, 190);
    }
    ctx.globalAlpha = 1;

    const outcomes = [
      { id: "covered", title: "Covered", value: data.coverage.covered, status: "covered" as Status, detached: false },
      { id: "grey_zone", title: "Partially covered", value: data.coverage.grey_zone, status: "grey_zone" as Status, detached: false },
      { id: "not_covered", title: "Not covered", value: data.coverage.not_covered, status: "not_covered" as Status, detached: true },
    ];
    for (const box of outcomes) {
      const point = layout.outcomes[box.id];
      const cx = sx(point.x);
      const cy = sy(point.y);
      const width = 156;
      const height = 46;
      if (cx < -width || cx > size.width + width || cy < -height || cy > size.height + height) continue;
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = STATUS_COLOR[box.status];
      ctx.lineWidth = box.detached ? 1.4 : 2;
      ctx.setLineDash(box.detached ? [5, 4] : []);
      roundedRect(ctx, cx - width / 2, cy - height / 2, width, height, 10);
      ctx.fill();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = STATUS_COLOR[box.status];
      ctx.font = "700 11px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(box.title, cx - width / 2 + 11, cy - 3);
      ctx.font = "500 9.5px ui-sans-serif, system-ui, sans-serif";
      ctx.fillStyle = "#66736d";
      ctx.fillText(box.detached ? "no backlog mapping" : `${number(box.value)} problems`, cx - width / 2 + 11, cy + 12);
      ctx.fillStyle = STATUS_COLOR[box.status];
      ctx.font = "800 12px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(number(box.value), cx + width / 2 - 11, cy - 3);
    }

    const headers = [
      { x: layout.columns.feedback, label: `${number(data.counts.feedback_total)} FEEDBACK` },
      { x: layout.columns.signals, label: `${number(data.counts.signals_total)} SIGNALS` },
      { x: layout.columns.problems, label: `${number(data.counts.themes)} CANONICAL PROBLEMS` },
      { x: layout.columns.backlogs, label: `${layout.backlogs.size} BACKLOGS` },
      { x: layout.columns.outcomes, label: "COVERAGE" },
    ];
    ctx.fillStyle = "#33413b";
    ctx.font = "700 10px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "left";
    for (const header of headers) {
      const px = sx(header.x);
      if (px > -40 && px < size.width + 40) ctx.fillText(header.label, px + 6, 18);
    }
  }, [data, highlight, layout, outcomeEdgeCounts, size.height, size.width, view]);

  const findHit = useCallback(
    (screenX: number, screenY: number): MappingSelection | null => {
      const toScreen = (point: Vec) => ({ x: point.x * view.scale + view.x, y: point.y * view.scale + view.y });
      const close = (point: Vec, radius: number) => {
        const screen = toScreen(point);
        return Math.hypot(screen.x - screenX, screen.y - screenY) <= radius;
      };
      for (const [id, point] of layout.backlogs) if (close(point, 14)) return { kind: "backlog", id };
      for (const theme of data.themes) {
        const point = layout.problems.get(theme.problem_id);
        if (point && close(point, 8)) return { kind: "theme", id: theme.problem_id };
      }
      for (const item of data.feedback) {
        const point = layout.feedback.get(item.feedback_id);
        if (point && close(point, 5)) return { kind: "feedback", id: item.feedback_id };
      }
      return null;
    },
    [data.feedback, data.themes, layout, view],
  );

  const hoveredDetails = useMemo(() => {
    if (!hovered) return null;
    if (hovered.selection.kind === "feedback") {
      const item = data.feedback.find((entry) => entry.feedback_id === hovered.selection.id);
      return item
        ? {
            title: item.title || item.feedback_id,
            subtitle: `${item.feedback_id} · ${item.source_type || "feedback"}`,
            lines: [`${item.theme_count || 0} linked problems`, item.primary_theme_id ? `Primary ${item.primary_theme_id}` : "Unmapped"],
          }
        : null;
    }
    if (hovered.selection.kind === "theme") {
      const item = data.themes.find((entry) => entry.problem_id === hovered.selection.id);
      return item
        ? {
            title: item.title,
            subtitle: `${item.problem_id} · ${item.journey_name || "canonical problem"}`,
            lines: [`${number(item.signal_count || 0)} signals`, STATUS_LABEL[layout.problemStatus.get(item.problem_id) || "not_covered"]],
          }
        : null;
    }
    const item = data.coverage_backlogs.find((entry) => entry.backlog_id === hovered.selection.id);
    return item
      ? { title: item.title, subtitle: `${item.backlog_id} · priority #${item.backlog_priority_rank || "—"}`, lines: ["Backlog item"] }
      : null;
  }, [data.coverage_backlogs, data.feedback, data.themes, hovered, layout.problemStatus]);

  const pointerPosition = (event: {
    clientX: number;
    clientY: number;
    currentTarget: HTMLCanvasElement;
  }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const signalScreenX = view.scale * layout.columns.signals + view.x;

  return (
    <div className="mapping-graph mapping-flow-canvas" ref={containerRef}>
      <canvas
        ref={canvasRef}
        className="mapping-canvas"
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          const position = pointerPosition(event);
          dragRef.current = { ...position, view: viewRef.current, moved: false };
          setHovered(null);
        }}
        onPointerMove={(event) => {
          const position = pointerPosition(event);
          const drag = dragRef.current;
          if (drag) {
            const dx = position.x - drag.x;
            const dy = position.y - drag.y;
            if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
            const next = { ...drag.view, x: drag.view.x + dx, y: drag.view.y + dy };
            setView(next);
            viewRef.current = next;
            return;
          }
          const hit = findHit(position.x, position.y);
          setHovered(hit ? { selection: hit, ...position } : null);
        }}
        onPointerUp={(event) => {
          const drag = dragRef.current;
          dragRef.current = null;
          if (!drag || drag.moved) return;
          const position = pointerPosition(event);
          onSelect(findHit(position.x, position.y));
        }}
        onPointerLeave={() => {
          if (!dragRef.current) setHovered(null);
        }}
        onDoubleClick={(event) => {
          const position = pointerPosition(event);
          const hit = findHit(position.x, position.y);
          if (hit) {
            onSelect(hit);
            const point = pointFor(hit);
            if (point) {
              const scale = hit.kind === "feedback" ? 1.1 : hit.kind === "theme" ? 0.32 : 0.5;
              const next = { scale, x: size.width / 2 - point.x * scale, y: size.height / 2 - point.y * scale };
              setView(next);
              viewRef.current = next;
            }
          }
        }}
        aria-label="Node-level feedback to canonical problem flow"
      />
      {signalScreenX > -200 && signalScreenX < size.width + 40 && (
        <div className="mapping-signal-card" style={{ left: clamp(signalScreenX - 92, 8, size.width - 200) }}>
          <strong>Problem signals</strong>
          <span>{number(data.counts.signals_total)} extracted</span>
          <small>intent · aspect · symptom<br />sentiment · emotion · effort</small>
        </div>
      )}
      <div className="mapping-graph-controls">
        <button className="icon-btn" onClick={() => setZoom(1.35)} title="Zoom in" aria-label="Zoom in"><ZoomIn size={15} /></button>
        <button className="icon-btn" onClick={() => setZoom(1 / 1.35)} title="Zoom out" aria-label="Zoom out"><ZoomOut size={15} /></button>
        <button className="icon-btn" onClick={fit} title="Fit graph" aria-label="Fit graph"><Maximize2 size={15} /></button>
      </div>
      <div className="mapping-graph-hint">
        All {number(data.counts.feedback_total)} feedback records and {number(data.counts.themes)} canonical problems · scroll to zoom · drag to pan
      </div>
      {hovered && hoveredDetails && (
        <div className="mapping-tooltip" style={{ left: clamp(hovered.x + 16, 8, Math.max(8, size.width - 268)), top: clamp(hovered.y + 16, 8, Math.max(8, size.height - 128)) }}>
          <strong>{hoveredDetails.title}</strong>
          <span>{hoveredDetails.subtitle}</span>
          {hoveredDetails.lines.map((line) => <b key={line}>{line}</b>)}
        </div>
      )}
    </div>
  );
}
