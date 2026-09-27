import { Download, Pause, Play, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { LegacyViewer } from "../viewer/LegacyViewer";
import { BuildReplay, PHASE_COLORS, type ReplayState } from "../viewer/replay";

const SPEEDS = [0.5, 1, 2, 4, 8];

/** Replaces the section bar while a build replay runs: slices the model, then plays its layers back. */
export function ReplayBar({ viewer, fileName, onClose }: { viewer: LegacyViewer; fileName: string; onClose: () => void }) {
  const replay = useRef<BuildReplay | null>(null);
  const [state, setState] = useState<ReplayState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const r = new BuildReplay(viewer, setState);
    replay.current = r;
    r.slice().catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => r.dispose();
  }, [viewer]);

  // Space toggles play/pause while the replay is open (unless typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.code === "Space" && !/INPUT|TEXTAREA|SELECT/.test(t.tagName) && !t.isContentEditable) {
        e.preventDefault();
        replay.current?.toggle();
      }
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const exportGcode = () => {
    const text = replay.current?.gcode(fileName);
    if (!text) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${fileName.replace(/\.ifc$/i, "")}.gcode` });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  if (error) {
    return (
      <div className="float replay-bar">
        <span className="replay-title">Replay</span>
        <span className="replay-label">Couldn't slice this model: {error}</span>
        <button className="icon-btn" title="Close replay" onClick={onClose}><X size={16} /></button>
      </div>
    );
  }

  if (!state?.ready) {
    return (
      <div className="float replay-bar">
        <span className="replay-title">Replay</span>
        <span className="replay-label">Slicing into G-code layers… {Math.round((state?.progress ?? 0) * 100)}%</span>
        <div className="replay-progress"><span style={{ transform: `scaleX(${state?.progress ?? 0})` }} /></div>
        <button className="icon-btn" title="Close replay" onClick={onClose}><X size={16} /></button>
      </div>
    );
  }

  const r = replay.current!;
  const phases = state.info!.phases;
  return (
    <div className="float replay-bar">
      <button className="icon-btn replay-play" title={state.playing ? "Pause (Space)" : "Play (Space)"} onClick={() => r.toggle()}>
        {state.playing ? <Pause size={16} /> : <Play size={16} />}
      </button>
      <button className="icon-btn" title="Restart" onClick={() => { r.seek(0); r.play(); }}><RotateCcw size={15} /></button>
      <input className="replay-scrub" type="range" min={0} max={state.total} step={0.01} value={state.step}
        onChange={(e) => { r.pause(); r.seek(Number(e.target.value)); }} aria-label="Replay position" />
      <span className="replay-label" title={`${state.info!.segments.toLocaleString()} toolpath segments`}>{state.label}</span>
      <div className="seg-toggle" role="group" aria-label="Build order">
        <button className={state.order === "height" ? "on" : ""} title="Layer by layer across the whole model, like a printer"
          onClick={() => r.setOrder("height")}>By height</button>
        <button className={state.order === "phase" ? "on" : ""} title="Slabs, then walls and columns, then roofs … (the backend's construction order)"
          onClick={() => r.setOrder("phase")}>By phase</button>
      </div>
      <label title="Hide the model and show only the G-code toolpaths">
        <input type="checkbox" checked={state.toolpathsOnly} onChange={(e) => r.setToolpathsOnly(e.target.checked)} /> toolpaths
      </label>
      <select value={state.speed} onChange={(e) => r.setSpeed(Number(e.target.value))} title="Playback speed" aria-label="Playback speed">
        {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
      </select>
      <button className="icon-btn" title="Export these layers as preview G-code" onClick={exportGcode}><Download size={15} /></button>
      <button className="icon-btn" title="Close replay (Esc)" onClick={onClose}><X size={16} /></button>
      <div className="replay-legend">
        {phases.map((p) => <span key={p}><i style={{ background: PHASE_COLORS[p] }} />{p}</span>)}
      </div>
    </div>
  );
}
