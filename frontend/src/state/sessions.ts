// Sessions = one conversation + the model it produced. Persisted in localStorage
// (per-machine convenience only; generated IFCs live on the backend).
import { useCallback, useEffect, useState } from "react";
import type { BuildResult, PlanResult, Version } from "../api/client";

export type Stage = "planning" | "building" | "loading" | "done" | "error";

/** One line of the live reasoning trace (from the backend stream, or the viewer's load steps). */
export interface TraceStep {
  id: string;
  parent: string | null;
  phase: "plan" | "validate" | "build" | "load";
  title: string;
  detail: string | null;
  status: "running" | "done" | "error";
  ms?: number;
  layer?: boolean;
  error?: string;
}

export interface Run {
  stage: Stage;
  error?: string;
  /** the project version this turn produced */
  version?: Version;
  /** older sessions (before versioned projects) */
  plan?: PlanResult;
  build?: BuildResult;
  steps?: TraceStep[];
  startedAt?: number;
  endedAt?: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  run?: Run;
}

export interface ModelRef {
  name: string;
  /** backend path (/models/x.ifc) or bundled URL; absent for local files opened this run */
  url?: string;
}

export interface Session {
  id: string;
  /** backend project behind this conversation (absent for files opened from disk) */
  projectId?: string;
  title: string;
  createdAt: number;
  messages: Message[];
  model?: ModelRef;
}

const KEY = "gbim.sessions.v1";

export const uid = () => Math.random().toString(36).slice(2, 10);

function load(): Session[] {
  try {
    const raw = localStorage.getItem(KEY);
    const list = raw ? (JSON.parse(raw) as Session[]) : [];
    // A run interrupted by closing the app can't resume.
    for (const s of list)
      for (const m of s.messages)
        if (m.run && m.run.stage !== "done" && m.run.stage !== "error")
          m.run = {
            ...m.run, stage: "error", error: "Interrupted",
            steps: m.run.steps?.map((st) => (st.status === "running" ? { ...st, status: "error" as const } : st)),
          };
    return list;
  } catch {
    return [];
  }
}

export function useSessions() {
  const [sessions, setSessions] = useState<Session[]>(load);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(sessions.slice(0, 50)));
    } catch {
      /* storage unavailable — sessions just won't persist */
    }
  }, [sessions]);

  const create = useCallback((title: string) => {
    const s: Session = { id: uid(), title, createdAt: Date.now(), messages: [] };
    setSessions((list) => [s, ...list]);
    setActiveId(s.id);
    return s.id;
  }, []);

  const update = useCallback((id: string, fn: (s: Session) => Session) => {
    setSessions((list) => list.map((s) => (s.id === id ? fn(s) : s)));
  }, []);

  const remove = useCallback((id: string) => {
    setSessions((list) => list.filter((s) => s.id !== id));
    setActiveId((a) => (a === id ? null : a));
  }, []);

  const active = sessions.find((s) => s.id === activeId) ?? null;
  return { sessions, active, activeId, setActiveId, create, update, remove };
}

/** Helpers for editing a message inside a session. */
export const addMessage = (m: Message) => (s: Session): Session => ({ ...s, messages: [...s.messages, m] });
export const patchRun = (msgId: string, patch: Partial<Run>) => (s: Session): Session => ({
  ...s,
  messages: s.messages.map((m) => (m.id === msgId ? { ...m, run: { ...(m.run ?? { stage: "planning" }), ...patch } } : m)),
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
