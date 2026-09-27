import {
  BookOpen, Box, Check, ChevronDown, ChevronRight, ClipboardList, DoorOpen, FileDown, Frame, Hammer, Layers,
  LayoutGrid, LoaderCircle, Ruler, ShieldCheck, Sofa, Sparkles, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { backendUrl } from "../api/client";
import type { Run, TracePhase, TraceStep } from "../state/sessions";
import { describeUsage, formatTokens, runUsage } from "../state/usage";

const PHASE_ICON: Partial<Record<TracePhase, typeof Sparkles>> = {
  brief: ClipboardList,
  research: BookOpen,
  massing: Ruler,
  plan: LayoutGrid,
  circulation: DoorOpen,
  envelope: Frame,
  structure: Hammer,
  fitout: Sofa,
  review: ShieldCheck,
  output: FileDown,
  // older sessions, persisted before the trace was grouped by phase
  validate: ShieldCheck,
  build: Hammer,
  load: Box,
};

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
  const usage = runUsage(run);
  // What the model is writing this instant beats the last finished step as the "now" line.
  const nowLine = running
    ? run.drafting ?? (current ? `${current.title}${current.detail ? ` — ${current.detail}` : ""}` : null)
    : null;

  // Layer stack: one block per storey plate, wherever it sits in the trace.
  const layerSteps = steps.filter((s) => s.layer);
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
          {usage && (
            <span className="token-count" title={describeUsage({
              input: usage.input_tokens, output: usage.output_tokens, cached: usage.cached_tokens ?? 0,
              calls: usage.calls ?? 0, estimated: !!usage.estimated,
            })}>
              {usage.estimated ? "~" : ""}{formatTokens(usage.total_tokens)} tokens
            </span>
          )}
          {nowLine && <small className="reasoning-now">{nowLine}</small>}
        </span>
        {totalLayers > 0 && (
          <span className="layer-stack" title="Storeys laid out so far">
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
          {top.map((s) => <StepRow key={s.id} step={s} kids={children} depth={0} layers={layerSteps} />)}
          {running && !steps.length && <li className="trace-row running"><span className="trace-dot"><LoaderCircle size={14} className="spin" /></span><span className="trace-main">Connecting…</span></li>}
        </ol>
      )}
    </div>
  );
}

function StepRow({ step, kids, depth, layers }: {
  step: TraceStep; kids: Map<string | null, TraceStep[]>; depth: number; layers: TraceStep[];
}) {
  const children = kids.get(step.id) ?? [];
  const [open, setOpen] = useState(true);
  const Icon = step.layer ? Layers : PHASE_ICON[step.phase] ?? Sparkles;
  const icon =
    step.status === "running" ? <LoaderCircle size={14} className="spin" /> :
    step.status === "error" ? <X size={14} /> :
    depth === 0 || step.layer ? <Icon size={14} /> : <Check size={12} />;
  const layerIndex = step.layer ? layers.findIndex((l) => l.id === step.id) : -1;

  return (
    <li className={`trace-row ${step.status} ${depth ? "child" : ""} ${step.layer ? "layer" : ""}`}>
      <span className="trace-dot">{icon}</span>
      <div className="trace-main">
        <div className="trace-line" onClick={() => children.length && setOpen(!open)} style={{ cursor: children.length ? "pointer" : undefined }}>
          <span className="trace-title">{step.title}</span>
          {layerIndex >= 0 && <span className="layer-badge">storey {layerIndex + 1}/{layers.length}</span>}
          {step.metric && <span className="trace-metric">{step.metric}</span>}
          <span className="grow" />
          {step.ms !== undefined && step.ms > 0 && <span className="trace-ms">{fmtMs(step.ms)}</span>}
        </div>
        {step.why && <div className="trace-why">{step.why}</div>}
        {(step.error || step.detail) && <div className={`trace-detail ${step.error ? "err" : ""}`}>{step.error ?? step.detail}</div>}
        {step.image && (
          <a className="trace-shot" href={backendUrl(step.image)} target="_blank" rel="noreferrer">
            <img src={backendUrl(step.image)} alt={step.title} loading="lazy" />
          </a>
        )}
        {open && children.length > 0 && (
          <ol className="trace nested">
            {children.map((c) => <StepRow key={c.id} step={c} kids={kids} depth={depth + 1} layers={layers} />)}
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
