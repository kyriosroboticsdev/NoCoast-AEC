import { useCallback, useEffect, useRef, useState } from "react";
import { IfcTurnCard, IfcViewerProvider } from "@nocoast/ifc-viewer";
import * as api from "./api/client";
import { InspectorPanel } from "./components/InspectorPanel";
import { PromptPanel, type Stage } from "./components/PromptPanel";
import * as platform from "./platform";
import { runtime, toTurn, turnId } from "./turns";
import { BimViewer, type PropertyGroup, type TreeNode } from "./viewer/BimViewer";

const PROJECT_KEY = "nocoast.project";

/** Pipeline stage names from the backend, mapped onto the panel's steps. */
const STAGE_OF: Record<string, Stage> = {
  program: "planning", edit: "planning", apply: "building", solve: "building", compile: "building",
};

const HIDDEN_BY_DEFAULT = ["IFCSPACE"]; // room volumes hide the building; toggle under Classes

export default function App() {
  const host = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<BimViewer | null>(null);
  const [viewerReady, setViewerReady] = useState(false);
  const [options, setOptions] = useState<platform.LaunchOptions | null>(null);

  const [prompt, setPrompt] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [detail, setDetail] = useState<string | null>(null);

  // Versioned project: every prompt makes a new version; the newest is the head.
  const [projectId, setProjectId] = useState<string | null>(null);
  const [versions, setVersions] = useState<api.Version[]>([]);
  const [viewing, setViewing] = useState<number | null>(null);
  const head = versions.at(-1) ?? null;

  const [modelName, setModelName] = useState<string | null>(null);
  const [modelBytes, setModelBytes] = useState<Uint8Array | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [categories, setCategories] = useState<{ name: string; count: number; visible: boolean }[]>([]);
  const [tab, setTab] = useState<"tree" | "classes">("tree");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [properties, setProperties] = useState<PropertyGroup[]>([]);

  useEffect(() => {
    if (!host.current || viewerRef.current) return;
    const viewer = new BimViewer();
    viewerRef.current = viewer;
    (window as unknown as { __viewer: BimViewer }).__viewer = viewer; // debug / smoke-test handle
    for (const c of HIDDEN_BY_DEFAULT) viewer.setCategoryVisible(c, false);
    viewer.onSelect = async (sel) => {
      setSelectedId(sel?.localId ?? null);
      setProperties(sel ? await viewer.properties(sel.localId) : []);
    };
    viewer.init(host.current).then(() => setViewerReady(true), (e) => {
      setError(`Viewer failed to start: ${e}`);
      platform.report({ status: "error", error: String(e) });
    });
    platform.launchOptions().then((o) => {
      api.setBackendUrl(o.backendUrl);
      setOptions(o);
    });
  }, []);

  useEffect(() => {
    if (!options) return;
    const check = () => api.health().then(setBackendUp);
    check();
    const t = setInterval(check, 4000);
    return () => clearInterval(t);
  }, [options]);

  const refreshCategories = useCallback(async () => {
    const v = viewerRef.current!;
    const cats = await v.categories();
    setCategories(cats.map((c) => ({ ...c, visible: !v.isCategoryHidden(c.name) })));
  }, []);

  const showModel = useCallback(async (bytes: Uint8Array, name: string) => {
    const v = viewerRef.current!;
    setProgress(0);
    setSelectedId(null);
    setProperties([]);
    await v.loadIfc(bytes, name, setProgress);
    setProgress(null);
    setModelName(name);
    setModelBytes(bytes);
    setTree(await v.spatialTree());
    await refreshCategories();
  }, [refreshCategories]);

  const fail = (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setError(msg);
    setProgress(null);
    platform.report({ status: "error", error: msg });
  };

  const showVersion = useCallback(async (v: api.Version) => {
    await showModel(await api.fetchBytes(api.backendUrl(v.ifc_url)), `v${v.number}.ifc`);
    setViewing(v.number);
  }, [showModel]);

  /** Record a new version: history list, a turn card, and the main viewer. */
  const adopt = useCallback(async (v: api.Version) => {
    setVersions((vs) => [...vs.filter((x) => x.number !== v.number), v]);
    void runtime.addTurn(toTurn(v));
    setStage("loading");
    await showVersion(v);
    setStage("ready");
  }, [showVersion]);

  const onEvent = useCallback((e: api.StageEvent) => {
    const s = STAGE_OF[e.stage];
    if (s) setStage(s);
    setDetail(e.message);
  }, []);

  const openProject = useCallback(async (id: string) => {
    const p = await api.getProject(id);
    setProjectId(id);
    setVersions(p.versions);
    for (const v of p.versions) void runtime.addTurn(toTurn(v));
    if (p.head) await showVersion(p.head);
  }, [showVersion]);

  const newProject = useCallback(() => {
    localStorage.removeItem(PROJECT_KEY);
    for (const v of versions) runtime.removeTurn(turnId(v));
    setProjectId(null);
    setVersions([]);
    setViewing(null);
    setStage("idle");
    setError(null);
    void viewerRef.current?.clear();
    setModelName(null);
    setModelBytes(null);
    setTree(null);
    setCategories([]);
  }, [versions]);

  /** First prompt designs a building; later prompts edit the head version. */
  const generate = useCallback(async (text: string) => {
    setError(null);
    setDetail(null);
    try {
      setStage("planning");
      await api.waitForBackend();
      let id = projectId;
      if (!id) {
        id = (await api.createProject("Untitled")).id;
        localStorage.setItem(PROJECT_KEY, id);
        setProjectId(id);
      }
      const v = await api.sendPrompt(id, text, head?.number ?? null, onEvent);
      await adopt(v);
      setPrompt("");
    } catch (e) {
      fail(e);
    }
  }, [projectId, head, onEvent, adopt]);

  const undo = useCallback(async () => {
    if (!projectId || !head) return;
    setError(null);
    try {
      setStage("building");
      await adopt(await api.revert(projectId, head.parent ?? head.number - 1, onEvent));
    } catch (e) {
      fail(e);
    }
  }, [projectId, head, onEvent, adopt]);

  const openFile = async () => {
    try {
      const file = await platform.openIfc();
      if (!file) return;
      setError(null);
      setStage("idle");
      setViewing(null);
      await showModel(file.data, file.name);
    } catch (e) {
      fail(e);
    }
  };

  const loadSample = async () => {
    try {
      setError(null);
      await showModel(await api.fetchBytes(new URL("samples/sample-house.ifc", location.href).href), "sample-house.ifc");
    } catch (e) {
      fail(e);
    }
  };

  const saveFile = async () => {
    try {
      if (modelBytes && modelName) await platform.saveIfc(modelName, modelBytes);
    } catch (e) {
      fail(e);
    }
  };

  // Reopen the last project once the viewer and backend are up. Skipped for
  // smoke-test runs so a scripted prompt always starts a fresh design.
  const reopened = useRef(false);
  useEffect(() => {
    if (reopened.current || !viewerReady || !backendUp || !options || options.autoload || options.prompt) return;
    reopened.current = true;
    const stored = localStorage.getItem(PROJECT_KEY);
    if (!stored) return;
    openProject(stored).catch(() => localStorage.removeItem(PROJECT_KEY)); // stale id from an older database
  }, [viewerReady, backendUp, options, openProject]);

  // Smoke-test hooks (BIM_AUTOLOAD / BIM_PROMPT / BIM_SMOKE_SELECT) once the viewer is up.
  useEffect(() => {
    if (!viewerReady || !options) return;
    platform.report({ status: "viewer-ready" });
    const { autoload, prompt: auto, select } = options;
    const run = async () => {
      if (autoload) {
        await showModel(await api.fetchBytes(new URL(autoload, location.href).href), autoload.split("/").pop()!);
      } else if (auto) {
        setPrompt(auto);
        await generate(auto);
      } else return;
      if (select) await viewerRef.current!.selectFirstOf(select);
      await new Promise((r) => setTimeout(r, 500)); // let React render the panels
      if (window.__bim?.status === "error") return;
      platform.report({
        status: "ready",
        model: document.querySelector(".toolbar .grow + span")?.textContent,
        tree: document.querySelectorAll(".tree .row").length,
        propRows: document.querySelectorAll(".props tr").length,
      });
    };
    run().catch(fail);
  }, [viewerReady, options]); // eslint-disable-line react-hooks/exhaustive-deps

  const v = viewerRef.current;
  const history = versions.length > 0 && (
    <section className="history" aria-label="Version history">
      <h3 className="label">History</h3>
      <ol>
        {[...versions].reverse().map((ver, i) => (
          <li key={ver.number} className={ver.number === viewing ? "viewing" : ""}>
            <div className="history-head">
              <b>v{ver.number}</b>
              <span className="history-prompt">{ver.prompt ?? ver.notes[0] ?? ver.mode}</span>
            </div>
            <IfcTurnCard
              turnId={turnId(ver)}
              height={170}
              liveOn={i === 0 ? "visible" : "hover"}
              onExpand={() => void showVersion(ver).catch(fail)}
            />
          </li>
        ))}
      </ol>
    </section>
  );

  return (
    <IfcViewerProvider runtime={runtime}>
    <div className="app">
      <PromptPanel prompt={prompt} setPrompt={setPrompt} onGenerate={() => generate(prompt)} stage={stage}
        detail={detail} error={error} backendUp={backendUp} head={head}
        onUndo={() => void undo()} onNewProject={newProject} history={history} />

      <main className="stage">
        <div className="toolbar">
          <button onClick={openFile} disabled={!viewerReady}>Open IFC…</button>
          <button onClick={loadSample} disabled={!viewerReady}>Sample</button>
          <button onClick={saveFile} disabled={!modelBytes}>Save IFC…</button>
          <span className="sep" />
          <button onClick={() => v?.fit()} disabled={!modelName}>Fit</button>
          <button onClick={() => v?.hideSelection()} disabled={selectedId === null}>Hide</button>
          <button onClick={() => v?.isolateSelection()} disabled={selectedId === null}>Isolate</button>
          <button onClick={async () => { await v?.showAll(); await refreshCategories(); setTree(tree && { ...tree }); }}
            disabled={!modelName}>Show all</button>
          <span className="grow" />
          <span className="muted">{viewing !== null && head && viewing !== head.number ? `viewing v${viewing} (head is v${head.number}) · ` : ""}{modelName ?? "No model"}</span>
        </div>
        <div className="viewport" ref={host}>
          {progress !== null && (
            <div className="overlay">
              <div>Loading model… {Math.round(progress * 100)}%</div>
              <div className="bar"><i style={{ width: `${progress * 100}%` }} /></div>
            </div>
          )}
          {!modelName && progress === null && viewerReady && (
            <div className="empty">
              <p>Type a prompt and press <b>Generate</b>, or</p>
              <p><button onClick={openFile}>Open an IFC file</button> · <button onClick={loadSample}>Load the sample</button></p>
            </div>
          )}
          <div className="hint-bar muted">Left-drag orbit · Right-drag pan · Wheel zoom · Click to select</div>
        </div>
      </main>

      <InspectorPanel tab={tab} setTab={setTab} tree={tree} categories={categories}
        onCategory={async (name, visible) => { await v?.setCategoryVisible(name, visible); await refreshCategories(); }}
        selectedId={selectedId}
        onSelect={(id) => v?.select(id)}
        onToggle={(node, visible) => v?.setItemsVisible(node.ids, visible)}
        properties={properties} />
    </div>
    </IfcViewerProvider>
  );
}
