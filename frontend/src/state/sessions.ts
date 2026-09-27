// Sessions = one conversation, backed by one versioned project on the backend: the
// first prompt designs a building, later prompts edit the head version. Persisted in
// localStorage (per-machine convenience only; projects and IFCs live on the backend,
// and files opened from disk live in IndexedDB — see state/files.ts).
//
// Persistence has to survive the app being closed mid-run, a storage quota that a long
// trace can hit, and a second window writing the same key, so:
//   • writes are debounced and flushed when the window goes away,
//   • a write that does not fit sheds traces, then the oldest sessions, instead of
//     silently losing the whole list,
//   • the active session id is stored too, so reopening lands where you left off,
//   • another window's write is merged in (newest copy of each session wins) and
//     deletions are remembered so a merge cannot resurrect them.
import { useCallback, useEffect, useState } from "react";
import type { Version } from "../api/client";

export type Stage = "planning" | "building" | "loading" | "done" | "error";

/**
 * Stage of the work a trace step belongs to — the trace is grouped under these, in the order a
 * project actually goes through them. ("plan" | "validate" | "build" | "load" are the older names,
 * still found in sessions persisted by an earlier version.)
 */
export type TracePhase =
  | "brief" | "research" | "massing" | "plan" | "circulation" | "envelope" | "structure" | "fitout" | "review" | "output"
  | "validate" | "build" | "load";

/** One line of the live reasoning trace (from the backend stream, or the viewer's load steps). */
export interface TraceStep {
  id: string;
  parent: string | null;
  phase: TracePhase;
  title: string;
  detail: string | null;
  status: "running" | "done" | "error";
  ms?: number;
  /** Backend path of a screenshot the model was shown at this step. */
  image?: string | null;
  layer?: boolean;
  error?: string;
  /** The model's own reasoning for this move, in its words. */
  why?: string | null;
  /** The quantities behind it ("16 m² · 4.0 × 4.0 m"), shown next to the title. */
  metric?: string | null;
}

export interface Run {
  stage: Stage;
  error?: string;
  /** The project version this run produced. */
  version?: Version;
  steps?: TraceStep[];
  /** The design strategy the model wrote before it started building. */
  approach?: string;
  /** What the model is writing this instant; cleared as soon as the step lands. */
  drafting?: string | null;
  startedAt?: number;
  endedAt?: number;
}

/** An image the user attached to a prompt. `dataUrl` lives only in memory; `url` is the backend's copy. */
export interface MessageImage {
  name: string;
  mediaType: string;
  size: number;
  url?: string;
  dataUrl?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  images?: MessageImage[];
  run?: Run;
}

export interface ModelRef {
  name: string;
  /** backend path (/projects/…/ifc) or bundled URL; for a file opened from disk the bytes are in IndexedDB */
  url?: string;
}

export interface Session {
  id: string;
  title: string;
  createdAt: number;
  /** Last change, used to order the list and to resolve two windows writing the same session. */
  updatedAt?: number;
  messages: Message[];
  model?: ModelRef;
  /** Backend project; `head` is the newest version (what the next prompt edits). */
  project?: { id: string; head: number | null };
}

export const SESSIONS_KEY = "gbim.sessions.v2"; // v1 sessions pointed at the stateless /models API
export const ACTIVE_KEY = "gbim.active.v1";
const REMOVED_KEY = "gbim.removed.v1";

const MAX_SESSIONS = 50;
const MAX_REMOVED = 200;
/** A run writes many trace steps a second; batch them into one write. */
const WRITE_DELAY = 250;

export const uid = () => Math.random().toString(36).slice(2, 10);

const stamp = (s: Session) => s.updatedAt ?? s.createdAt ?? 0;
const byRecency = (a: Session, b: Session) => stamp(b) - stamp(a);

// --- reading -----------------------------------------------------------------

const isSession = (s: unknown): s is Session =>
  !!s && typeof s === "object"
  && typeof (s as Session).id === "string"
  && typeof (s as Session).title === "string"
  && Array.isArray((s as Session).messages);

/** A run that was still going when the app closed can't resume. */
function settle(s: Session): Session {
  if (!s.messages.some((m) => m.run && m.run.stage !== "done" && m.run.stage !== "error")) return s;
  return {
    ...s,
    messages: s.messages.map((m) => (m.run && m.run.stage !== "done" && m.run.stage !== "error"
      ? {
        ...m,
        run: {
          ...m.run,
          stage: "error" as const,
          error: m.run.error ?? "Interrupted",
          steps: m.run.steps?.map((st) => (st.status === "running" ? { ...st, status: "error" as const } : st)),
        },
      }
      : m)),
  };
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

/** Ids deleted here, kept so a merge from another window cannot bring them back. */
const removedIds = (): Record<string, number> => {
  const graves = readJson<Record<string, number>>(REMOVED_KEY, {});
  return graves && typeof graves === "object" ? graves : {};
};

function remember(id: string) {
  try {
    const graves = { ...removedIds(), [id]: Date.now() };
    const kept = Object.entries(graves).sort((a, b) => b[1] - a[1]).slice(0, MAX_REMOVED);
    localStorage.setItem(REMOVED_KEY, JSON.stringify(Object.fromEntries(kept)));
  } catch {
    /* storage unavailable */
  }
}

function parseSessions(raw: string | null): Session[] {
  if (!raw) return [];
  let list: unknown;
  try {
    list = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(list)) return [];
  const gone = removedIds();
  return list.filter(isSession).filter((s) => !(s.id in gone)).map(settle).sort(byRecency).slice(0, MAX_SESSIONS);
}

export interface SessionState {
  sessions: Session[];
  activeId: string | null;
}

function loadState(): SessionState {
  let sessions: Session[] = [];
  let stored: string | null = null;
  try {
    sessions = parseSessions(localStorage.getItem(SESSIONS_KEY));
    stored = localStorage.getItem(ACTIVE_KEY);
  } catch {
    /* storage unavailable — this run starts empty */
  }
  return { sessions, activeId: stored && sessions.some((s) => s.id === stored) ? stored : null };
}

// --- writing ------------------------------------------------------------------

const isQuotaError = (e: unknown) =>
  e instanceof DOMException && (e.name === "QuotaExceededError" || e.name === "NS_ERROR_DOM_QUOTA_REACHED" || e.code === 22);

const stripSteps = (s: Session): Session => ({
  ...s,
  messages: s.messages.map((m) => (m.run?.steps ? { ...m, run: { ...m.run, steps: undefined } } : m)),
});

/** Attached images are stored by the backend; their bytes would eat the quota on their own. */
const withoutImageData = (key: string, value: unknown) => (key === "dataUrl" ? undefined : value);

/**
 * The list as it should be written at a given pressure level: traces of older sessions
 * first, then every trace, then the oldest sessions. `null` when there is nothing left
 * to give up.
 */
function shed(list: Session[], level: number): Session[] | null {
  if (level <= 0) return list;
  const trimmed = level === 1 ? list.map((s, i) => (i === 0 ? s : stripSteps(s))) : list.map(stripSteps);
  const drop = Math.max(0, level - 2);
  return drop < trimmed.length ? trimmed.slice(0, trimmed.length - drop) : null;
}

/** Pressure level the last write fit into, so a tight storage isn't probed from scratch every time. */
let pressure = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
let queued: Session[] | null = null;
let warned = false;

function write(list: Session[]) {
  const capped = list.slice(0, MAX_SESSIONS);
  for (let level = Math.max(0, pressure - 1); ; level++) {
    const payload = shed(capped, level);
    if (!payload) {
      if (!warned) {
        warned = true;
        console.warn("[nocoast] sessions do not fit in localStorage; older ones are not being kept");
      }
      return;
    }
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(payload, withoutImageData));
      pressure = level;
      return;
    } catch (e) {
      if (!isQuotaError(e)) return; // storage disabled entirely (private mode, no-storage webview)
    }
  }
}

export function saveSessions(list: Session[]) {
  queued = list;
  if (timer) return;
  timer = setTimeout(flushSessions, WRITE_DELAY);
}

/** Write a pending change now (called before the window goes away). */
export function flushSessions() {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  if (!queued) return;
  const list = queued;
  queued = null;
  write(list);
}

function writeActive(id: string | null) {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, id);
    else localStorage.removeItem(ACTIVE_KEY);
  } catch {
    /* storage unavailable */
  }
}

/** Forget everything (the smoke tests' `?tab=reset`). */
export function clearSessions() {
  if (timer) clearTimeout(timer);
  timer = null;
  queued = null;
  pressure = 0;
  try {
    localStorage.removeItem(SESSIONS_KEY);
    localStorage.removeItem(ACTIVE_KEY);
    localStorage.removeItem(REMOVED_KEY);
  } catch {
    /* storage unavailable */
  }
}

// --- merging another window's list ---------------------------------------------

/** Newest copy of each session wins; `null` when the merge changes nothing here. */
export function mergeSessions(mine: Session[], theirs: Session[]): Session[] | null {
  const gone = removedIds();
  const byId = new Map(mine.map((s) => [s.id, s]));
  for (const t of theirs) {
    if (t.id in gone) continue;
    const held = byId.get(t.id);
    if (!held || stamp(t) > stamp(held)) byId.set(t.id, settle(t));
  }
  const merged = [...byId.values()].sort(byRecency).slice(0, MAX_SESSIONS);
  const same = merged.length === mine.length && merged.every((s, i) => s === mine[i]);
  return same ? null : merged;
}

// --- the hook -------------------------------------------------------------------

export function useSessions() {
  const [state, setState] = useState<SessionState>(loadState);
  const { sessions, activeId } = state;

  useEffect(() => saveSessions(sessions), [sessions]);
  useEffect(() => writeActive(activeId), [activeId]);

  useEffect(() => {
    const onHidden = () => document.visibilityState === "hidden" && flushSessions();
    // Another window wrote the list: take the newest copy of each session rather than
    // letting whoever writes last overwrite the other's work.
    const onStorage = (e: StorageEvent) => {
      if (e.key !== SESSIONS_KEY || !e.newValue) return;
      const theirs = parseSessions(e.newValue);
      setState((s) => {
        const merged = mergeSessions(s.sessions, theirs);
        return merged ? { ...s, sessions: merged } : s;
      });
    };
    window.addEventListener("pagehide", flushSessions);
    window.addEventListener("beforeunload", flushSessions);
    document.addEventListener("visibilitychange", onHidden);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("pagehide", flushSessions);
      window.removeEventListener("beforeunload", flushSessions);
      document.removeEventListener("visibilitychange", onHidden);
      window.removeEventListener("storage", onStorage);
      flushSessions();
    };
  }, []);

  const setActiveId = useCallback((id: string | null) => setState((s) => ({ ...s, activeId: id })), []);

  const create = useCallback((title: string) => {
    const now = Date.now();
    const s: Session = { id: uid(), title, createdAt: now, updatedAt: now, messages: [] };
    setState((prev) => ({ sessions: [s, ...prev.sessions].slice(0, MAX_SESSIONS), activeId: s.id }));
    return s.id;
  }, []);

  const update = useCallback((id: string, fn: (s: Session) => Session) => {
    setState((prev) => ({
      ...prev,
      sessions: prev.sessions.map((s) => {
        if (s.id !== id) return s;
        const next = fn(s);
        return next === s ? s : { ...next, updatedAt: Date.now() };
      }),
    }));
  }, []);

  const remove = useCallback((id: string) => {
    remember(id);
    setState((prev) => ({
      sessions: prev.sessions.filter((s) => s.id !== id),
      activeId: prev.activeId === id ? null : prev.activeId,
    }));
  }, []);

  const clear = useCallback(() => {
    clearSessions();
    setState({ sessions: [], activeId: null });
  }, []);

  const active = sessions.find((s) => s.id === activeId) ?? null;
  return { sessions, active, activeId, setActiveId, create, update, remove, clear };
}

/** Helpers for editing a message inside a session. */
export const addMessage = (m: Message) => (s: Session): Session => ({ ...s, messages: [...s.messages, m] });
export const patchRun = (msgId: string, patch: Partial<Run>) => (s: Session): Session => ({
  ...s,
  messages: s.messages.map((m) => (m.id === msgId ? { ...m, run: { ...(m.run ?? { stage: "planning" }), ...patch } } : m)),
});

/** Point a user message's attachments at the backend's copies, so they survive a reload. */
export const linkImages = (msgId: string, urls: string[]) => (s: Session): Session => ({
  ...s,
  messages: s.messages.map((m) => (m.id === msgId && m.images
    ? { ...m, images: m.images.map((img, i) => (urls[i] ? { ...img, url: urls[i] } : img)) }
    : m)),
});

/** Insert or update a trace step on a run (steps arrive as running, then done/error). */
export const upsertStep = (msgId: string, step: TraceStep) => (s: Session): Session => ({
  ...s,
  messages: s.messages.map((m) => {
    if (m.id !== msgId || !m.run) return m;
    const steps = m.run.steps ?? [];
    const i = steps.findIndex((x) => x.id === step.id);
    const next = i < 0 ? [...steps, step] : steps.map((x, j) => (j === i ? { ...x, ...step } : x));
    return { ...m, run: { ...m.run, steps: next } };
  }),
});
