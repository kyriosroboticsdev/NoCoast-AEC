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
  ifc_url: string;
  created: number;
}

export interface Project {
  project: { id: string; name: string };
  head: Version | null;
  versions: Version[];
}

export interface StageEvent {
  stage: string; // program | edit | apply | solve | compile | done | error
  message: string;
  data: Record<string, unknown> | null;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BACKEND + path, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const health = () => json<{ ok: boolean; llm: { provider: string; model: string | null } }>("/health");

export const createProject = (name: string) =>
  json<{ id: string }>("/projects", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) });

export const getProject = (id: string) => json<Project>(`/projects/${id}`);

/** POST and stream SSE events to `onEvent`. Resolves with the "done" version or throws on "error". */
async function stream(path: string, init: RequestInit, onEvent: (e: StageEvent) => void): Promise<Version> {
  const r = await fetch(BACKEND + path, init);
  if (!r.ok || !r.body) throw new Error(`${r.status} ${await r.text()}`);
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
      onEvent(ev);
      if (ev.stage === "error") throw new Error(ev.message);
      if (ev.stage === "done") result = ev.data as unknown as Version;
    }
  }
  if (!result) throw new Error("stream ended without a result");
  return result;
}

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export const sendPrompt = (id: string, prompt: string, baseVersion: number | null, onEvent: (e: StageEvent) => void) =>
  stream(`/projects/${id}/prompt`, post({ prompt, base_version: baseVersion }), onEvent);

export const revert = (id: string, to: number, onEvent: (e: StageEvent) => void) =>
  stream(`/projects/${id}/revert/${to}`, { method: "POST" }, onEvent);

export const importIfc = (id: string, file: File, onEvent: (e: StageEvent) => void) => {
  const form = new FormData();
  form.append("file", file, file.name);
  return stream(`/projects/${id}/import`, { method: "POST", body: form }, onEvent);
};

export const fetchIfc = async (ifcUrl: string): Promise<Uint8Array> => {
  const r = await fetch(BACKEND + ifcUrl);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return new Uint8Array(await r.arrayBuffer());
};
