import type {
  MappingFactorBacklogLink,
  MappingFeedbackNode,
  MappingFeedbackThemeLink,
  MappingGraphResponse,
  MappingSearchResult,
  MappingThemeFactorLink,
  MappingThemeNode,
} from "./types";

export const FACTOR_COLORS = [
  "#0f766e",
  "#2563eb",
  "#7c3aed",
  "#db2777",
  "#ea580c",
  "#0891b2",
  "#65a30d",
  "#9333ea",
  "#dc2626",
  "#ca8a04",
  "#0d9488",
  "#4f46e5",
];

export const RELATIONSHIP_COLORS: Record<string, string> = {
  COVERS: "#0f9f7a",
  PARTIALLY_COVERS: "#2563eb",
  RELATED: "#7c3aed",
  NOT_COVERED: "#dc2626",
  NEEDS_REVIEW: "#d97706",
};

export function factorColor(rank?: number | null): string {
  const index = Math.max(0, (rank || 1) - 1) % FACTOR_COLORS.length;
  return FACTOR_COLORS[index];
}

export function relationshipColor(relationship?: string | null): string {
  return RELATIONSHIP_COLORS[relationship || ""] || "#8b9791";
}

export type MappingIndex = {
  feedbackById: Map<string, MappingFeedbackNode>;
  themeById: Map<string, MappingThemeNode>;
  feedbackThemeBySource: Map<string, MappingFeedbackThemeLink[]>;
  feedbackThemeByTarget: Map<string, MappingFeedbackThemeLink[]>;
  themeFactorBySource: Map<string, MappingThemeFactorLink[]>;
  themeFactorByTarget: Map<string, MappingThemeFactorLink[]>;
  factorBacklogBySource: Map<string, MappingFactorBacklogLink[]>;
  factorBacklogByTarget: Map<string, MappingFactorBacklogLink[]>;
  factorRankById: Map<string, number>;
  themeFactorLinksByTheme: Map<string, MappingThemeFactorLink[]>;
};

function push<K, V>(map: Map<K, V[]>, key: K, value: V) {
  const current = map.get(key);
  if (current) current.push(value);
  else map.set(key, [value]);
}

export function buildMappingIndex(data: MappingGraphResponse): MappingIndex {
  const feedbackById = new Map(data.feedback.map((item) => [item.feedback_id, item]));
  const themeById = new Map(data.themes.map((item) => [item.problem_id, item]));
  const feedbackThemeBySource = new Map<string, MappingFeedbackThemeLink[]>();
  const feedbackThemeByTarget = new Map<string, MappingFeedbackThemeLink[]>();
  const themeFactorBySource = new Map<string, MappingThemeFactorLink[]>();
  const themeFactorByTarget = new Map<string, MappingThemeFactorLink[]>();
  const factorBacklogBySource = new Map<string, MappingFactorBacklogLink[]>();
  const factorBacklogByTarget = new Map<string, MappingFactorBacklogLink[]>();
  const factorRankById = new Map(data.factors.map((item) => [item.factor_id, item.rank]));

  for (const link of data.links.feedback_theme) {
    push(feedbackThemeBySource, link.source, link);
    push(feedbackThemeByTarget, link.target, link);
  }
  for (const link of data.links.theme_factor) {
    push(themeFactorBySource, link.source, link);
    push(themeFactorByTarget, link.target, link);
  }
  for (const link of data.links.factor_backlog) {
    push(factorBacklogBySource, link.source, link);
    push(factorBacklogByTarget, link.target, link);
  }

  return {
    feedbackById,
    themeById,
    feedbackThemeBySource,
    feedbackThemeByTarget,
    themeFactorBySource,
    themeFactorByTarget,
    factorBacklogBySource,
    factorBacklogByTarget,
    factorRankById,
    themeFactorLinksByTheme: themeFactorBySource,
  };
}

function includes(value: string | null | undefined, query: string): boolean {
  return Boolean(value && value.toLowerCase().includes(query));
}

export function searchMappings(
  data: MappingGraphResponse,
  query: string,
  limit = 10,
): MappingSearchResult[] {
  const needle = query.trim().toLowerCase();
  if (needle.length < 2) return [];
  const results: MappingSearchResult[] = [];

  for (const item of data.feedback) {
    const idMatch = item.feedback_id.toLowerCase().startsWith(needle);
    if (
      idMatch ||
      includes(item.title, needle) ||
      includes(item.text, needle) ||
      includes(item.source_type, needle)
    ) {
      results.push({
        kind: "feedback",
        id: item.feedback_id,
        label: item.title || item.feedback_id,
        subtitle: `${item.feedback_id} · ${item.source_type || "feedback"}`,
        score: idMatch ? 4 : 1,
      });
      if (results.length >= limit * 8) break;
    }
  }
  for (const item of data.themes) {
    const idMatch = item.problem_id.toLowerCase().startsWith(needle);
    if (
      idMatch ||
      includes(item.title, needle) ||
      includes(item.problem_statement, needle) ||
      includes(item.journey_name, needle)
    ) {
      results.push({
        kind: "theme",
        id: item.problem_id,
        label: item.title || item.problem_id,
        subtitle: `${item.problem_id} · ${item.journey_name || "theme"}`,
        score: idMatch ? 5 : 2,
      });
    }
  }
  for (const item of data.factors) {
    if (
      includes(item.factor_id, needle) ||
      includes(item.factor_name, needle) ||
      includes(item.dimension_id, needle)
    ) {
      results.push({
        kind: "factor",
        id: item.factor_id,
        label: item.factor_name,
        subtitle: `${item.factor_id} · priority rank ${item.rank}`,
        score: item.factor_id.toLowerCase() === needle ? 8 : 3,
      });
    }
  }
  for (const item of data.backlogs) {
    if (
      includes(item.backlog_id, needle) ||
      includes(item.title, needle) ||
      includes(item.product_area, needle) ||
      includes(item.business_goal, needle)
    ) {
      results.push({
        kind: "backlog",
        id: item.backlog_id,
        label: item.title,
        subtitle: `${item.backlog_id} · ${item.product_area || "backlog"}`,
        score: item.backlog_id.toLowerCase() === needle ? 8 : 3,
      });
    }
  }

  const seen = new Set<string>();
  return results
    .sort((a, b) => b.score - a.score || a.label.localeCompare(b.label))
    .filter((item) => {
      const key = `${item.kind}:${item.id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, limit);
}
