import type { ReactNode } from "react";
import type { Version } from "../api/client";

export type Stage = "idle" | "planning" | "building" | "loading" | "ready";

const STEPS: [Stage, string][] = [
  ["planning", "Generating instructions"],
  ["building", "Building IFC"],
  ["loading", "Loading model"],
  ["ready", "3D building"],
];

const EXAMPLES = [
  "Create a two-story rectangular house. The first floor should have a kitchen and living room. The second floor should have three bedrooms. Add windows to the exterior walls and a garage.",
  "Create a two-story house with four bedrooms, a garage, and a flat roof.",
  "Design a modern single storey house with lots of natural light and a front porch.",
];

interface Props {
  prompt: string;
  setPrompt: (p: string) => void;
  onGenerate: () => void;
  stage: Stage;
  /** Live message from the pipeline, e.g. "repair attempt 1". */
  detail: string | null;
  error: string | null;
  backendUp: boolean | null;
  /** The project's current head version, if any. */
  head: Version | null;
  onUndo: () => void;
  onNewProject: () => void;
  /** Version history rendered by the caller (turn cards). */
  history: ReactNode;
}

export function PromptPanel({
  prompt, setPrompt, onGenerate, stage, detail, error, backendUp, head, onUndo, onNewProject, history,
}: Props) {
  const busy = !error && (stage === "planning" || stage === "building" || stage === "loading");
  const current = STEPS.findIndex(([s]) => s === stage);
  const editing = head !== null;

  return (
    <aside className="panel left">
      <header className="brand">
        <span className="logo">◆</span> Generative BIM
        <span className={`dot ${backendUp ? "ok" : backendUp === false ? "bad" : ""}`}
          title={backendUp ? "Backend connected" : "Backend offline"} />
      </header>

      <div className="project-bar">
        <span className="muted">{head ? `Version ${head.number}${head.llm ? ` · ${head.llm}` : ""}` : "New project"}</span>
        <span className="grow" />
        <button onClick={onUndo} disabled={busy || !head || head.number < 2} title="Go back to the previous version">Undo</button>
        <button onClick={onNewProject} disabled={busy} title="Start a new project">New</button>
      </div>

      <label className="label" htmlFor="prompt">{editing ? "Describe a change" : "Describe a building"}</label>
      <textarea
        id="prompt"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => (e.ctrlKey || e.metaKey) && e.key === "Enter" && !busy && onGenerate()}
        placeholder={editing ? "Add a front porch and make the garage bigger." : "Create a two-story house with four bedrooms, a garage, and a flat roof."}
        rows={editing ? 3 : 7}
      />
      <button className="primary" onClick={onGenerate} disabled={busy || !prompt.trim()}>
        {busy ? "Working…" : editing ? "Apply change" : "Generate"} <kbd>Ctrl ↵</kbd>
      </button>
      {backendUp === false && <p className="hint bad">Backend offline. The desktop app starts it automatically; otherwise run <code>python main.py</code> in backend/.</p>}

      {!editing && (
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip" onClick={() => setPrompt(ex)} disabled={busy}>
              {ex.length > 70 ? ex.slice(0, 68) + "…" : ex}
            </button>
          ))}
        </div>
      )}

      {stage !== "idle" && stage !== "ready" && (
        <ol className="steps">
          {STEPS.map(([s, label], i) => {
            // On error, `stage` stays at the step that failed.
            const state = i < current ? "done" : i === current ? (error ? "failed" : "active") : "";
            return <li key={s} className={state}>{label}{i === current && detail ? <span className="muted"> · {detail}</span> : null}</li>;
          })}
        </ol>
      )}
      {error && <div className="error">{error}</div>}

      {head && (
        <section className="result">
          <h3>Interpretation <span className="muted">· v{head.number} · {head.mode}</span></h3>
          <ul>{head.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          <div className="counts">
            {Object.entries(head.summary.counts).map(([k, v]) => (
              <span key={k}><b>{v}</b> {k.replace("Ifc", "")}</span>
            ))}
          </div>
        </section>
      )}

      {history}
    </aside>
  );
}
