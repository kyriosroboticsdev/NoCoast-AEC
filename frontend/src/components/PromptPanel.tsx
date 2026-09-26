import type { BuildResult, PlanResult } from "../api/client";

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
  error: string | null;
  backendUp: boolean | null;
  plan: PlanResult | null;
  build: BuildResult | null;
}

export function PromptPanel({ prompt, setPrompt, onGenerate, stage, error, backendUp, plan, build }: Props) {
  const busy = !error && (stage === "planning" || stage === "building" || stage === "loading");
  const current = STEPS.findIndex(([s]) => s === stage);

  return (
    <aside className="panel left">
      <header className="brand">
        <span className="logo">◆</span> Generative BIM
        <span className={`dot ${backendUp ? "ok" : backendUp === false ? "bad" : ""}`}
          title={backendUp ? "Backend connected" : "Backend offline"} />
      </header>

      <label className="label" htmlFor="prompt">Describe a building</label>
      <textarea
        id="prompt"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => (e.ctrlKey || e.metaKey) && e.key === "Enter" && !busy && onGenerate()}
        placeholder="Create a two-story house with four bedrooms, a garage, and a flat roof."
        rows={7}
      />
      <button className="primary" onClick={onGenerate} disabled={busy || !prompt.trim()}>
        {busy ? "Working…" : "Generate"} <kbd>Ctrl ↵</kbd>
      </button>
      {backendUp === false && <p className="hint bad">Backend offline. The desktop app starts it automatically; otherwise run <code>python main.py</code> in backend/.</p>}

      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} className="chip" onClick={() => setPrompt(ex)} disabled={busy}>
            {ex.length > 70 ? ex.slice(0, 68) + "…" : ex}
          </button>
        ))}
      </div>

      {stage !== "idle" && (
        <ol className="steps">
          {STEPS.map(([s, label], i) => {
            // On error, `stage` stays at the step that failed.
            const state = i < current ? "done" : i === current ? (error ? "failed" : s === "ready" ? "done" : "active") : "";
            return <li key={s} className={state}>{label}</li>;
          })}
        </ol>
      )}
      {error && <div className="error">{error}</div>}

      {plan && (
        <section className="result">
          <h3>Interpretation <span className="muted">· {plan.planner} planner</span></h3>
          <ul>{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </section>
      )}
      {build && (
        <section className="result">
          <h3>IFC <span className="muted">· {build.summary.schema} · {build.summary.elements} elements · {build.seconds}s</span></h3>
          <div className="counts">
            {Object.entries(build.summary.counts).map(([k, v]) => (
              <span key={k}><b>{v}</b> {k.replace("Ifc", "")}</span>
            ))}
          </div>
        </section>
      )}
      {plan && (
        <details className="result">
          <summary>Structured BIM instructions ({plan.spec.elements.length} elements)</summary>
          <pre>{JSON.stringify(plan.spec, null, 2)}</pre>
        </details>
      )}
    </aside>
  );
}
