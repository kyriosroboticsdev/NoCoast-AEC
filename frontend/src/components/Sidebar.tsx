import { Box, FolderOpen, PanelLeft, Plus, Search, Trash } from "lucide-react";
import { useState } from "react";
import { Logo } from "./Logo";
import { PANEL_RANGE } from "../state/layout";
import type { Session } from "../state/sessions";
import { Resizer } from "./Resizer";

interface Props {
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onOpenFile: () => void;
  onSample: () => void;
  onDelete: (id: string) => void;
  onCollapse: () => void;
  backendUp: boolean | null;
  planners: string[];
  width: number;
  onResize: (width: number) => void;
  onResetWidth: () => void;
}

export function Sidebar(p: Props) {
  const [query, setQuery] = useState<string | null>(null);
  const list = query ? p.sessions.filter((s) => s.title.toLowerCase().includes(query.toLowerCase())) : p.sessions;

  return (
    <aside className="sidebar" style={{ width: p.width }}>
      <div className="sidebar-head">
        <div className="brand-home" title="tekt"><Logo height={30} /></div>
        <button className="icon-btn" title="Search sessions" onClick={() => setQuery(query === null ? "" : null)}>
          <Search size={17} />
        </button>
        <button className="icon-btn" title="Collapse sidebar" onClick={p.onCollapse}>
          <PanelLeft size={17} />
        </button>
      </div>

      {query !== null && (
        <input className="side-search" autoFocus placeholder="Search sessions…" value={query}
          onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setQuery(null)} />
      )}

      <nav className="nav">
        <button className={`nav-item ${p.activeId === null ? "on" : ""}`} onClick={p.onNew}>
          <Plus size={17} /> New Session
        </button>
        <button className="nav-item" onClick={p.onOpenFile}>
          <FolderOpen size={17} /> Open IFC…
        </button>
        <button className="nav-item" onClick={p.onSample}>
          <Box size={17} /> Sample model
        </button>
      </nav>

      <div className="side-section">Past sessions</div>
      <div className="session-list">
        {list.map((s) => (
          <div key={s.id} className={`session ${s.id === p.activeId ? "on" : ""}`} onClick={() => p.onSelect(s.id)} title={s.title}>
            <span className="session-title">{s.title}</span>
            <button className="icon-btn tiny" title="Delete session"
              onClick={(e) => { e.stopPropagation(); p.onDelete(s.id); }}>
              <Trash size={14} />
            </button>
          </div>
        ))}
        {!list.length && <p className="muted small pad-x">{query ? "No matches." : "Nothing yet — describe a building to start."}</p>}
      </div>

      <div className="status-card">
        <div className="status-row">
          <span className="status-title">Backend</span>
          <span className={`pill ${p.backendUp ? "ok" : p.backendUp === false ? "bad" : ""}`}>
            {p.backendUp ? "Connected" : p.backendUp === false ? "Offline" : "…"}
          </span>
        </div>
        <div className="muted small">
          {p.backendUp
            ? `Model: ${p.planners[0] ?? "—"} · IfcOpenShell`
            : "Started automatically by the desktop app, or run python main.py in backend/."}
        </div>
      </div>

      <Resizer className="resizer-sidebar" label="Sidebar width" onReset={p.onResetWidth}
        width={{ value: p.width, dir: 1, ...PANEL_RANGE.sidebar, onChange: p.onResize }} />
    </aside>
  );
}
