import { Check, ChevronDown, Download, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { EXPORTS, type ExportFormat } from "../api/client";

interface Props {
  /** Runs the download; resolves with the saved file name, or null when the user cancelled. */
  onExport: (format: ExportFormat) => Promise<string | null>;
  /** Why exporting is not possible right now (preview on screen, nothing loaded …). */
  disabledReason: string | null;
}

/**
 * Export IFC, with everything else that belongs to the model one click further: the bundle, the
 * schedule, the spec. The main button is the IFC — the thing people come here for — and the caret
 * opens the rest.
 */
export function ExportMenu({ onExport, disabledReason }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(null), 2600);
    return () => clearTimeout(t);
  }, [saved]);

  const run = async (format: ExportFormat) => {
    setOpen(false);
    setBusy(format);
    try {
      const name = await onExport(format);
      if (name) setSaved(name);
    } finally {
      setBusy(null);
    }
  };

  const disabled = !!disabledReason || busy !== null;

  return (
    <div className="export" ref={ref}>
      <button className="btn export-main" disabled={disabled} title={disabledReason ?? "Download the IFC model"}
        onClick={() => run("ifc")}>
        {busy ? <LoaderCircle size={16} className="spin" /> : saved ? <Check size={16} /> : <Download size={16} />}
        {saved ? "Saved" : "Export IFC"}
      </button>
      <button className="btn export-more" disabled={disabled} title="Other export formats" onClick={() => setOpen(!open)}>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="menu right export-menu">
          {EXPORTS.map((e) => (
            <button key={e.format} className="menu-item" onClick={() => run(e.format)}>
              <span>{e.label}</span>
              <small className="muted">{e.hint}</small>
            </button>
          ))}
        </div>
      )}
      {saved && <span className="export-toast">Saved {saved}</span>}
    </div>
  );
}
