// Backend API. The UI knows prompt → plan → IFC URL, nothing about how planning works.
import type { Design } from "../state/design";

let BACKEND = "http://127.0.0.1:8765";

export function setBackendUrl(url: string) {
  BACKEND = url.replace(/\/$/, "");
}

export interface PlanResult {
  spec: { building: { name: string }; levels: unknown[]; elements: unknown[] };
  planner: string;
  notes: string[];
}

export interface BuildResult {
  id: string;
  ifc_url: string;
  summary: { schema: string; storeys: string[]; spaces: string[]; elements: number; counts: Record<string, number> };
  seconds: number;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BACKEND}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail, () => res.statusText);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export const plan = (prompt: string) => post<PlanResult>("/plan", { prompt });
export const build = (spec: PlanResult["spec"]) => post<BuildResult>("/build", { spec });

// --- Versioned projects: the agent loop -------------------------------------
// Each prompt produces a new version of a project; edits are applied to a base
// version, so the history can be browsed and reverted.

export interface Version {
  project_id: string;
  number: number;
  parent: number | null;
  prompt: string | null;
  mode: string;
  llm: string | null;
  notes: string[];
  summary: { schema?: string; counts: Record<string, number>; elements: number; storeys: string[]; spaces: string[] };
  ifc_url: string;
  created: number;
  /** Requirement checks from the design layer (met | unmet | unsupported | skipped). */
  checks?: RequirementCheck[];
}

export interface RequirementCheck {
  text: string;
  status: "met" | "unmet" | "unsupported" | "skipped" | string;
  detail?: string;
}

export interface ProjectDetail {
  project: { id: string; name: string };
  head: Version | null;
  versions: Version[];
}

/** One progress event from the pipeline: program | edit | apply | solve | compile | done | error. */
export interface StageEvent {
  stage: string;
  message: string;
  data: Record<string, unknown> | null;
  /** Sequence number and seconds since the request started. */
  seq?: number;
  t?: number;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BACKEND}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status} ${await res.text()}`);
  return res.json();
}

export const createProject = (name = "Untitled") => post<{ id: string }>("/projects", { name });
export const getProject = (id: string) => getJson<ProjectDetail>(`/projects/${id}`);

/**
 * POST and read Server-Sent Events from the response body (EventSource is
 * GET-only). Resolves with the finished version or throws on an error event.
 */
async function stream(path: string, init: RequestInit, onEvent: (e: StageEvent) => void): Promise<Version> {
  const res = await fetch(`${BACKEND}${path}`, init);
  if (!res.ok || !res.body) throw new Error(`POST ${path} → ${res.status} ${await res.text()}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: Version | undefined;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const ev = JSON.parse(line.slice(6)) as StageEvent;
      onEvent(ev);
      if (ev.stage === "error") {
        const errors = (ev.data?.errors as string[] | undefined) ?? [];
        throw new Error([ev.message, ...errors].join("\n"));
      }
      if (ev.stage === "done") result = ev.data as unknown as Version;
    }
  }
  if (!result) throw new Error("The pipeline stream ended without a result.");
  return result;
}

const jsonPost = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** New design (no base) or an edit of `baseVersion`. `planner` picks an LLM provider (backend default if omitted). */
export const sendPrompt = (
  id: string, prompt: string, baseVersion: number | null, onEvent: (e: StageEvent) => void, planner?: string,
  focus?: string | null,
) => stream(`/projects/${id}/prompt`, jsonPost({ prompt, base_version: baseVersion, planner, focus: focus ?? undefined }), onEvent);

/** The structured BIM instructions behind a version, and its design record (null for imports and pre-design-layer versions). */
export const getSpec = (id: string, n: number) => getJson<{ spec: unknown; design: Design | null }>(`/projects/${id}/versions/${n}/spec`);

/** Make an older version the new head (recorded as a new version). */
export const revert = (id: string, to: number, onEvent: (e: StageEvent) => void) =>
  stream(`/projects/${id}/revert/${to}`, { method: "POST" }, onEvent);

/** Absolute URL for a backend-relative path such as a version's ifc_url. */
export const backendUrl = (path: string) => (path.startsWith("/") ? `${BACKEND}${path}` : path);

export async function fetchBytes(url: string): Promise<Uint8Array> {
  // "/models/x.ifc" is a backend path; anything else is already a full URL.
  const res = await fetch(url.startsWith("/") ? `${BACKEND}${url}` : url);
  if (!res.ok) throw new Error(`download failed: ${res.status}`);
  return new Uint8Array(await res.arrayBuffer());
}

/** The desktop shell starts the backend at launch; give it time to come up. */
export async function waitForBackend(timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!(await health())) {
    if (Date.now() > deadline) throw new Error(`Backend not reachable at ${BACKEND}. Start it with: python main.py (in backend/)`);
    await new Promise((r) => setTimeout(r, 400));
  }
}

export interface HealthInfo {
  ok: boolean;
  /** LLM providers the backend can use for prompts, and the one it uses by default. */
  llm: { provider: string; model: string | null; providers: string[] } | null;
}

export async function info(): Promise<HealthInfo> {
  try {
    const res = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok ? await res.json() : { ok: false, llm: null };
  } catch {
    return { ok: false, llm: null };
  }
}

export async function health(): Promise<boolean> {
  return (await info()).ok;
}
