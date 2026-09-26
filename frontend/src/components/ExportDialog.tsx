import { useEffect, useState } from "react";
import type { SnapshotView } from "@nocoast/ifc-viewer";
import * as api from "../api/client";
import * as platform from "../platform";
import { runtime, turnId } from "../turns";

const PREFS_KEY = "nocoast.export";
const BUNDLE_VIEWS: SnapshotView[] = ["iso", "top", "front", "side"];
const MARK = { pass: "✓", warn: "⚠", fail: "✗" } as const;

interface Props {
  projectId: string;
  version: api.Version;
  onClose: () => void;
}

interface Prefs { author: string; organization: string; projectName: string }

function loadPrefs(): Prefs {
  try {
    return { author: "", organization: "", projectName: "", ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return { author: "", organization: "", projectName: "" };
  }
}

/**
 * Export the viewed version as a final deliverable: a validated IFC stamped with project,
 * author and prompt history, or a .zip bundle that adds 3D snapshots and reports.
 */
export function ExportDialog({ projectId, version, onClose }: Props) {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [format, setFormat] = useState<"ifc" | "zip">("zip");
  const [report, setReport] = useState<api.ValidationReport | null>(null);
  const [checking, setChecking] = useState(true);
  const [allowFailed, setAllowFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  // Quick check on open, so problems show before anyone fills in the form.
  useEffect(() => {
    let live = true;
    setChecking(true);
    api.validateVersion(projectId, version.number)
      .then((r) => live && setReport(r), (e) => live && setError(String(e instanceof Error ? e.message : e)))
      .finally(() => live && setChecking(false));
    return () => { live = false; };
  }, [projectId, version.number]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const update = (patch: Partial<Prefs>) => setPrefs((p) => ({ ...p, ...patch }));

  const run = async () => {
    setError(null);
    setSaved(null);
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch { /* preferences are a convenience only */ }
    try {
      const snapshots: { name: string; png: Uint8Array }[] = [];
      if (format === "zip") {
        for (const view of BUNDLE_VIEWS) {
          setBusy(`Rendering ${view} view…`);
          const png = await runtime.captureSnapshot(turnId(version), { view, width: 1600, height: 1200 });
          snapshots.push({ name: `${view}.png`, png });
        }
      }
      setBusy("Validating and stamping (this runs the full schema rules)…");
      const result = await api.exportVersion(projectId, version.number, {
        format,
        project_name: prefs.projectName.trim() || undefined,
        author: prefs.author.trim() || undefined,
        organization: prefs.organization.trim() || undefined,
        strict: !allowFailed,
        thorough: true,
      }, snapshots);
      setBusy("Saving…");
      const where = await platform.saveFile(result.filename, result.bytes, format);
      if (where) setSaved(`${where}${result.validation === "failed" ? " (exported despite failed validation)" : ""}`);
    } catch (e) {
      if (e instanceof api.ExportRefused) setReport(e.report);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const failed = report !== null && !report.ok;
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="export-title">
        <header className="modal-head">
          <h2 id="export-title">Export version {version.number}</h2>
          <button onClick={onClose} disabled={!!busy} aria-label="Close">✕</button>
        </header>

        <section className="export-checks" aria-live="polite">
          <h3 className="label">Validation</h3>
          {checking && <p className="muted">Checking the model…</p>}
          {report && (
            <>
              <ul className="checklist">
                {report.checks.map((c) => (
                  <li key={c.name} className={c.status}><span>{MARK[c.status]}</span> {c.name}</li>
                ))}
              </ul>
              {report.issues.length > 0 && (
                <ul className="issues">
                  {report.issues.map((i, k) => <li key={k} className={i.level}>{i.message}</li>)}
                </ul>
              )}
              <p className="muted">
                {report.schema_name} · {Object.entries(report.counts).map(([k, v]) => `${v} ${k.replace("Ifc", "")}`).join(" · ")}
              </p>
            </>
          )}
        </section>

        <div className="export-form">
          <label>Project name
            <input value={prefs.projectName} onChange={(e) => update({ projectName: e.target.value })} placeholder="Maple Street House" />
          </label>
          <label>Author
            <input value={prefs.author} onChange={(e) => update({ author: e.target.value })} placeholder="Your name" />
          </label>
          <label>Organization
            <input value={prefs.organization} onChange={(e) => update({ organization: e.target.value })} placeholder="Company or team" />
          </label>

          <fieldset className="formats">
            <legend className="label">Format</legend>
            <label>
              <input type="radio" name="format" checked={format === "zip"} onChange={() => setFormat("zip")} />
              <b>Deliverable bundle (.zip)</b>
              <span className="muted">Stamped IFC, 4 snapshots, validation report, summary and prompt history.</span>
            </label>
            <label>
              <input type="radio" name="format" checked={format === "ifc"} onChange={() => setFormat("ifc")} />
              <b>IFC only</b>
              <span className="muted">The validated model, stamped with project, author and prompt history.</span>
            </label>
          </fieldset>

          {failed && (
            <label className="override">
              <input type="checkbox" checked={allowFailed} onChange={(e) => setAllowFailed(e.target.checked)} />
              Export anyway. The file will be marked as failed validation.
            </label>
          )}
        </div>

        {error && <div className="error">{error}</div>}
        {saved && <div className="ok-note">Saved {saved}</div>}

        <footer className="modal-foot">
          <span className="muted">{busy ?? ""}</span>
          <button onClick={onClose} disabled={!!busy}>{saved ? "Done" : "Cancel"}</button>
          <button className="primary" onClick={() => void run()} disabled={!!busy || checking || (failed && !allowFailed)}>
            {busy ? "Exporting…" : format === "zip" ? "Export bundle" : "Export IFC"}
          </button>
        </footer>
      </div>
    </div>
  );
}
