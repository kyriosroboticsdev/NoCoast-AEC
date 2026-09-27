import { ChevronsUpDown, Ellipsis, House, PanelLeft, PanelRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ExportFormat } from "../api/client";
import { ExportMenu } from "./ExportMenu";

interface Props {
  title: string | null;
  sidebarOpen: boolean;
  assistantOpen: boolean;
  showAssistantToggle: boolean;
  onHome: () => void;
  onToggleSidebar: () => void;
  onToggleAssistant: () => void;
  onExport: (format: ExportFormat) => Promise<string | null>;
  exportDisabled: string | null;
  onDelete: (() => void) | null;
}

export function TopBar(p: Props) {
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setMenu(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);

  return (
    <header className="topbar">
      {!p.sidebarOpen && (
        <button className="icon-btn" title="Show sidebar" onClick={p.onToggleSidebar}>
          <PanelLeft size={18} />
        </button>
      )}
      <nav className="crumbs">
        <button className="crumb-home" onClick={p.onHome}>
          <House size={16} /> Home <ChevronsUpDown size={14} className="muted" />
        </button>
        <span className="crumb-sep">/</span>
        <span className="crumb-current">{p.title ?? "Assistant"}</span>
      </nav>
      <span className="grow" />
      <button className={`icon-btn ${p.sidebarOpen ? "on" : ""}`} title="Toggle sidebar" onClick={p.onToggleSidebar}>
        <PanelLeft size={18} />
      </button>
      {p.showAssistantToggle && (
        <button className={`icon-btn ${p.assistantOpen ? "on" : ""}`} title={p.assistantOpen ? "Hide assistant" : "Show assistant"}
          onClick={p.onToggleAssistant}>
          <PanelRight size={18} />
        </button>
      )}
      <div className="picker" ref={ref}>
        <button className="icon-btn" title="More" onClick={() => setMenu(!menu)}>
          <Ellipsis size={18} />
        </button>
        {menu && (
          <div className="menu right">
            <button className="menu-item" disabled={!p.onDelete} onClick={() => { setMenu(false); p.onDelete?.(); }}>
              Delete session
            </button>
          </div>
        )}
      </div>
      <ExportMenu onExport={p.onExport} disabledReason={p.exportDisabled} />
    </header>
  );
}
