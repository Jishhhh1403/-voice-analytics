export const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body);
    } catch {
      /* ignore non-json error body */
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function postJSON<T>(path: string, body: unknown, idempotencyKey?: string): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    },
    body: JSON.stringify(body),
  });
}

export function postForm<T>(path: string, form: FormData): Promise<T> {
  return api<T>(path, { method: "POST", body: form });
}

export async function download(path: string, filename: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new ApiError("Download failed", response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function startDimensionRun(payload: {
  feedback_run_id?: string | null;
  max_components?: number | null;
  force_rerun?: boolean;
}): Promise<{ run_id: string; status: string; stage?: string | null }> {
  return postJSON("/problem-dimensions/runs?background=true", {
    feedback_run_id: payload.feedback_run_id ?? null,
    max_components: payload.max_components ?? null,
    force_rerun: Boolean(payload.force_rerun),
  });
}

export function reviewDimension(
  runId: string,
  dimensionId: string,
  payload: {
    reviewer: string;
    decision: "approve" | "reject" | "rename" | "request_revision";
    name?: string;
    description?: string;
    note?: string;
  },
) {
  return postJSON(`/problem-dimensions/runs/${runId}/dimensions/${dimensionId}/review`, payload);
}

export function publishDimensionRun(runId: string, publishedBy: string, note = "") {
  return postJSON(`/problem-dimensions/runs/${runId}/publish`, { published_by: publishedBy, note });
}

export function coefficientMatrixPath(runId: string): string {
  return `/problem-dimensions/runs/${runId}/coefficients`;
}

export function coefficientMatrixDownloadPath(runId: string): string {
  return `/problem-dimensions/runs/${runId}/coefficients.csv`;
}

export function narrativeSerializationPath(runId: string): string {
  return `/problem-dimensions/runs/${runId}/narrative-serialization`;
}

export function generateNarrativeSerialization(runId: string) {
  return api(narrativeSerializationPath(runId), { method: "POST" });
}

export function startPortfolioRun(payload: {
  feedback_run_id?: string | null;
  dimension_run_id?: string | null;
  force_rerun?: boolean;
  generate_narrative?: boolean;
}): Promise<{ run_id: string; status: string; stage?: string | null }> {
  return postJSON("/problem-portfolio/runs?background=true", {
    feedback_run_id: payload.feedback_run_id ?? null,
    dimension_run_id: payload.dimension_run_id ?? null,
    force_rerun: Boolean(payload.force_rerun),
    generate_narrative: payload.generate_narrative !== false,
  });
}

export function regeneratePortfolioNarrative(runId: string, force = true) {
  return postJSON(`/problem-portfolio/runs/${runId}/narrative/regenerate`, { force });
}

export function startFactorPrioritisationRun(payload: {
  famd_run_id?: string | null;
  feedback_run_id?: string | null;
  weights?: Record<string, number> | null;
  force_rerun?: boolean;
}): Promise<{ run_id: string; status: string }> {
  return postJSON("/factor-prioritisation/runs?background=true", {
    famd_run_id: payload.famd_run_id ?? null,
    feedback_run_id: payload.feedback_run_id ?? null,
    weights: payload.weights ?? null,
    force_rerun: Boolean(payload.force_rerun),
  });
}

export function reviewFactorSemanticAssessment(
  runId: string,
  factorId: string,
  payload: { reviewer: string; decision: "approve" | "reject" | "request_revision"; note?: string },
) {
  return postJSON(`/factor-prioritisation/runs/${runId}/factors/${factorId}/semantic-assessment/review`, payload);
}
