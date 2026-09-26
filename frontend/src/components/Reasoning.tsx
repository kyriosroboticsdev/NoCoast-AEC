import { Box, Check, ChevronDown, ChevronRight, Hammer, Layers, LoaderCircle, ShieldCheck, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Run, TraceStep } from "../state/sessions";

const PHASE_ICON = { plan: Sparkles, validate: ShieldCheck, build: Hammer, load: Box } as const;

/** Live, nested trace of what the agent is doing — streamed from the backend step by step. */
export function Reasoning({ run }: { run: Run }) {
  const steps = run.steps ?? [];
  const running = run.stage !== "done" && run.stage !== "error";
  const [open, setOpen] = useState(running);
  const [userToggled, setUserToggled] = useState(false);
  const now = useNow(running);

  // Open while working; fold away when finished unless the user chose otherwise.
  useEffect(() => {
    if (!userToggled) setOpen(running);
  }, [running, userToggled]);

  const children = useMemo(() => {
    const map = new Map<string | null, TraceStep[]>();
    for (const s of steps) map.set(s.parent, [...(map.get(s.parent) ?? []), s]);
    return map;
  }, [steps]);
  const top = children.get(null) ?? [];

  const elapsed = ((run.endedAt ?? now) - (run.startedAt ?? now)) / 1000;
  const current = [...steps].reverse().find((s) => s.status === "running");
  const failed = run.stage === "error";

  // Layer stack: one block per storey step, when the trace reports them.
  const layerSteps = steps.filter((s) => s.layer && !s.parent);
  const totalLayers = layerSteps.length;

  if (!steps.length && !running) return null;

  return (
    <div className={`reasoning ${failed ? "failed" : ""}`}>
      <button className="reasoning-head" onClick={() => { setOpen(!open); setUserToggled(true); }}>
        <span className="reasoning-icon">
          {running ? <LoaderCircle size={16} className="spin" /> : failed ? <X size={16} /> : <Check size={16} />}
        </span>
        <span className="reasoning-title">
          <b>{running ? "Working" : failed ? "Stopped" : "Reasoned"}</b>
          <span className="muted"> {running ? "·" : failed ? "after" : "for"} {fmtSeconds(elapsed)}{!running && ` · ${steps.length} steps`}</span>
          {running && current && <small className="reasoning-now">{current.title}{current.detail ? ` — ${current.detail}` : ""}</small>}
        </span>
        {totalLayers > 0 && (
          <span className="layer-stack" title="Storeys built so far">
            {Array.from({ length: totalLayers }, (_, i) => {
              const s = layerSteps[i];
              return <i key={i} className={s ? s.status : ""} />;
            })}
          </span>
        )}
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>

      {open && (
        <ol className="trace">
          {top.map((s) => <StepRow key={s.id} step={s} kids={children} depth={0} layerIndex={layerSteps.indexOf(s)} layerTotal={totalLayers} />)}
          {running && !steps.length && <li className="trace-row running"><span className="trace-dot"><LoaderCircle size={14} className="spin" /></span><span className="trace-main">Connecting…</span></li>}
        </ol>
      )}
    </div>
  );
}

function StepRow({ step, kids, depth, layerIndex, layerTotal }: {
  step: TraceStep; kids: Map<string | null, TraceStep[]>; depth: number; layerIndex: number; layerTotal: number;
}) {
  const children = kids.get(step.id) ?? [];
  const [open, setOpen] = useState(true);
  const Icon = step.layer ? Layers : PHASE_ICON[step.phase] ?? Sparkles;
  const icon =
    step.status === "running" ? <LoaderCircle size={14} className="spin" /> :
    step.status === "error" ? <X size={14} /> :
    depth === 0 ? <Icon size={14} /> : <Check size={12} />;

  return (
    <li className={`trace-row ${step.status} ${depth ? "child" : ""} ${step.layer ? "layer" : ""}`}>
      <span className="trace-dot">{icon}</span>
      <div className="trace-main">
        <div className="trace-line" onClick={() => children.length && setOpen(!open)} style={{ cursor: children.length ? "pointer" : undefined }}>
          <span className="trace-title">{step.title}</span>
          {step.layer && layerIndex >= 0 && <span className="layer-badge">layer {layerIndex + 1}/{layerTotal}</span>}
          <span className="grow" />
          {step.ms !== undefined && step.ms > 0 && <span className="trace-ms">{fmtMs(step.ms)}</span>}
        </div>
        {(step.error || step.detail) && <div className={`trace-detail ${step.error ? "err" : ""}`}>{step.error ?? step.detail}</div>}
        {open && children.length > 0 && (
          <ol className="trace nested">
            {children.map((c) => <StepRow key={c.id} step={c} kids={kids} depth={depth + 1} layerIndex={-1} layerTotal={layerTotal} />)}
          </ol>
        )}
      </div>
    </li>
  );
}

function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

const fmtSeconds = (s: number) => `${Math.max(0, s).toFixed(1)}s`;
const fmtMs = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
