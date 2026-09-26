// Rudimentary UI: a viewer and a prompt box. State = one project id (kept in localStorage) + its head version.

import * as api from "./api";
import { Viewer } from "./viewer";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
// Verbose console log: open DevTools (F12) and filter on [nocoast].
export const log = (...args: unknown[]) => console.log("[nocoast]", new Date().toISOString().slice(11, 23), ...args);
window.addEventListener("error", (e) => console.error("[nocoast] uncaught:", e.message, e.error));
window.addEventListener("unhandledrejection", (e) => console.error("[nocoast] unhandled rejection:", e.reason));
log("page loaded", location.href, "backend:", api.BACKEND, "userAgent:", navigator.userAgent);
const text = $<HTMLTextAreaElement>("text");
const send = $<HTMLButtonElement>("send");
const status = $<HTMLDivElement>("status");
const notes = $<HTMLPreElement>("notes");
const undo = $<HTMLButtonElement>("undo");
const download = $<HTMLAnchorElement>("download");
const projectLabel = $<HTMLSpanElement>("project");
const picked = $<HTMLSpanElement>("picked");
const showing = $<HTMLDivElement>("showing");
const stepsList = $<HTMLOListElement>("steps-list");
const stepsText = $<HTMLPreElement>("steps-text");
const stepsJson = $<HTMLInputElement>("steps-json");

let projectId = "";
let head: api.Version | null = null;
let busy = false;

const viewer = new Viewer($<HTMLCanvasElement>("viewport"), (p) => {
  picked.textContent = p ? `${p.type} ${p.tag || p.name} ${p.globalId}` : "";
});

function setStatus(msg: string, error = false) {
  status.textContent = msg;
  status.classList.toggle("error", error);
  (error ? console.error : console.log)("[nocoast] status:", msg);
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
    const checks = (v.checks ?? []).filter((c) => c.status !== "met").map((c) => `${c.status === "unmet" ? "✗" : "–"} ${c.text}: ${c.detail}`);
    notes.textContent = [...v.notes, ...checks, `elements: ${JSON.stringify(v.summary.counts)}`].join("\n");
    log("version", v.number, v.mode, "fetching", v.ifc_url);
    const bytes = await api.fetchIfc(v.ifc_url);
    log("ifc fetched:", bytes.length, "bytes; loading into web-ifc");
    const t = performance.now();
    await viewer.load(bytes);
    log("viewer loaded in", Math.round(performance.now() - t), "ms");
    shownRow?.classList.remove("shown");
    shownRow = null;
    setShowing(`v${v.number} · final · ${v.summary.elements} elements`, false);
  } else {
    notes.textContent = "";
    viewer.clear();
    setShowing("", false);
  }
  setBusy(false);
}

// --- step log ------------------------------------------------------------------------------------
// One row per SSE event. `stream` events update a single row (and the live model-output pane);
// `partial` rows are clickable so earlier previews can be re-shown after the run.

let streamRow: HTMLLIElement | null = null;
let shownRow: HTMLLIElement | null = null;

function setShowing(label: string, preview: boolean) {
  showing.textContent = label;
  showing.classList.toggle("preview", preview);
}

function stepRow(e: api.StageEvent, detail?: string): HTMLLIElement {
  const li = document.createElement("li");
  li.className = e.stage;
  li.innerHTML = `<span class="t">${e.t.toFixed(1)}s</span><span class="stage">${e.stage}</span> `;
  li.append(document.createTextNode(e.message));
  if (detail) {
    const d = document.createElement("span");
    d.className = "detail";
    d.textContent = detail;
    li.append(d);
  }
  stepsList.append(li);
  li.scrollIntoView({ block: "nearest" });
  return li;
}

function detailFor(e: api.StageEvent): string | undefined {
  const d = e.data ?? {};
  const errs = d.errors as string[] | undefined;
  if (errs?.length) return errs.map((x) => "• " + x).join("\n");
  if (e.stage === "llm" && d.model) return `${d.provider} ${d.model} · system ${d.system_chars} chars · user ${d.user_chars} chars`;
  if (e.stage === "requirements" && Array.isArray(d.requirements)) {
    const reqs = d.requirements as { text: string; kind: string; supported?: boolean }[];
    return reqs.map((r) => `${r.supported === false ? "✗" : "•"} ${r.text} [${r.kind}]`).join("\n");
  }
  if (e.stage === "build") {
    const p = (d.problems as string[]) ?? [];
    const u = (d.unmet as string[]) ?? [];
    return [...p, ...u].map((x) => "• " + x).join("\n") || undefined;
  }
  if (e.stage === "step") {
    if (d.ok === false) return `${JSON.stringify(d.step)}\n${d.error}`;
    return undefined;
  }
  if (e.stage === "verify" && Array.isArray(d.results)) {
    const rs = d.results as { text: string; status: string; detail: string }[];
    const mark: Record<string, string> = { met: "✓", unmet: "✗", unsupported: "–", skipped: "?" };
    return rs.map((r) => `${mark[r.status] ?? "?"} ${r.text} — ${r.detail}`).join("\n");
  }
  if (e.stage === "validate" && Array.isArray(d.rooms)) return (d.rooms as string[]).join(", ");
  if (e.stage === "apply" && Array.isArray(d.cascade)) return (d.cascade as string[]).map((x) => "• " + x).join("\n");
  if (e.stage === "partial" && typeof d.ifc_url === "string") {
    const rooms = d.rooms as Record<string, string[]>;
    const roomLine = Object.entries(rooms ?? {}).map(([l, n]) => `${l}: ${n.join(", ") || "–"}`).join(" | ");
    return `${JSON.stringify(d.counts)} · compiled in ${d.compile_ms} ms after ${d.steps} steps (${d.checked} re-checked)\n${roomLine}`;
  }
  if (e.stage === "done") {
    const v = d as unknown as api.Version;
    return `v${v.number} ${v.mode} · ${JSON.stringify(v.summary?.counts)}${v.notes?.length ? "\n" + v.notes.map((n) => "• " + n).join("\n") : ""}`;
  }
  return undefined;
}

function resetSteps() {
  stepsList.replaceChildren();
  stepsText.textContent = "";
  streamRow = shownRow = null;
}

stepsJson.onchange = () => (stepsText.hidden = !stepsJson.checked);

// --- previews --------------------------------------------------------------------------------------
// The backend emits `partial` events with a geometry-checked IFC of what the model has produced so far.
// Loads are serialised, only the newest pending preview is loaded, and nothing is loaded once the
// final version has arrived (unless the user clicks a preview row afterwards).
let previewChain = Promise.resolve();
let pendingPreview: { url: string; label: string; row: HTMLLIElement } | null = null;
let finalArrived = false;

function queuePreview(p: { url: string; label: string; row: HTMLLIElement }) {
  pendingPreview = p;
  previewChain = previewChain.then(async () => {
    const q = pendingPreview;
    if (!q || finalArrived) return;
    pendingPreview = null;
    await showPreview(q);
  });
}

async function showPreview(p: { url: string; label: string; row: HTMLLIElement }) {
  try {
    const bytes = await api.fetchIfc(p.url);
    if (finalArrived && busy) return;
    await viewer.load(bytes);
    shownRow?.classList.remove("shown");
    shownRow = p.row;
    p.row.classList.add("shown");
    setShowing(p.label, true);
    log("preview shown", p.url);
  } catch (err) {
    log("preview skipped:", String(err));
  }
}

const onEvent = (e: api.StageEvent) => {
  const errs = (e.data?.errors as string[] | undefined) ?? [];
  if (e.stage === "stream") {
    stepsText.textContent = String(e.data?.text ?? "");
    stepsText.scrollTop = stepsText.scrollHeight;
    if (!streamRow) streamRow = stepRow(e);
    else streamRow.innerHTML = `<span class="t">${e.t.toFixed(1)}s</span><span class="stage">stream</span> ${e.message}`;
    status.textContent = `streaming: ${e.message}`;
    return;
  }
  if (e.stage !== "step" && e.stage !== "partial") streamRow = null; // the next stream event (a new round) starts a fresh row
  const row = stepRow(e, detailFor(e));
  if (e.stage === "validate" && errs.length) row.classList.add("bad");
  if (e.stage === "step" && e.data?.ok === false) row.classList.add("bad");
  if (e.stage === "verify" && ((e.data?.unmet as string[]) ?? []).length) row.classList.add("bad");
  if (e.stage === "requirements" && ((e.data?.unsupported as string[]) ?? []).length) row.classList.add("bad");
  if (e.stage === "partial" && typeof e.data?.ifc_url === "string") {
    const label = `preview ${e.data.preview} · ${e.data.elements} elements`;
    const p = { url: e.data.ifc_url, label, row };
    row.onclick = () => {
      if (!busy) previewChain = previewChain.then(() => showPreview(p));
    };
    queuePreview(p);
  }
  setStatus(`${e.stage}: ${e.message}${errs.length ? " — " + errs.join("; ") : ""}`);
};

async function run(work: () => Promise<api.Version>) {
  if (busy) return;
  setBusy(true);
  finalArrived = false;
  resetSteps();
  try {
    const version = await work();
    finalArrived = true;
    await previewChain; // let an in-flight preview finish before the final model replaces it
    await showVersion(version);
    setStatus(`v${head!.number} loaded`);
  } catch (err) {
    finalArrived = true;
    console.error("[nocoast] request failed:", err);
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
    log("created project", id);
  }
  projectId = id;
  const p = await api.getProject(id);
  log("opened project", id, "versions:", p.versions.length, "head:", p.head?.number ?? null);
  await showVersion(p.head);
}

async function boot() {
  setStatus("connecting to backend…");
  for (let attempt = 0; ; attempt++) {
    try {
      const h = await api.health();
      log("health:", h);
      setStatus(`backend ok · llm: ${h.llm.provider}${h.llm.model ? " " + h.llm.model : ""}`);
      break;
    } catch (err) {
      if (attempt % 10 === 0) log("backend not reachable yet:", String(err));
      if (attempt > 40) return setStatus(`backend not reachable at ${api.BACKEND} — start it with: cd backend && python main.py`, true);
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  const params = new URLSearchParams(location.search);
  try {
    // ?project=<id> deep-links a project (also how the headless smoke test opens one).
    await openProject(params.get("project") ?? localStorage.getItem("nocoast.project"));
  } catch (err) {
    log("stored project could not be opened, creating a new one:", String(err));
    await openProject(null); // stale id from an older database
  }
  const auto = params.get("prompt"); // ?prompt=… sends a prompt on load (smoke tests, demos)
  if (auto) {
    text.value = auto;
    send.click();
  }
}

boot();
