import { BedDouble, Play, RotateCcw, Square, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { Facts } from "../state/design";
import { PANEL_RANGE } from "../state/layout";
import type { LegacyViewer, Picked, PropertySet, ViewName } from "../viewer/LegacyViewer";
import type { SectionView } from "../viewer/section";
import { Resizer } from "./Resizer";

// --- floating view panel (top-right) ----------------------------------------

interface ViewProps {
  viewer: LegacyViewer;
  roomsVisible: boolean;
  onRooms: () => void;
  /** Set when the model on screen is a stored version that can be rebuilt step by step. */
  replay: { playing: boolean; onToggle: () => void } | null;
  width: number;
  onResize: (width: number) => void;
  onResetSize: () => void;
}

export function ViewControls({ viewer, roomsVisible, onRooms, replay, width, onResize, onResetSize }: ViewProps) {
  const views: [ViewName, string][] = [
    ["top", "Top"], ["bottom", "Bottom"], ["front", "Front"], ["back", "Back"], ["left", "Left"], ["right", "Right"],
  ];
  return (
    <div className="float view-controls" style={{ width }}>
      <Resizer className="resizer-viewtools" label="View palette width" onReset={onResetSize}
        width={{ value: width, dir: -1, ...PANEL_RANGE.viewTools, onChange: onResize }} />
      <div className="view-grid">
        {views.map(([v, label]) => (
          <button key={v} onClick={() => viewer.view(v)}>{label}</button>
        ))}
        <button className="span2" onClick={() => viewer.view("isometric")}>Isometric</button>
      </div>
      <div className="view-sep" />
      <div className="view-icons">
        <button title="Reset view" onClick={() => viewer.reset()}><RotateCcw size={17} /></button>
        <button title={roomsVisible ? "Hide room volumes" : "Show room volumes"} className={roomsVisible ? "on" : ""} onClick={onRooms}>
          <BedDouble size={17} />
        </button>
        {replay && (
          <button className={`replay ${replay.playing ? "on" : ""}`}
            title={replay.playing ? "Stop the build replay" : "Replay the build, one element at a time, framed on the whole building"}
            onClick={replay.onToggle}>
            {replay.playing ? <Square size={13} /> : <Play size={14} />}
            {replay.playing ? "Stop" : "Replay"}
          </button>
        )}
      </div>
    </div>
  );
}

// --- what the viewer shows (top-left): "preview 3 · 39 elements" or "v4 · final · 120 elements" -----------

export function Showing({ label, preview }: { label: string; preview: boolean }) {
  return <div className={`showing ${preview ? "preview" : ""}`}>{label}</div>;
}

// --- cross-section slider + follow build (bottom, between the info card and the gizmo) -------------------

export function SectionBar({ section, onValue, onFollow }: { section: SectionView; onValue: (tenths: number) => void; onFollow: (on: boolean) => void }) {
  return (
    <div className="float section-bar" title="Cross-section: hide everything above a height">
      <span className="muted">section</span>
      <input type="range" min={section.min} max={section.max} step={1} value={section.value} list="section-snaps" disabled={!section.enabled}
        onChange={(e) => onValue(Number(e.target.value))} />
      <datalist id="section-snaps">
        {section.snaps.map((s) => <option key={`${s.z}-${s.label}`} value={Math.round(s.z * 10)} label={s.label} />)}
      </datalist>
      <span className="section-label">{section.label}</span>
      <label title="While a request runs, cut the view just under the ceiling of the storey being worked on">
        <input type="checkbox" checked={section.follow} onChange={(e) => onFollow(e.target.checked)} /> follow build
      </label>
    </div>
  );
}

// --- model / selection card (bottom-left) -----------------------------------
// The inspector: what the selected element is in design terms first, then its IFC attributes and property sets.

interface InfoProps {
  fileName: string;
  schema: string;
  picked: Picked | null;
  facts: Facts | null;
  properties: PropertySet[];
  onClear: () => void;
  width: number;
  height: number;
  onResize: (size: { width?: number; height?: number }) => void;
  onResetSize: () => void;
}

export function InfoCard({ fileName, schema, picked, facts, properties, onClear, width, height, onResize, onResetSize }: InfoProps) {
  return (
    <div className="float info-card" style={{ width }}>
      {/* Anchored bottom-left, so the card grows to the right and upwards from its top-right corner.
          The height is how far it may grow before the property sets scroll. */}
      <Resizer className="resizer-inspector" label="Inspector width and height" onReset={onResetSize}
        width={{ value: width, dir: 1, ...PANEL_RANGE.inspectorW, onChange: (w) => onResize({ width: w }) }}
        height={{ value: height, dir: -1, ...PANEL_RANGE.inspectorH, onChange: (h) => onResize({ height: h }) }} />
      <div className="info-scroll" style={{ maxHeight: height }}>
        <div className="info-title" title={fileName}>{fileName}</div>
        <div className="muted small">{schema || "IFC"} · m</div>
        <div className="info-sep" />
        {picked ? (
          <>
            <div className="info-head">
              <div className="info-sub" title={facts?.title ?? picked.name ?? picked.type}>{facts?.title ?? `${picked.type.replace(/^Ifc/, "")} ${picked.tag || picked.name}`}</div>
              <button className="icon-btn tiny" title="Clear selection" onClick={onClear}><X size={14} /></button>
            </div>
            {facts && facts.rows.length > 0 && (
              <dl className="kv facts">
                {facts.rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}
              </dl>
            )}
            <details className="info-ifc">
              <summary>IFC properties</summary>
              {properties.map((ps) => (
                <div key={ps.name} className="info-pset">
                  <div className="info-pset-title">{ps.name}</div>
                  <dl className="kv facts">
                    {ps.props.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}
                  </dl>
                </div>
              ))}
              {!properties.length && <div className="muted small">No property sets.</div>}
            </details>
            <div className="guid">{picked.globalId}</div>
          </>
        ) : (
          <div className="muted small">Click an element to inspect it and to make the next prompt about it. Clicking a floor picks the room.</div>
        )}
      </div>
    </div>
  );
}

// --- axis gizmo (bottom-right) ----------------------------------------------

// IFC axes (Z up) expressed in three.js (Y up) coordinates.
const AXES: { label: string; color: string; dir: THREE.Vector3; pos: ViewName; neg: ViewName }[] = [
  { label: "X", color: "#e5484d", dir: new THREE.Vector3(1, 0, 0), pos: "right", neg: "left" },
  { label: "Y", color: "#46a758", dir: new THREE.Vector3(0, 0, -1), pos: "back", neg: "front" },
  { label: "Z", color: "#3e63dd", dir: new THREE.Vector3(0, 1, 0), pos: "top", neg: "bottom" },
];

export function AxisGizmo({ viewer }: { viewer: LegacyViewer }) {
  const [pts, setPts] = useState<{ key: string; x: number; y: number; z: number; color: string; label?: string; view: ViewName; line: boolean }[]>([]);
  const last = useRef("");

  useEffect(() => {
    let frame = 0;
    const q = new THREE.Quaternion();
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const cam = viewer.camera;
      if (!cam) return;
      q.copy(cam.quaternion).invert();
      const next = AXES.flatMap((a) => {
        const v = a.dir.clone().applyQuaternion(q);
        return [
          { key: a.label, x: 50 + v.x * 32, y: 50 - v.y * 32, z: v.z, color: a.color, label: a.label, view: a.pos, line: true },
          { key: `-${a.label}`, x: 50 - v.x * 32, y: 50 + v.y * 32, z: -v.z, color: "#c4c4bf", view: a.neg, line: false },
        ];
      }).sort((a, b) => a.z - b.z); // back to front
      const sig = next.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join();
      if (sig !== last.current) {
        last.current = sig;
        setPts(next);
      }
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [viewer]);

  return (
    <svg className="gizmo" viewBox="0 0 100 100" width={100} height={100}>
      {pts.map((p) => (
        <g key={p.key} className="gizmo-axis" onClick={() => viewer.view(p.view)}>
          {p.line && <line x1={50} y1={50} x2={p.x} y2={p.y} stroke={p.color} strokeWidth={3} strokeLinecap="round" />}
          <circle cx={p.x} cy={p.y} r={p.line ? 9 : 7} fill={p.color} />
          {p.label && <text x={p.x} y={p.y + 3.5} textAnchor="middle" fontSize={10} fontWeight={700} fill="#fff">{p.label}</text>}
        </g>
      ))}
    </svg>
  );
}
