import { ArrowUp, Check, ChevronDown, LoaderCircle, Plus, Sparkles } from "lucide-react";
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
}

export function Composer({ size, busy, planners, planner, setPlanner, onSubmit, onAttach, placeholder }: Props) {
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
        <button className="icon-btn round" title="Open an IFC file" onClick={onAttach}>
          <Plus size={18} />
        </button>
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
