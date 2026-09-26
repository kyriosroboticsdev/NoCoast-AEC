// Turns the pipeline's flat stage events (program | edit | apply | solve | compile | done)
// into reasoning-trace steps. A stage that repeats is a repair attempt after validation
// failed; those nest under the stage with the errors being fixed as their detail.
import type { StageEvent } from "../api/client";
import { uid, type TraceStep } from "./sessions";

const STAGES: Record<string, { phase: TraceStep["phase"]; title: string }> = {
  program: { phase: "plan", title: "Designing the building program" },
  edit: { phase: "plan", title: "Working out the edit" },
  apply: { phase: "validate", title: "Applying the operations" },
  solve: { phase: "build", title: "Solving the layout" },
  compile: { phase: "build", title: "Compiling IFC" },
};

interface Open {
  step: TraceStep;
  stage: string;
  t0: number;
}

export function stageTracer(push: (step: TraceStep) => void) {
  let top: Open | null = null;
  let child: Open | null = null;

  const open = (step: TraceStep, stage: string): Open => {
    push(step);
    return { step, stage, t0: performance.now() };
  };
  const finish = (o: Open | null, status: "done" | "error", error?: string) => {
    if (o) push({ ...o.step, status, error, ms: Math.round(performance.now() - o.t0) });
  };
  const closeAll = () => {
    finish(child, "done");
    finish(top, "done");
    top = child = null;
  };

  return {
    event(e: StageEvent) {
      if (e.stage === "done") return closeAll();
      if (e.stage === "error") return; // the stream throws right after; fail() reports it once
      const errors = (e.data?.errors as string[] | undefined) ?? [];
      if (top && top.stage === e.stage) {
        finish(child, "done");
        const fixing = errors.length ? `fixing: ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}` : null;
        const title = e.message.charAt(0).toUpperCase() + e.message.slice(1);
        child = open({ id: uid(), parent: top.step.id, phase: top.step.phase, title, detail: fixing, status: "running" }, e.stage);
        return;
      }
      closeAll();
      const info = STAGES[e.stage] ?? { phase: "build" as const, title: e.message };
      const detail = e.message.toLowerCase() === info.title.toLowerCase() ? null : e.message;
      top = open({ id: uid(), parent: null, phase: info.phase, title: info.title, detail, status: "running" }, e.stage);
    },
    /** Mark the step that was running as failed (the error shows on the innermost one). */
    fail(message: string) {
      if (child) {
        finish(child, "error", message);
        finish(top, "error");
      } else finish(top, "error", message);
      top = child = null;
    },
  };
}
