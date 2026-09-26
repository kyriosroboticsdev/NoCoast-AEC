import { ArrowUp, Box, Check, ChevronDown, Crosshair, FolderOpen, LoaderCircle, Paperclip, Plus, Sparkles, X } from "lucide-react";
import type { ComponentRecord } from "../api/client";
import { useEffect, useRef, useState } from "react";

export interface PlannerOption {
  id: string;
  label: string;
  description: string;
}

/** The backend's LLM providers (backend/llm); the first in the list is its configured default. */
export const PLANNER_INFO: Record<string, Omit<PlannerOption, "id">> = {
  mock: { label: "Offline mock", description: "Canned responses, no model. For demos and tests." },
  llamacpp: { label: "Local GGUF", description: "llama.cpp on this machine." },
  ollama: { label: "Ollama", description: "A local Ollama model." },
  claude: { label: "Claude", description: "Anthropic API. Needs ANTHROPIC_API_KEY." },
  openai: { label: "OpenAI-compatible", description: "Any /v1 endpoint set in backend/.env." },
};

interface Props {
  size: "hero" | "dock";
  busy: boolean;
  planners: string[];
  planner: string | null;
  setPlanner: (p: string) => void;
  onSubmit: (text: string) => void;
  onAttach: () => void;
  placeholder?: string;
  /** Viewer selection the next prompt is about, shown as a removable chip. */
  focus?: { id: string; label: string } | null;
  onClearFocus?: () => void;
  /** IFC components attached to this session's project (placeable by prompt). */
  components?: ComponentRecord[];
  onAttachComponents?: () => void;
  onRemoveComponent?: (id: string) => void;
  /** "Uploading 2 files…" while attachments are being processed. */
  uploading?: string | null;
  uploadErrors?: { filename: string; error: string }[];
  onDismissErrors?: () => void;
}

const dims = (c: ComponentRecord) => `${c.width} × ${c.depth} × ${c.height} m`;

export function Composer({
  size, busy, planners, planner, setPlanner, onSubmit, onAttach, placeholder, focus, onClearFocus,
  components = [], onAttachComponents, onRemoveComponent, uploading, uploadErrors = [], onDismissErrors,
}: Props) {
  const [attachMenu, setAttachMenu] = useState(false);
  const attachRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!attachMenu) return;
    const close = (e: MouseEvent) => !attachRef.current?.contains(e.target as Node) && setAttachMenu(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [attachMenu]);
  const [text, setText] = useState("");
  const [menu, setMenu] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Grow with content, up to a limit.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, size === "hero" ? 220 : 180)}px`;
  }, [text, size]);

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => !menuRef.current?.contains(e.target as Node) && setMenu(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);

  const send = () => {
    const t = text.trim();
    if (!t || busy) return;
    onSubmit(t);
    setText("");
  };

  const info = (id: string) => PLANNER_INFO[id] ?? { label: id, description: "" };

  return (
    <div className={`composer ${size}`}>
      {(components.length > 0 || uploading) && (
        <div className="attachments" aria-label="Attached components">
          {components.map((c) => (
            <span key={c.id} className="attachment" title={`${c.filename} · ${c.elements} element(s) · from ${c.schema_in}, ${c.unit_in}s`}>
              <button className="attachment-main" onClick={() => setText((t) => `${t}${t && !t.endsWith(" ") ? " " : ""}the ${c.name}`)}>
                <Box size={14} />
                <span className="attachment-name">{c.name}</span>
                <small>{dims(c)}</small>
              </button>
              {onRemoveComponent && (
                <button className="attachment-x" onClick={() => onRemoveComponent(c.id)} aria-label={`Remove ${c.name}`}><X size={12} /></button>
              )}
            </span>
          ))}
          {uploading && <span className="attachment pending"><LoaderCircle size={14} className="spin" /> {uploading}</span>}
        </div>
      )}
      {uploadErrors.length > 0 && (
        <div className="attach-errors" role="alert">
          {uploadErrors.map((e) => <div key={e.filename}><b>{e.filename}</b>: {e.error}</div>)}
          {onDismissErrors && <button onClick={onDismissErrors} aria-label="Dismiss"><X size={13} /></button>}
        </div>
      )}
      {focus && (
        <div className="focus-chip" title={`The next prompt is about ${focus.id}`}>
          <Crosshair size={14} />
          <span>{focus.label}</span>
          {onClearFocus && <button onClick={onClearFocus} aria-label="Clear selection"><X size={13} /></button>}
        </div>
      )}
      <textarea
        ref={area}
        value={text}
        rows={1}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        placeholder={placeholder ?? "Describe a building…"}
        autoFocus={size === "hero"}
      />
      <div className="composer-bar">
        {onAttachComponents ? (
          <div className="picker" ref={attachRef}>
            <button className="icon-btn round" title="Attach or open IFC files" onClick={() => setAttachMenu(!attachMenu)}>
              <Plus size={18} />
            </button>
            {attachMenu && (
              <div className="menu up">
                <button className="menu-item" onClick={() => { setAttachMenu(false); onAttachComponents(); }}>
                  <Paperclip size={15} />
                  <span className="menu-text">
                    <span>Attach IFC components…</span>
                    <small>Parts the model can place: a stair, a kitchen, vendor furniture. Several at once.</small>
                  </span>
                </button>
                <button className="menu-item" onClick={() => { setAttachMenu(false); onAttach(); }}>
                  <FolderOpen size={15} />
                  <span className="menu-text">
                    <span>Open an IFC file</span>
                    <small>View a model in a new session.</small>
                  </span>
                </button>
              </div>
            )}
          </div>
        ) : (
          <button className="icon-btn round" title="Open an IFC file" onClick={onAttach}>
            <Plus size={18} />
          </button>
        )}
        <span className="grow" />
        {planner && <div className="picker" ref={menuRef}>
          <button className="picker-btn" onClick={() => setMenu(!menu)}>
            {info(planner).label} <ChevronDown size={14} />
          </button>
          {menu && (
            <div className="menu">
              <div className="menu-label">Model</div>
              {planners.map((p, i) => (
                <button key={p} className={`menu-item ${p === planner ? "on" : ""}`}
                  onClick={() => { setPlanner(p); setMenu(false); }}>
                  <Sparkles size={15} />
                  <span className="menu-text">
                    <span>{info(p).label}{i === 0 && <small className="muted"> · default</small>}</span>
                    {info(p).description && <small>{info(p).description}</small>}
                  </span>
                  {p === planner && <Check size={15} />}
                </button>
              ))}
              <div className="menu-foot">The default comes from LLM_PROVIDER in backend/.env.</div>
            </div>
          )}
        </div>}
        {busy && <LoaderCircle size={20} className="spin muted" />}
        <button className="send" disabled={!text.trim() || busy} onClick={send} title="Send (Enter)">
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  );
}
