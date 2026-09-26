// Backend API. The UI knows prompt → plan → IFC URL, nothing about how planning works.

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

export const plan = (prompt: string, planner?: string) => post<PlanResult>("/plan", { prompt, planner });
export const build = (spec: PlanResult["spec"]) => post<BuildResult>("/build", { spec });

export async function fetchBytes(url: string): Promise<Uint8Array> {
  // "/models/x.ifc" is a backend path; anything else is resolved against the page.
  const res = await fetch(url.startsWith("/") ? `${BACKEND}${url}` : new URL(url, location.href).href);
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

export async function info(): Promise<{ ok: boolean; planners: string[] }> {
  try {
    const res = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok ? await res.json() : { ok: false, planners: [] };
  } catch {
    return { ok: false, planners: [] };
  }
}

export async function health(): Promise<boolean> {
  return (await info()).ok;
}
