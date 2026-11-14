import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { factorColor, relationshipColor, buildMappingIndex } from "../lib/mappingGraph";
import type {
  MappingFocusTarget,
  MappingGraphResponse,
  MappingNodeKind,
  MappingSelection,
} from "../lib/types";

type Vec = { x: number; y: number };

type GraphLayout = {
  feedback: Map<string, Vec>;
  themes: Map<string, Vec>;
  factors: Map<string, Vec>;
  backlogs: Map<string, Vec>;
  unmapped: string[];
  worldWidth: number;
  worldHeight: number;
  columns: {
    feedback: number;
    theme: number;
    factor: number;
    backlog: number;
  };
};

type View = {
  scale: number;
  x: number;
  y: number;
};

type Hovered = {
  selection: MappingSelection;
  x: number;
  y: number;
};

type Highlight = {
  nodes: Set<string>;
  edges: Set<string>;
};

const FEEDBACK_PITCH = 3.2;

function nodeKey(kind: MappingNodeKind, id: string): string {
  return `${kind}:${id}`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function computeLayout(data: MappingGraphResponse, mappedOnly: boolean): GraphLayout {
  const themeIds = new Set(data.themes.map((item) => item.problem_id));
  const grouped = new Map<string, typeof data.feedback>();
  for (const theme of data.themes) grouped.set(theme.problem_id, []);
  const unmappedFeedback: typeof data.feedback = [];
  for (const item of data.feedback) {
    if (item.primary_theme_id && themeIds.has(item.primary_theme_id)) {
      grouped.get(item.primary_theme_id)?.push(item);
    } else if (!mappedOnly) {
      unmappedFeedback.push(item);
    }
  }

  const feedback = new Map<string, Vec>();
  const themes = new Map<string, Vec>();
  let cursor = 48;
  for (const theme of data.themes) {
    const items = grouped.get(theme.problem_id) || [];
    const bandHeight = items.length ? Math.max(12, items.length * FEEDBACK_PITCH + 8) : 8;
    const center = cursor + bandHeight / 2;
    themes.set(theme.problem_id, { x: 0, y: center });
    const start = cursor + (bandHeight - items.length * FEEDBACK_PITCH) / 2;
    items.forEach((item, index) => {
      feedback.set(item.feedback_id, {
        x: 0,
        y: start + (index + 0.5) * FEEDBACK_PITCH,
      });
    });
    cursor += bandHeight;
  }

  const unmapped: string[] = [];
  if (unmappedFeedback.length) {
    cursor += 20;
    const bandHeight = 56 + Math.min(90, Math.sqrt(unmappedFeedback.length) * 2.2);
    const denominator = Math.max(1, unmappedFeedback.length - 1);
    unmappedFeedback.forEach((item, index) => {
      const y = cursor + (index / denominator) * bandHeight;
      feedback.set(item.feedback_id, { x: 0, y });
      unmapped.push(item.feedback_id);
    });
    cursor += bandHeight + 28;
  }

  const worldHeight = Math.max(320, cursor + 52);
  const factors = new Map<string, Vec>();
  for (const factor of data.factors) {
    const ys = data.themes
      .filter((theme) => theme.primary_factor_id === factor.factor_id)
      .map((theme) => themes.get(theme.problem_id)?.y)
      .filter((value): value is number => value !== undefined);
    const fallback = (factor.rank / Math.max(1, data.factors.length + 1)) * worldHeight;
    const y = ys.length ? ys.reduce((sum, value) => sum + value, 0) / ys.length : fallback;
    factors.set(factor.factor_id, { x: 0, y });
  }

  const factorIds = new Set(data.factors.map((item) => item.factor_id));
  const backlogAnchors = new Map<string, number[]>();
  for (const link of data.links.factor_backlog) {
    const factor = factors.get(link.source);
    if (!factor || !factorIds.has(link.source)) continue;
    const anchors = backlogAnchors.get(link.target) || [];
    anchors.push(factor.y);
    backlogAnchors.set(link.target, anchors);
  }
  const rawBacklogs = data.backlogs.map((item, index) => {
    const anchors = backlogAnchors.get(item.backlog_id) || [];
    const raw = anchors.length
      ? anchors.reduce((sum, value) => sum + value, 0) / anchors.length
      : (worldHeight * (index + 1)) / (data.backlogs.length + 1);
    return { id: item.backlog_id, rank: item.backlog_priority_rank || index + 1, y: raw };
  });
  rawBacklogs.sort((a, b) => a.y - b.y || a.rank - b.rank);
  const gap = Math.min(1150, worldHeight / Math.max(1, rawBacklogs.length));
  let previous = -Infinity;
  for (const item of rawBacklogs) {
    item.y = Math.max(item.y, previous + gap, 36);
    previous = item.y;
  }
  const overflow = previous - (worldHeight - 36);
  if (overflow > 0) {
    for (const item of rawBacklogs) item.y -= overflow;
    previous = -Infinity;
    for (const item of rawBacklogs) {
      item.y = Math.max(item.y, previous + gap, 36);
      previous = item.y;
    }
  }
  const backlogs = new Map(rawBacklogs.map((item) => [item.id, { x: 0, y: item.y }]));
  const worldWidth = Math.max(3200, worldHeight * 1.15);
  const columns = {
    feedback: worldWidth * 0.03,
    theme: worldWidth * 0.27,
    factor: worldWidth * 0.51,
    backlog: worldWidth * 0.75,
  };
  for (const point of feedback.values()) point.x = columns.feedback;
  for (const point of themes.values()) point.x = columns.theme;
  for (const point of factors.values()) point.x = columns.factor;
  for (const point of backlogs.values()) point.x = columns.backlog;

  return { feedback, themes, factors, backlogs, unmapped, worldWidth, worldHeight, columns };
}

function fitView(layout: GraphLayout, width: number, height: number): View {
  const padding = 48;
  const scale = Math.min(
    (width - padding * 2) / layout.worldWidth,
    (height - padding * 2) / layout.worldHeight,
  );
  const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 0.02;
  return {
    scale: safeScale,
    x: (width - layout.worldWidth * safeScale) / 2,
    y: (height - layout.worldHeight * safeScale) / 2,
  };
}

function pointFor(layout: GraphLayout, selection: MappingSelection): Vec | null {
  if (selection.kind === "feedback") return layout.feedback.get(selection.id) || null;
  if (selection.kind === "theme") return layout.themes.get(selection.id) || null;
  if (selection.kind === "factor") return layout.factors.get(selection.id) || null;
  return layout.backlogs.get(selection.id) || null;
}

function highlightFor(
  data: MappingGraphResponse,
  selection: MappingSelection | null,
): Highlight | null {
  if (!selection) return null;
  const nodes = new Set<string>();
  const edges = new Set<string>();
  const index = buildMappingIndex(data);
  const addNode = (kind: MappingNodeKind, id: string) => nodes.add(nodeKey(kind, id));
  const addFeedbackTheme = (link: { source: string; target: string }) =>
    edges.add(`ft:${link.source}:${link.target}`);
  const addThemeFactor = (link: { source: string; target: string }) =>
    edges.add(`tf:${link.source}:${link.target}`);
  const addFactorBacklog = (link: { source: string; target: string }) =>
    edges.add(`fb:${link.source}:${link.target}`);

  const addTheme = (themeId: string) => {
    addNode("theme", themeId);
    for (const link of index.themeFactorBySource.get(themeId) || []) {
      addNode("factor", link.target);
      addThemeFactor(link);
      for (const backlog of index.factorBacklogBySource.get(link.target) || []) {
        addNode("backlog", backlog.target);
        addFactorBacklog(backlog);
      }
    }
    for (const link of index.feedbackThemeByTarget.get(themeId) || []) {
      addNode("feedback", link.source);
      addFeedbackTheme(link);
    }
  };

  const addFactor = (factorId: string) => {
    addNode("factor", factorId);
    for (const themeLink of index.themeFactorByTarget.get(factorId) || []) {
      addNode("theme", themeLink.source);
      addThemeFactor(themeLink);
      for (const feedback of index.feedbackThemeByTarget.get(themeLink.source) || []) {
        addNode("feedback", feedback.source);
        addFeedbackTheme(feedback);
      }
    }
    for (const backlog of index.factorBacklogBySource.get(factorId) || []) {
      addNode("backlog", backlog.target);
      addFactorBacklog(backlog);
    }
  };

  const addBacklog = (backlogId: string) => {
    addNode("backlog", backlogId);
    for (const backlogLink of index.factorBacklogByTarget.get(backlogId) || []) {
      addNode("factor", backlogLink.source);
      addFactorBacklog(backlogLink);
      addFactor(backlogLink.source);
    }
  };

  if (selection.kind === "feedback") {
    addNode("feedback", selection.id);
    for (const link of index.feedbackThemeBySource.get(selection.id) || []) {
      addNode("theme", link.target);
      addFeedbackTheme(link);
      for (const factorLink of index.themeFactorBySource.get(link.target) || []) {
        addNode("factor", factorLink.target);
        addThemeFactor(factorLink);
        for (const backlog of index.factorBacklogBySource.get(factorLink.target) || []) {
          addNode("backlog", backlog.target);
          addFactorBacklog(backlog);
        }
      }
    }
  } else if (selection.kind === "theme") {
    addTheme(selection.id);
  } else if (selection.kind === "factor") {
    addFactor(selection.id);
  } else {
    addBacklog(selection.id);
  }

  return { nodes, edges };
}

function searchMatchesFor(data: MappingGraphResponse, search: string) {
  const needle = search.trim().toLowerCase();
  if (needle.length < 2) return null;
  const feedback = new Set<string>();
  const themes = new Set<string>();
  const factors = new Set<string>();
  const backlogs = new Set<string>();
  for (const item of data.feedback) {
    if (feedback.size >= 250) break;
    if (
      item.feedback_id.toLowerCase().includes(needle) ||
      item.title.toLowerCase().includes(needle) ||
      item.text.toLowerCase().includes(needle)
    ) {
      feedback.add(item.feedback_id);
    }
  }
  for (const item of data.themes) {
    if (
      item.problem_id.toLowerCase().includes(needle) ||
      item.title.toLowerCase().includes(needle) ||
      (item.journey_name || "").toLowerCase().includes(needle)
    ) {
      themes.add(item.problem_id);
    }
  }
  for (const item of data.factors) {
    if (
      item.factor_id.toLowerCase().includes(needle) ||
      item.factor_name.toLowerCase().includes(needle)
    ) {
      factors.add(item.factor_id);
    }
  }
  for (const item of data.backlogs) {
    if (
      item.backlog_id.toLowerCase().includes(needle) ||
      item.title.toLowerCase().includes(needle) ||
      (item.product_area || "").toLowerCase().includes(needle)
    ) {
      backlogs.add(item.backlog_id);
    }
  }
  return { feedback, themes, factors, backlogs };
}

export default function MappingGraph({
  data,
  mappedOnly,
  relationship,
  selection,
  onSelect,
  focusTarget,
  search,
}: {
  data: MappingGraphResponse;
  mappedOnly: boolean;
  relationship: string;
  selection: MappingSelection | null;
  onSelect: (selection: MappingSelection | null) => void;
  focusTarget: MappingFocusTarget | null;
  search: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const viewRef = useRef<View>({ scale: 0.02, x: 0, y: 0 });
  const fitKeyRef = useRef("");
  const dragRef = useRef<{ x: number; y: number; view: View; moved: boolean } | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [view, setView] = useState<View>({ scale: 0.02, x: 0, y: 0 });
  const [hovered, setHovered] = useState<Hovered | null>(null);

  const layout = useMemo(() => computeLayout(data, mappedOnly), [data, mappedOnly]);
  const highlight = useMemo(() => highlightFor(data, selection), [data, selection]);
  const matches = useMemo(() => searchMatchesFor(data, search), [data, search]);
  const index = useMemo(() => buildMappingIndex(data), [data]);

  viewRef.current = view;
  sizeRef.current = size;

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const width = Math.max(1, entry.contentRect.width);
      const height = Math.max(1, entry.contentRect.height);
      setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!size.width || !size.height) return;
    const key = `${data.feedback_run_id}:${mappedOnly}:${layout.worldWidth}:${layout.worldHeight}`;
    if (fitKeyRef.current === key) return;
    fitKeyRef.current = key;
    const next = fitView(layout, size.width, size.height);
    setView(next);
    viewRef.current = next;
  }, [data.feedback_run_id, layout, mappedOnly, size.height, size.width]);

  const focus = useCallback(
    (target: MappingSelection) => {
      const point = pointFor(layout, target);
      if (!point || !sizeRef.current.width) return;
      const scale =
        target.kind === "feedback" ? 0.8 : target.kind === "theme" ? 0.35 : 0.5;
      const next = {
        scale,
        x: sizeRef.current.width / 2 - point.x * scale,
        y: sizeRef.current.height / 2 - point.y * scale,
      };
      setView(next);
      viewRef.current = next;
    },
    [layout],
  );

  useEffect(() => {
    if (focusTarget) focus(focusTarget);
  }, [focus, focusTarget]);

  const setZoom = useCallback(
    (factor: number, anchorX?: number, anchorY?: number) => {
      const current = viewRef.current;
      const width = sizeRef.current.width;
      const height = sizeRef.current.height;
      const ax = anchorX ?? width / 2;
      const ay = anchorY ?? height / 2;
      const fit = fitView(layout, width, height);
      const nextScale = clamp(current.scale * factor, fit.scale * 0.7, 8);
      const worldX = (ax - current.x) / current.scale;
      const worldY = (ay - current.y) / current.scale;
      const next = {
        scale: nextScale,
        x: ax - worldX * nextScale,
        y: ay - worldY * nextScale,
      };
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
      setZoom(
        Math.exp(-event.deltaY * 0.0015),
        event.clientX - rect.left,
        event.clientY - rect.top,
      );
    };
    canvas.addEventListener("wheel", handler, { passive: false });
    return () => canvas.removeEventListener("wheel", handler);
  }, [setZoom]);

  const fit = useCallback(() => {
    if (!sizeRef.current.width || !sizeRef.current.height) return;
    const next = fitView(layout, sizeRef.current.width, sizeRef.current.height);
    setView(next);
    viewRef.current = next;
  }, [layout]);

  const findHit = useCallback(
    (screenX: number, screenY: number): MappingSelection | null => {
      const scale = viewRef.current.scale;
      const x = viewRef.current.x;
      const y = viewRef.current.y;
      const toScreen = (point: Vec) => ({ x: point.x * scale + x, y: point.y * scale + y });
      const close = (point: Vec, radius: number) => {
        const screen = toScreen(point);
        return Math.hypot(screen.x - screenX, screen.y - screenY) <= radius;
      };

      for (const item of data.backlogs) {
        const point = layout.backlogs.get(item.backlog_id);
        if (point && close(point, 14)) return { kind: "backlog", id: item.backlog_id };
      }
      for (const item of data.factors) {
        const point = layout.factors.get(item.factor_id);
        if (point && close(point, 13)) return { kind: "factor", id: item.factor_id };
      }
      for (const item of data.themes) {
        const point = layout.themes.get(item.problem_id);
        if (point && close(point, 7)) return { kind: "theme", id: item.problem_id };
      }
      for (const item of data.feedback) {
        const point = layout.feedback.get(item.feedback_id);
        if (point && close(point, 5)) return { kind: "feedback", id: item.feedback_id };
      }
      return null;
    },
    [data, layout],
  );

  const pointToScreen = useCallback(
    (point: Vec) => ({
      x: point.x * view.scale + view.x,
      y: point.y * view.scale + view.y,
    }),
    [view],
  );

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
    const themeNodes = data.themes;

    ctx.save();
    ctx.strokeStyle = "rgba(148, 163, 184, 0.28)";
    ctx.setLineDash([4, 6]);
    ctx.lineWidth = 1;
    for (const column of [layout.columns.theme, layout.columns.factor, layout.columns.backlog]) {
      const px = sx(column);
      if (px < -20 || px > size.width + 20) continue;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, size.height);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.fillStyle = "#7d8983";
    ctx.font = "600 10px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "left";
    const headers = [
      { x: layout.columns.feedback, label: "FEEDBACK" },
      { x: layout.columns.theme, label: `${data.counts.themes} THEMES` },
      { x: layout.columns.factor, label: `${data.counts.factors} FACTORS` },
      { x: layout.columns.backlog, label: `${data.counts.backlogs} BACKLOGS` },
    ];
    for (const header of headers) {
      const px = sx(header.x);
      if (px > -40 && px < size.width + 40) ctx.fillText(header.label, px, 18);
    }
    ctx.restore();

    const drawEdge = (
      source: Vec,
      target: Vec,
      color: string,
      width: number,
      alpha: number,
      arrowSize = 3,
    ) => {
      const startX = sx(source.x);
      const startY = sy(source.y);
      const endX = sx(target.x);
      const endY = sy(target.y);
      if (
        (startX < -10 && endX < -10) ||
        (startX > size.width + 10 && endX > size.width + 10) ||
        (startY < -10 && endY < -10) ||
        (startY > size.height + 10 && endY > size.height + 10)
      ) {
        return;
      }
      const controlX = (startX + endX) / 2;
      const angle = Math.atan2(endY - startY, endX - controlX);
      const tipX = endX - Math.cos(angle) * 5;
      const tipY = endY - Math.sin(angle) * 5;
      ctx.strokeStyle = color;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.quadraticCurveTo(controlX, startY, tipX, tipY);
      ctx.stroke();
      if (arrowSize > 0) {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(
          tipX - Math.cos(angle - 0.48) * arrowSize,
          tipY - Math.sin(angle - 0.48) * arrowSize,
        );
        ctx.lineTo(
          tipX - Math.cos(angle + 0.48) * arrowSize,
          tipY - Math.sin(angle + 0.48) * arrowSize,
        );
        ctx.closePath();
        ctx.fill();
      }
    };

    for (const link of data.links.feedback_theme) {
      const source = layout.feedback.get(link.source);
      const target = layout.themes.get(link.target);
      if (!source || !target) continue;
      const theme = index.themeById.get(link.target);
      const rank = theme?.primary_factor_rank;
      const key = `ft:${link.source}:${link.target}`;
      const active = highlight ? highlight.edges.has(key) : false;
      const dimmed = highlight ? !active : false;
      drawEdge(
        source,
        target,
        factorColor(rank),
        active ? 1 : 0.7,
        dimmed ? 0.015 : active ? 0.5 : 0.075,
        active || scale > 0.22 ? 2.5 : 1.6,
      );
    }

    const factorRank = new Map(data.factors.map((item) => [item.factor_id, item.rank]));
    for (const link of data.links.theme_factor) {
      const source = layout.themes.get(link.source);
      const target = layout.factors.get(link.target);
      if (!source || !target) continue;
      const key = `tf:${link.source}:${link.target}`;
      const active = highlight ? highlight.edges.has(key) : false;
      const dimmed = highlight ? !active : false;
      drawEdge(
        source,
        target,
        factorColor(factorRank.get(link.target)),
        active ? 1.4 : 0.8,
        dimmed ? 0.03 : active ? 0.8 : 0.24,
        3,
      );
    }

    for (const link of data.links.factor_backlog) {
      if (relationship !== "ALL" && link.relationship !== relationship) continue;
      const source = layout.factors.get(link.source);
      const target = layout.backlogs.get(link.target);
      if (!source || !target) continue;
      const key = `fb:${link.source}:${link.target}`;
      const active = highlight ? highlight.edges.has(key) : false;
      const dimmed = highlight ? !active : false;
      drawEdge(
        source,
        target,
        relationshipColor(link.relationship),
        active ? 2.4 : 1.25,
        dimmed ? 0.05 : active ? 0.95 : 0.62,
        4,
      );
    }

    ctx.globalAlpha = 1;
    const searchRing = (
      point: Vec,
      color: string,
      radius: number,
      distance = 4,
    ) => {
      const screen = { x: sx(point.x), y: sy(point.y) };
      if (
        screen.x < -radius ||
        screen.x > size.width + radius ||
        screen.y < -radius ||
        screen.y > size.height + radius
      ) {
        return;
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius + distance, 0, Math.PI * 2);
      ctx.stroke();
    };

    for (const item of data.feedback) {
      const point = layout.feedback.get(item.feedback_id);
      if (!point) continue;
      const px = sx(point.x);
      const py = sy(point.y);
      if (px < -4 || px > size.width + 4 || py < -4 || py > size.height + 4) continue;
      const key = nodeKey("feedback", item.feedback_id);
      const active = highlight ? highlight.nodes.has(key) : false;
      if (highlight && !active) {
        ctx.fillStyle = "rgba(148, 163, 184, 0.12)";
      } else if (active) {
        ctx.fillStyle = "#0f766e";
      } else {
        ctx.fillStyle = "rgba(100, 116, 139, 0.42)";
      }
      const dot = scale > 0.15 ? 0.8 : 0.45;
      ctx.fillRect(px - dot, py - dot, dot * 2, dot * 2);
      if (matches?.feedback.has(item.feedback_id)) searchRing(point, "#0f766e", 2, 2);
    }

    for (const theme of themeNodes) {
      const point = layout.themes.get(theme.problem_id);
      if (!point) continue;
      const screen = pointToScreen(point);
      const radius = clamp(2.3 + Math.sqrt(theme.mapped_feedback_count || 0) / 6, 2.8, 8) * clamp(scale / 0.08, 0.45, 1);
      if (
        screen.x < -radius - 4 ||
        screen.x > size.width + radius + 4 ||
        screen.y < -radius - 4 ||
        screen.y > size.height + radius + 4
      ) {
        continue;
      }
      const key = nodeKey("theme", theme.problem_id);
      const active = highlight ? highlight.nodes.has(key) : false;
      const selected = selection?.kind === "theme" && selection.id === theme.problem_id;
      ctx.globalAlpha = highlight && !active ? 0.16 : 0.88;
      ctx.fillStyle = factorColor(theme.primary_factor_rank);
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
      ctx.fill();
      if (selected) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "#17211d";
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.arc(screen.x, screen.y, radius + 4, 0, Math.PI * 2);
        ctx.stroke();
      }
      if (matches?.themes.has(theme.problem_id)) searchRing(point, "#0f766e", radius, 2);
      if (active || selected || scale > 0.22) {
        ctx.globalAlpha = highlight && !active ? 0.24 : 1;
        ctx.fillStyle = "#33413b";
        ctx.font = "500 10px ui-sans-serif, system-ui, sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(truncate(theme.title, 48), screen.x + radius + 5, screen.y + 3.5, 260);
      }
    }

    for (const factor of data.factors) {
      const point = layout.factors.get(factor.factor_id);
      if (!point) continue;
      const screen = pointToScreen(point);
      const key = nodeKey("factor", factor.factor_id);
      const active = highlight ? highlight.nodes.has(key) : false;
      const selected = selection?.kind === "factor" && selection.id === factor.factor_id;
      const radius = selected ? 12 : 10;
      ctx.globalAlpha = highlight && !active ? 0.18 : 1;
      ctx.fillStyle = factorColor(factor.rank);
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.font = "700 8.5px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(factor.factor_id, screen.x, screen.y + 3);
      if (selected) {
        ctx.strokeStyle = "#17211d";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(screen.x, screen.y, radius + 4, 0, Math.PI * 2);
        ctx.stroke();
      }
      if (matches?.factors.has(factor.factor_id)) searchRing(point, "#0f766e", radius, 2);
      ctx.globalAlpha = highlight && !active ? 0.24 : 1;
      ctx.textAlign = "left";
      ctx.fillStyle = "#17211d";
      ctx.font = "600 11px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText(`#${factor.rank} ${truncate(factor.factor_name, 27)}`, screen.x + 16, screen.y + 1, 165);
      ctx.fillStyle = "#66736d";
      ctx.font = "500 9.5px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText(
        `${factor.priority_score.toFixed(2)} priority · ${factor.evidence_coverage.toFixed(0)}% evidence`,
        screen.x + 16,
        screen.y + 13,
        165,
      );
    }

    for (const backlog of data.backlogs) {
      const point = layout.backlogs.get(backlog.backlog_id);
      if (!point) continue;
      const screen = pointToScreen(point);
      const key = nodeKey("backlog", backlog.backlog_id);
      const active = highlight ? highlight.nodes.has(key) : false;
      const selected = selection?.kind === "backlog" && selection.id === backlog.backlog_id;
      ctx.globalAlpha = highlight && !active ? 0.18 : 1;
      ctx.fillStyle = relationshipColor(backlog.best_relationship);
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, selected ? 9 : 7.5, 0, Math.PI * 2);
      ctx.fill();
      if (selected) {
        ctx.strokeStyle = "#17211d";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(screen.x, screen.y, 13, 0, Math.PI * 2);
        ctx.stroke();
      }
      if (matches?.backlogs.has(backlog.backlog_id)) searchRing(point, "#0f766e", 7.5, 2);
      ctx.textAlign = "left";
      ctx.fillStyle = "#17211d";
      ctx.font = "600 10.5px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText(
        `#${backlog.backlog_priority_rank || "—"} ${backlog.backlog_id}`,
        screen.x + 13,
        screen.y - 1,
        240,
      );
      ctx.fillStyle = "#66736d";
      ctx.font = "500 9.5px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText(truncate(backlog.title, 34), screen.x + 13, screen.y + 11, 180);
    }

    ctx.globalAlpha = 1;
  }, [
    data,
    highlight,
    index,
    layout,
    matches,
    pointToScreen,
    relationship,
    selection,
    size.height,
    size.width,
    view,
  ]);

  const hoveredDetails = useMemo(() => {
    if (!hovered) return null;
    if (hovered.selection.kind === "feedback") {
      const item = index.feedbackById.get(hovered.selection.id);
      return item
        ? {
            title: item.title || item.feedback_id,
            subtitle: `${item.feedback_id} · ${item.source_type || "feedback"}`,
            lines: [
              `${item.theme_count || 0} theme${(item.theme_count || 0) === 1 ? "" : "s"}`,
              item.primary_theme_id ? `Primary ${item.primary_theme_id}` : "Unmapped feedback",
            ],
          }
        : null;
    }
    if (hovered.selection.kind === "theme") {
      const item = index.themeById.get(hovered.selection.id);
      return item
        ? {
            title: item.title,
            subtitle: `${item.problem_id} · ${item.journey_name || "theme"}`,
            lines: [
              `${item.mapped_feedback_count || 0} feedback links`,
              item.primary_factor_id ? `Primary ${item.primary_factor_id}` : "No factor",
            ],
          }
        : null;
    }
    if (hovered.selection.kind === "factor") {
      const item = data.factors.find((factor) => factor.factor_id === hovered.selection.id);
      return item
        ? {
            title: item.factor_name,
            subtitle: `${item.factor_id} · priority rank ${item.rank}`,
            lines: [
              `${item.priority_score.toFixed(2)} priority`,
              `${(index.themeFactorByTarget.get(item.factor_id) || []).length} member themes`,
            ],
          }
        : null;
    }
    const item = data.backlogs.find((backlog) => backlog.backlog_id === hovered.selection.id);
    return item
      ? {
          title: item.title,
          subtitle: `${item.backlog_id} · ${item.product_area || "backlog"}`,
          lines: [
            item.priority ? `${item.priority} priority` : "Priority not set",
            `${item.covered_factor_count || 0} factors covered`,
          ],
        }
      : null;
  }, [data.backlogs, data.factors, hovered, index]);

  const tooltipStyle = hovered
    ? {
        left: clamp(hovered.x + 16, 8, Math.max(8, size.width - 268)),
        top: clamp(hovered.y + 16, 8, Math.max(8, size.height - 128)),
      }
    : undefined;

  const pointerPosition = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  return (
    <div className="mapping-graph" ref={containerRef}>
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
          const rect = event.currentTarget.getBoundingClientRect();
          const position = { x: event.clientX - rect.left, y: event.clientY - rect.top };
          const hit = findHit(position.x, position.y);
          if (hit) {
            onSelect(hit);
            focus(hit);
          }
        }}
        aria-label="Feedback to backlog mapping graph"
      />
      <div className="mapping-graph-controls">
        <button className="icon-btn" onClick={() => setZoom(1.35)} title="Zoom in" aria-label="Zoom in">
          <ZoomIn size={15} />
        </button>
        <button className="icon-btn" onClick={() => setZoom(1 / 1.35)} title="Zoom out" aria-label="Zoom out">
          <ZoomOut size={15} />
        </button>
        <button className="icon-btn" onClick={fit} title="Fit graph" aria-label="Fit graph">
          <Maximize2 size={15} />
        </button>
      </div>
      <div className="mapping-graph-hint">
        Scroll to zoom · drag to pan · click a node to trace its full path · double-click to focus
      </div>
      {hovered && hoveredDetails && (
        <div className="mapping-tooltip" style={tooltipStyle}>
          <strong>{hoveredDetails.title}</strong>
          <span>{hoveredDetails.subtitle}</span>
          {hoveredDetails.lines.map((line) => (
            <b key={line}>{line}</b>
          ))}
        </div>
      )}
    </div>
  );
}
