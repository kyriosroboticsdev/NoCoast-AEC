import { Copy, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { ElementRow, LevelNode, PropertyGroup } from "../viewer/BimViewer";
import { LevelTree } from "./LevelTree";

// --- Elements tab: full hierarchy + properties of the selection -------------

interface ElementsProps {
  levels: LevelNode[];
  selectedId: number | null;
  properties: PropertyGroup[];
  onSelect: (localId: number) => void;
  onVisible: (ids: number[], visible: boolean) => void;
}

export function ElementsView(p: ElementsProps) {
  return (
    <div className="tab-view split">
      <section className="pane">
        <h3 className="pane-title">Levels</h3>
        <div className="pane-scroll">
          <LevelTree levels={p.levels} selectedId={p.selectedId} onSelect={p.onSelect} onVisible={p.onVisible} />
        </div>
      </section>
      <section className="pane">
        <h3 className="pane-title">Properties</h3>
        <div className="pane-scroll">
          {!p.properties.length && <p className="muted small pad">Select an element to see its attributes and property sets.</p>}
          {p.properties.map((g) => (
            <div key={g.title} className="prop-group">
              <div className="prop-title">{g.title}</div>
              <dl className="kv wide">
                {g.rows.map(([k, v], i) => (
                  <div key={k + i} className="kv-row"><dt>{k}</dt><dd>{v}</dd></div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

// --- Data tab: every element as a filterable table --------------------------

interface DataProps {
  rows: ElementRow[] | null;
  selectedId: number | null;
  onPick: (localId: number) => void;
}

export function DataView({ rows, selectedId, onPick }: DataProps) {
  const [q, setQ] = useState("");
  const [cls, setCls] = useState("");
  const classes = useMemo(() => [...new Set((rows ?? []).map((r) => r.ifcClass))].sort(), [rows]);
  const shown = useMemo(() => {
    const needle = q.toLowerCase();
    return (rows ?? []).filter(
      (r) => (!cls || r.ifcClass === cls) &&
        (!needle || [r.name, r.tag, r.level, r.guid, r.ifcClass].some((v) => v.toLowerCase().includes(needle))),
    );
  }, [rows, q, cls]);

  const copy = () => {
    const head = "Level\tClass\tName\tTag\tGlobalId";
    const body = shown.map((r) => [r.level, r.ifcClass, r.name, r.tag, r.guid].join("\t")).join("\n");
    navigator.clipboard?.writeText(`${head}\n${body}`);
  };

  if (!rows) return <div className="tab-view center muted">Reading elements…</div>;
  return (
    <div className="tab-view data">
      <div className="data-bar">
        <select value={cls} onChange={(e) => setCls(e.target.value)}>
          <option value="">All classes</option>
          {classes.map((c) => <option key={c}>{c}</option>)}
        </select>
        <label className="search">
          <Search size={15} />
          <input placeholder="Search name, tag, level, GlobalId…" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <span className="chip">{shown.length.toLocaleString()} rows</span>
        <span className="grow" />
        <button className="btn ghost" onClick={copy} title="Copy as tab-separated values (paste into Excel)">
          <Copy size={15} /> Copy
        </button>
      </div>
      <div className="data-scroll">
        <table className="grid sticky">
          <thead>
            <tr><th>Level</th><th>Class</th><th>Name</th><th>Tag</th><th>GlobalId</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.localId} className={r.localId === selectedId ? "sel" : ""} onClick={() => onPick(r.localId)}>
                <td>{r.level}</td><td>{r.ifcClass}</td><td>{r.name}</td><td>{r.tag}</td><td className="mono">{r.guid}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <p className="muted small pad">No elements match.</p>}
      </div>
    </div>
  );
}
