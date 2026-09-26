import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import fragmentsWorkerUrl from "@thatopen/fragments/worker?url";
import {
  IfcInspector,
  IfcTurnCard,
  IfcViewerProvider,
  IfcViewerRuntime,
  useTurns,
  type TurnRef,
} from "@nocoast/ifc-viewer";
import { BrowserTurnSource, type FixtureEntry } from "./browserSource";
import "./playground.css";

const source = new BrowserTurnSource();
const runtime = new IfcViewerRuntime(source, {
  wasmPath: "/wasm/",
  fragmentsWorkerUrl,
}).start();

const manifest: FixtureEntry[] = await fetch("/fixtures/manifest.json").then((r) => r.json());
const turnFixtures = manifest.filter((m) => m.id !== "broken");
const brokenFixture = manifest.find((m) => m.id === "broken")!;
let seq = 0;

function emitFixture(f: FixtureEntry): TurnRef {
  seq += 1;
  const turn: TurnRef = {
    id: `turn-${seq}`,
    ifcPath: `/fixtures/${f.file}`,
    createdAt: new Date().toISOString(),
    label: f.prompt,
  };
  source.emit(turn);
  return turn;
}

const api = {
  runtime,
  source,
  /** Simulate the agent producing the next turn in the scripted session. */
  next: () => emitFixture(turnFixtures[seq % turnFixtures.length]),
  broken: () => emitFixture(brokenFixture),
  stress: (n = 20) => Array.from({ length: n }, () => api.next()),
  liveCanvases: () => document.querySelectorAll(".ncv-card canvas").length,
};
declare global {
  interface Window {
    __ncv: typeof api;
  }
}
window.__ncv = api;

function Transcript({ onInspect }: { onInspect: (id: string) => void }) {
  const turns = useTurns();
  const endRef = useRef<HTMLDivElement>(null);
  // Braces matter: newer browsers return a Promise from scrollIntoView, and
  // React would treat a returned value as the effect's cleanup function.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  if (turns.length === 0) {
    return (
      <div className="pg-empty">
        <p>No turns yet.</p>
        <p>Press <strong>Next turn</strong> to simulate the agent writing its first IFC file.</p>
      </div>
    );
  }
  return (
    <ol className="pg-transcript">
      {turns.map((t, i) => {
        const latest = i === turns.length - 1;
        return (
          <li key={t.turn.id} className="pg-turn">
            <div className="pg-msg pg-user">{t.turn.label}</div>
            <div className="pg-msg pg-agent">
              <div className="pg-agent-head">
                <span>{t.status === "error" ? "The file I wrote didn't load." : `Updated the model · ${t.turn.id}`}</span>
                {t.timings && (
                  <span className="pg-meta">
                    {t.cached ? "cached" : `convert ${t.timings.convert ?? "…"} ms`} · snapshot {t.timings.snapshot ?? "…"} ms
                  </span>
                )}
              </div>
              <IfcTurnCard turnId={t.turn.id} liveOn={latest ? "visible" : "hover"} onExpand={onInspect} />
            </div>
          </li>
        );
      })}
      <div ref={endRef} />
    </ol>
  );
}

function App() {
  const turns = useTurns();
  const [inspecting, setInspecting] = useState<string | null>(null);
  const latestReady = [...turns].reverse().find((t) => t.status === "ready")?.turn.id ?? null;
  const shown = inspecting ?? latestReady;

  return (
    <div className="pg-app">
      <header className="pg-header">
        <h1>IFC viewer playground</h1>
        <div className="pg-actions">
          <button type="button" onClick={() => api.next()}>Next turn</button>
          <button type="button" onClick={() => api.broken()}>Broken turn</button>
          <button type="button" onClick={() => api.stress(20)}>Add 20 turns</button>
        </div>
      </header>
      <main className="pg-main">
        <section className="pg-chat" aria-label="Agent transcript">
          <Transcript onInspect={setInspecting} />
        </section>
        <section className="pg-side" aria-label="Inspector">
          <IfcInspector turnId={shown} onClose={inspecting ? () => setInspecting(null) : undefined} />
        </section>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <IfcViewerProvider runtime={runtime}>
      <App />
    </IfcViewerProvider>
  </StrictMode>,
);
