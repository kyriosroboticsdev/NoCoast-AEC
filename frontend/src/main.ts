// Rudimentary UI: a viewer and a prompt box. State = one project id (kept in localStorage) + its head version.

import * as api from "./api";
import { Viewer } from "./viewer";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const text = $<HTMLTextAreaElement>("text");
const send = $<HTMLButtonElement>("send");
const status = $<HTMLDivElement>("status");
const notes = $<HTMLPreElement>("notes");
const undo = $<HTMLButtonElement>("undo");
const download = $<HTMLAnchorElement>("download");
const projectLabel = $<HTMLSpanElement>("project");
const picked = $<HTMLSpanElement>("picked");

let projectId = "";
let head: api.Version | null = null;
let busy = false;

const viewer = new Viewer($<HTMLCanvasElement>("viewport"), (p) => {
  picked.textContent = p ? `${p.type} ${p.tag || p.name} ${p.globalId}` : "";
});

function setStatus(msg: string, error = false) {
  status.textContent = msg;
  status.classList.toggle("error", error);
}

function setBusy(b: boolean) {
  busy = b;
  send.disabled = b;
  undo.disabled = b || !head || head.number < 2;
}

async function showVersion(v: api.Version | null) {
  head = v;
  projectLabel.textContent = v ? `project ${projectId} · v${v.number} (${v.mode}${v.llm ? ", " + v.llm : ""})` : `project ${projectId} · empty`;
  download.hidden = !v;
  if (v) {
    download.href = api.BACKEND + v.ifc_url;
    download.download = `nocoast-v${v.number}.ifc`;
    notes.textContent = [...v.notes, `elements: ${JSON.stringify(v.summary.counts)}`].join("\n");
    viewer.load(await api.fetchIfc(v.ifc_url));
  } else {
    notes.textContent = "";
    viewer.clear();
  }
  setBusy(false);
}

const onEvent = (e: api.StageEvent) => {
  const errs = (e.data?.errors as string[] | undefined) ?? [];
  setStatus(`${e.stage}: ${e.message}${errs.length ? " — " + errs.join("; ") : ""}`);
};

async function run(work: () => Promise<api.Version>) {
  if (busy) return;
  setBusy(true);
  try {
    await showVersion(await work());
    setStatus(`v${head!.number} loaded`);
  } catch (err) {
    setStatus(String(err instanceof Error ? err.message : err), true);
    setBusy(false);
  }
}

send.onclick = () => {
  const prompt = text.value.trim();
  if (!prompt) return;
  run(() => api.sendPrompt(projectId, prompt, head?.number ?? null, onEvent)).then(() => (text.value = ""));
};
text.onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send.click();
  }
};
undo.onclick = () => head && run(() => api.revert(projectId, head!.number - 1, onEvent));
$<HTMLInputElement>("import").onchange = (e) => {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (file) run(() => api.importIfc(projectId, file, onEvent));
};
$<HTMLButtonElement>("new").onclick = () => openProject(null);

async function openProject(id: string | null) {
  if (!id) {
    id = (await api.createProject("Untitled")).id;
    localStorage.setItem("nocoast.project", id);
  }
  projectId = id;
  const p = await api.getProject(id);
  await showVersion(p.head);
}

async function boot() {
  setStatus("connecting to backend…");
  for (let attempt = 0; ; attempt++) {
    try {
      const h = await api.health();
      setStatus(`backend ok · llm: ${h.llm.provider}${h.llm.model ? " " + h.llm.model : ""}`);
      break;
    } catch {
      if (attempt > 40) return setStatus(`backend not reachable at ${api.BACKEND}`, true);
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  try {
    // ?project=<id> deep-links a project (also how the headless smoke test opens one).
    await openProject(new URLSearchParams(location.search).get("project") ?? localStorage.getItem("nocoast.project"));
  } catch {
    await openProject(null); // stale id from an older database
  }
}

boot();
