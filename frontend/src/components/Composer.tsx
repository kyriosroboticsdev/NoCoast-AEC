import { ArrowUp, Check, ChevronDown, Crosshair, FileUp, ImagePlus, LoaderCircle, Plus, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { formatSize, imageFiles, pickImages, readImages, type Attachment } from "../state/attachments";

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
  onSubmit: (text: string, images: Attachment[]) => void;
  onAttach: () => void;
  placeholder?: string;
  /** Viewer selection the next prompt is about, shown as a removable chip. */
  focus?: { id: string; label: string } | null;
  onClearFocus?: () => void;
}

/** Close a popover on the next mousedown outside it. */
function useDismiss(open: boolean, setOpen: (v: boolean) => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open, setOpen]);
  return ref;
}

export function Composer({ size, busy, planners, planner, setPlanner, onSubmit, onAttach, placeholder, focus, onClearFocus }: Props) {
  const [text, setText] = useState("");
  // Images go with the next prompt: pick them from the + menu, drop them on the composer, or paste them.
  const [images, setImages] = useState<Attachment[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [dropping, setDropping] = useState(false);
  const [menu, setMenu] = useState(false);
  const [adding, setAdding] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const menuRef = useDismiss(menu, setMenu);
  const addRef = useDismiss(adding, setAdding);

  // Grow with content, up to a limit.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, size === "hero" ? 220 : 180)}px`;
  }, [text, size]);

  const attach = async (files: File[]) => {
    if (!files.length) return;
    const { images: added, error } = await readImages(files, images.length);
    if (added.length) setImages((list) => [...list, ...added]);
    setProblem(error);
  };

  const send = () => {
    const t = text.trim();
    if (!t || busy) return;
    onSubmit(t, images);
    setText("");
    setImages([]);
    setProblem(null);
  };

  const info = (id: string) => PLANNER_INFO[id] ?? { label: id, description: "" };

  return (
    <div className={`composer ${size} ${dropping ? "dropping" : ""}`}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        setDropping(true);
      }}
      onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setDropping(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDropping(false);
        void attach(imageFiles(e.dataTransfer.files));
      }}>
      {focus && (
        <div className="focus-chip" title={`The next prompt is about ${focus.id}`}>
          <Crosshair size={14} />
          <span>{focus.label}</span>
          {onClearFocus && <button onClick={onClearFocus} aria-label="Clear selection"><X size={13} /></button>}
        </div>
      )}
      {images.length > 0 && (
        <div className="attachments">
          {images.map((img) => (
            <div key={img.id} className="thumb" title={`${img.name} · ${formatSize(img.size)}`}>
              <img src={img.dataUrl} alt={img.name} />
              <button onClick={() => setImages((list) => list.filter((x) => x.id !== img.id))} aria-label={`Remove ${img.name}`}>
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <textarea
        ref={area}
        value={text}
        rows={1}
        onChange={(e) => setText(e.target.value)}
        onPaste={(e) => {
          const pasted = imageFiles(e.clipboardData.files);
          if (!pasted.length) return;
          e.preventDefault();
          void attach(pasted);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        placeholder={placeholder ?? "Describe an asset…"}
        autoFocus={size === "hero"}
      />
      {problem && <div className="composer-problem">{problem}</div>}
      <div className="composer-bar">
        <div className="picker" ref={addRef}>
          <button className="icon-btn round" title="Attach an image or open an IFC file" onClick={() => setAdding(!adding)}>
            <Plus size={18} />
          </button>
          {adding && (
            <div className="menu left">
              <button className="menu-item" onClick={() => { setAdding(false); void pickImages().then(attach); }}>
                <ImagePlus size={15} />
                <span className="menu-text">
                  <span>Attach images</span>
                  <small>A sketch, a plan, a photo — sent to the model with the prompt</small>
                </span>
              </button>
              <button className="menu-item" onClick={() => { setAdding(false); onAttach(); }}>
                <FileUp size={15} />
                <span className="menu-text">
                  <span>Open an IFC file</span>
                  <small>View a model in the workspace</small>
                </span>
              </button>
              <div className="menu-foot">Images can also be dropped here or pasted into the prompt.</div>
            </div>
          )}
        </div>
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
