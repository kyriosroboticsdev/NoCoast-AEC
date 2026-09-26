// Thin client for the backend. Progress arrives as Server-Sent Events over a POST, so it is
// read with fetch + a streaming body parser rather than EventSource (which is GET-only).

export const BACKEND = (import.meta.env.VITE_BACKEND_URL as string | undefined) ?? "http://127.0.0.1:8765";

export interface Version {
  project_id: string;
  number: number;
  parent: number | null;
  prompt: string | null;
  mode: string;
  llm: string | null;
  notes: string[];
  summary: { counts: Record<string, number>; elements: number; storeys: string[]; spaces: string[] };
  ops: unknown[];
  checks?: { text: string; status: string; detail: string }[];
  ifc_url: string;
  created: number;
}

export interface Project {
  project: { id: string; name: string };
  head: Version | null;
  versions: Version[];
}

export interface StageEvent {
  seq: number; // ordinal within the request
  t: number; // seconds since the request started
  stage: string; // requirements | build | llm | stream | step | partial | verify | validate | apply | compile | done | error
  message: string;
  data: Record<string, unknown> | null;
}

export interface SliceLayer {
  phase: string;
  z: number;
  segments: [number, number, number, number][];
}

export interface Slices {
  layer_height: number;
  layers: SliceLayer[];
}

export interface ConstructionStatus {
  job_id: string;
  done: boolean;
  error: string | null;
  index: number;
  total: number;
  ifc_url: string | null;
}

const log = (...args: unknown[]) => console.log("[nocoast:api]", ...args);

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  log(init?.method ?? "GET", path);
  const r = await fetch(BACKEND + path, init);
  if (!r.ok) throw new Error(`${init?.method ?? "GET"} ${path} → ${r.status} ${await r.text()}`);
  return r.json();
}

export const health = () => json<{ ok: boolean; llm: { provider: string; model: string | null } }>("/health");

export const createProject = (name: string) =>
  json<{ id: string }>("/projects", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) });

export const getProject = (id: string) => json<Project>(`/projects/${id}`);

/** POST and stream SSE events to `onEvent`. Resolves with the "done" version or throws on "error". */
async function stream(path: string, init: RequestInit, onEvent: (e: StageEvent) => void): Promise<Version> {
  log("POST", path, "(SSE)");
  const r = await fetch(BACKEND + path, init);
  if (!r.ok || !r.body) throw new Error(`POST ${path} → ${r.status} ${await r.text()}`);
  const reader = r.body.getReader();
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
      const dataLine = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      const ev = JSON.parse(dataLine.slice(6)) as StageEvent;
      if (ev.stage === "stream") log("event", ev.seq, `${ev.t}s`, ev.stage, ev.message);
      else log("event", ev.seq, `${ev.t}s`, ev.stage, ev.message, ev.data ?? "");
      onEvent(ev);
      if (ev.stage === "error") throw new Error(ev.message);
      if (ev.stage === "done") result = ev.data as unknown as Version;
    }
  }
  if (!result) throw new Error("stream ended without a result");
  return result;
}

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export const sendPrompt = (id: string, prompt: string, baseVersion: number | null, onEvent: (e: StageEvent) => void, focus: string | null = null) =>
  stream(`/projects/${id}/prompt`, post({ prompt, base_version: baseVersion, focus }), onEvent);

/** The design record (rooms, doors, windows, …) and the derived spec of a version; `design` is null for pre-design-layer versions. */
export const fetchSpec = (id: string, number: number) =>
  json<{ design: Design | null; spec: { elements: Record<string, unknown>[]; levels: { id: string; name: string; elevation: number; height: number }[] } }>(`/projects/${id}/versions/${number}/spec`);

export interface Design {
  name: string;
  levels: { id: string; name: string | null; height: number }[];
  rooms: { id: string; name: string; level: string; kind: string; rect: [number, number, number, number] | null; area: number | null }[];
  doors: { id: string; room: string; to: string; side: string | null; at: number; kind: string; width: number; height: number }[];
  windows: { id: string; room: string; side: string; at: number; kind: string; width: number; height: number; sill: number | null }[];
  stairs: { id: string; room: string; side: string; to_level: string | null; width: number }[];
  fixtures: { id: string; room: string; kind: string; side: string; at: number; rotation: number | null; width: number | null; depth: number | null; height: number | null }[];
  balconies: { id: string; room: string; side: string; depth: number }[];
  columns: { id: string; level: string; x: number; y: number }[];
  porch: { side: string; depth: number } | null;
  roof: { kind: string; pitch: number; overhang: number };
  wall_material: string | null;
}

export const revert = (id: string, to: number, onEvent: (e: StageEvent) => void) =>
  stream(`/projects/${id}/revert/${to}`, { method: "POST" }, onEvent);

export const importIfc = (id: string, file: File, onEvent: (e: StageEvent) => void) => {
  const form = new FormData();
  form.append("file", file, file.name);
  return stream(`/projects/${id}/import`, { method: "POST", body: form }, onEvent);
};

export const fetchSlices = (id: string, number: number, layerHeight = 0.2) =>
  json<Slices>(`/projects/${id}/versions/${number}/slices?layer_height=${layerHeight}`);

export const startConstruction = (id: string, number: number) =>
  json<ConstructionStatus>(`/projects/${id}/versions/${number}/construction`, { method: "POST" });

export const constructionStatus = (id: string, number: number, jobId: string) =>
  json<ConstructionStatus>(`/projects/${id}/versions/${number}/construction/${jobId}`);

export const fetchIfc = async (ifcUrl: string): Promise<Uint8Array> => {
  const r = await fetch(BACKEND + ifcUrl);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return new Uint8Array(await r.arrayBuffer());
};
