import { BedDouble, RotateCcw } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { LegacyViewer, Picked, PropertySet, ViewName } from "../viewer/LegacyViewer";

// --- floating view panel (top-right) ----------------------------------------

export function ViewControls({ viewer, roomsVisible, onRooms }: { viewer: LegacyViewer; roomsVisible: boolean; onRooms: () => void }) {
  const views: [ViewName, string][] = [
    ["top", "Top"], ["bottom", "Bottom"], ["front", "Front"], ["back", "Back"], ["left", "Left"], ["right", "Right"],
  ];
  return (
    <div className="float view-controls">
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
      </div>
    </div>
  );
}

// --- model / selection card (bottom-left) -----------------------------------

interface InfoProps {
  fileName: string;
  schema: string;
  picked: Picked | null;
  properties: PropertySet[];
}

export function InfoCard({ fileName, schema, picked, properties }: InfoProps) {
  return (
    <div className="float info-card">
      <div className="info-title" title={fileName}>{fileName}</div>
      <div className="muted small">{schema || "IFC"} · m</div>
      <div className="info-sep" />
      {picked ? (
        <>
          <div className="info-sub" title={picked.name || picked.type}>{picked.name || picked.type}</div>
          <dl className="kv">
            <dt>Class</dt><dd>{picked.type}</dd>
            {picked.tag && <><dt>Tag</dt><dd>{picked.tag}</dd></>}
          </dl>
          <div className="guid">{picked.globalId}</div>
          {properties.slice(1).map((ps) => (
            <div key={ps.name} className="info-pset">
              <div className="info-pset-title">{ps.name}</div>
              <dl className="kv">
                {ps.props.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}
              </dl>
            </div>
          ))}
        </>
      ) : (
        <div className="muted small">Click an element to inspect it.</div>
      )}
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
