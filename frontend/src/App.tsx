import { useCallback, useEffect, useRef, useState } from "react";
import { IfcViewerProvider } from "@nocoast/ifc-viewer";
import * as api from "./api/client";
import { Assistant } from "./components/Assistant";
import { Home } from "./components/Home";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Workspace, type Tab } from "./components/Workspace";
import * as platform from "./platform";
import { addMessage, patchRun, uid, upsertStep, useSessions, type Session, type TraceStep } from "./state/sessions";
import { ensureTurn, runtime } from "./turns";
import {
  BimViewer, type ElementRow, type ElementSummary, type LevelNode, type ModelStats, type PropertyGroup,
} from "./viewer/BimViewer";

const SAMPLE_URL = "samples/sample-house.ifc";

interface Loaded {
  key: string;
  name: string;
  schema: string;
  bytes: Uint8Array;
}

export default function App() {
  const { sessions, active, activeId, setActiveId, create, update, remove } = useSessions();
  const activeRef = useRef(activeId);
  activeRef.current = activeId;
  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;

  // Version cards for the open conversation (registered once; re-adding reprocesses).
  useEffect(() => {
    for (const m of active?.messages ?? []) if (m.run?.version) ensureTurn(m.run.version);
  }, [active?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- viewer ---------------------------------------------------------------
  const hostRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<BimViewer | null>(null);
  const [viewerReady, setViewerReady] = useState(false);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const loadedKey = useRef<string | null>(null); // sync copy, avoids double loads
  const [progress, setProgress] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stats, setStats] = useState<ModelStats | null>(null);
  const [levels, setLevels] = useState<LevelNode[]>([]);
  const [rows, setRows] = useState<ElementRow[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<ElementSummary | null>(null);
  const [properties, setProperties] = useState<PropertyGroup[]>([]);
  const [roomsVisible, setRoomsVisible] = useState(false);
  const [treeVersion, setTreeVersion] = useState(0);

  // --- chrome ---------------------------------------------------------------
  const [options, setOptions] = useState<platform.LaunchOptions | null>(null);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  // LLM providers the backend offers (mock | llamacpp | claude | ollama | openai); "" = backend default.
  const [planners, setPlanners] = useState<string[]>([]);
  const [planner, setPlanner] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [treeOpen, setTreeOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("model");
  const localFiles = useRef(new Map<string, Uint8Array>()); // session id → bytes of a file opened from disk

  useEffect(() => {
    if (!hostRef.current || viewerRef.current) return;
    const viewer = new BimViewer();
    viewerRef.current = viewer;
    (window as unknown as { __viewer: BimViewer }).__viewer = viewer; // debug / smoke-test handle
    viewer.setCategoryVisible("IFCSPACE", false); // room volumes hide the building
    viewer.onSelect = async (sel) => {
      setSelectedId(sel?.localId ?? null);
      setSelected(sel ? await viewer.elementSummary(sel.localId) : null);
      setProperties(sel ? await viewer.properties(sel.localId) : []);
    };
    viewer.init(hostRef.current).then(() => setViewerReady(true), (e) => {
      setLoadError(`Viewer failed to start: ${e}`);
      platform.report({ status: "error", error: String(e) });
    });
    platform.launchOptions().then((o) => {
      api.setBackendUrl(o.backendUrl);
      setOptions(o);
    });
  }, []);

  useEffect(() => {
    if (!options) return;
    // Poll quickly while the backend boots, then settle to every 4 s.
    let timer: ReturnType<typeof setTimeout>;
    let seen = false;
    const check = async () => {
      const i = await api.info();
      setBackendUp(i.ok || (seen ? false : null));
      if (i.ok) {
        seen = true;
        if (i.llm) {
          setPlanners(i.llm.providers);
          const current = i.llm.provider;
          setPlanner((p) => p || current);
        }
      }
      timer = setTimeout(check, seen ? 4000 : 1000);
    };
    check();
    return () => clearTimeout(timer);
  }, [options]);

  // --- loading models into the viewer -----------------------------------------

  const showModel = useCallback(async (bytes: Uint8Array, name: string, key: string, onProgress?: (p: number) => void) => {
    const v = viewerRef.current!;
    loadedKey.current = key;
    setLoadError(null);
    setProgress(0);
    setSelectedId(null);
    setSelected(null);
    setProperties([]);
    setStats(null);
    setRows(null);
    await v.loadIfc(bytes, name, (p) => { setProgress(p); onProgress?.(p); });
    const head = new TextDecoder().decode(bytes.subarray(0, 4000));
    const schema = head.match(/FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'/i)?.[1] ?? "";
    setLevels(await v.levels());
    setTreeVersion((n) => n + 1);
    setLoaded({ key, name, schema, bytes });
    setProgress(null);
    const s = await v.stats();
    setStats(s);
    return s ?? { elements: 0, levels: 0, triangles: 0, extent: [0, 0, 0] as [number, number, number] };
  }, []);

  const clearModel = useCallback(async () => {
    loadedKey.current = null;
    setLoaded(null);
    setLevels([]);
    setStats(null);
    setRows(null);
    setSelectedId(null);
    setSelected(null);
    setProperties([]);
    await viewerRef.current?.clear();
  }, []);

  // Switching sessions loads that session's model.
  useEffect(() => {
    if (!viewerReady) return;
    const model = active?.model;
    if (!active || !model) {
      // A load for this same session may be in flight (its model is attached when it finishes).
      const mine = active && loadedKey.current?.startsWith(`${active.id}:`);
      if (loadedKey.current && !mine && !busy) clearModel();
      return;
    }
    const key = `${active.id}:${model.name}`;
    if (loadedKey.current === key) return;
    const local = localFiles.current.get(active.id);
    (async () => {
      try {
        if (model.url) await showModel(await api.fetchBytes(model.url), model.name, key);
        else if (local) await showModel(local, model.name, key);
        else {
          await clearModel();
          setLoadError(`${model.name} was opened from disk in an earlier run. Open it again to view it.`);
        }
      } catch (e) {
        setProgress(null);
        setLoadError(`Couldn't load ${model.name}: ${e instanceof Error ? e.message : e}`);
      }
    })();
  }, [viewerReady, active?.id, active?.model?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (tab === "data" && loaded && rows === null) viewerRef.current!.elementRows().then(setRows);
  }, [tab, loaded, rows]);

  // --- actions ------------------------------------------------------------------

  /**
   * Stream one pipeline run into an assistant message: stage events become top-level trace
   * steps, the builder's detailed steps nest under the stage that is running, and the
   * client adds the download + viewer-load steps. Resolves with the finished version.
   */
  const runPipeline = useCallback(async (sid: string, aid: string,
    call: (onEvent: (e: api.StageEvent) => void) => Promise<api.Version>) => {
    let stageStep: TraceStep | null = null;
    let stageKey = "";
    let stageT0 = 0;
    const closeStage = (status: TraceStep["status"] = "done", error?: string) => {
      if (!stageStep) return;
      update(sid, upsertStep(aid, { ...stageStep, status, error, ms: Math.round(performance.now() - stageT0) }));
      stageStep = null;
      stageKey = "";
    };
    const onEvent = (e: api.StageEvent) => {
      if (e.stage === "step") {
        const st = e.data as unknown as TraceStep;
        update(sid, upsertStep(aid, { ...st, parent: st.parent ?? stageStep?.id ?? null }));
        return;
      }
      if (e.stage === "done") return closeStage();
      if (e.stage === "error") return closeStage("error", e.message);
      const errors = (e.data?.errors as string[] | undefined) ?? [];
      const detail = errors.length ? `${e.message} — fixing: ${errors.join("; ")}` : e.message;
      // Repair attempts stay inside the same stage; a new stage closes the previous one.
      if (stageStep && stageKey === e.stage) {
        stageStep = { ...stageStep, detail };
        update(sid, upsertStep(aid, stageStep));
        return;
      }
      closeStage();
      const phase: TraceStep["phase"] = e.stage === "compile" ? "build" : e.stage === "apply" ? "validate" : "plan";
      stageT0 = performance.now();
      stageKey = e.stage;
      stageStep = { id: uid(), parent: null, phase, title: STAGE_TITLE[e.stage] ?? cap(e.message), detail, status: "running" };
      update(sid, upsertStep(aid, stageStep));
      update(sid, patchRun(aid, { stage: phase === "build" ? "building" : "planning" }));
    };
    try {
      return await call(onEvent);
    } catch (err) {
      closeStage("error", err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, [update]);

  /** Client-side trace step (download, viewer load) under an assistant message. */
  const clientStep = useCallback((sid: string, aid: string, title: string, detail: string | null = null) => {
    const base: TraceStep = { id: uid(), parent: null, phase: "load", title, detail, status: "running" };
    const t0 = performance.now();
    update(sid, upsertStep(aid, base));
    return {
      update: (d: string) => update(sid, upsertStep(aid, { ...base, detail: d })),
      done: (d?: string) => update(sid, upsertStep(aid, { ...base, detail: d ?? detail, status: "done", ms: Math.round(performance.now() - t0) })),
      fail: (msg: string) => update(sid, upsertStep(aid, { ...base, status: "error", error: msg, ms: Math.round(performance.now() - t0) })),
    };
  }, [update]);

  /** Load a finished version into the viewer, narrated as trace steps. */
  const loadVersion = useCallback(async (sid: string, aid: string, v: api.Version) => {
    ensureTurn(v);
    const name = `v${v.number}.ifc`;
    if (activeRef.current === sid) {
      setTab("model");
      let step = clientStep(sid, aid, "Downloading the IFC", `version ${v.number}`);
      const bytes = await api.fetchBytes(v.ifc_url);
      step.done(`${name} · ${Math.round(bytes.length / 1024)} KB`);
      step = clientStep(sid, aid, "Loading into the 3D viewer", "converting IFC to fragments");
      const load = step;
      let shown = -1;
      const s = await showModel(bytes, name, `${sid}:${name}`, (p) => {
        const pct = Math.round(p * 100);
        if (pct >= shown + 10) { shown = pct; load.update(`converting IFC to fragments · ${pct}%`); }
      });
      step.done(`${s.levels} levels · ${s.elements} elements · ${s.triangles.toLocaleString()} triangles`);
    }
    update(sid, (x) => ({ ...patchRun(aid, { stage: "done", version: v, endedAt: Date.now() })(x), model: { name, url: v.ifc_url } }));
  }, [clientStep, showModel, update]);

  const headOf = (s: Session | undefined) =>
    [...(s?.messages ?? [])].reverse().find((m) => m.run?.version)?.run?.version ?? null;

  const generate = useCallback(async (sid: string, prompt: string) => {
    const aid = uid();
    update(sid, addMessage({ id: uid(), role: "user", text: prompt }));
    update(sid, addMessage({ id: aid, role: "assistant", text: "", run: { stage: "planning", steps: [], startedAt: Date.now() } }));
    setBusy(true);
    try {
      if (!(await api.health())) {
        const wait = clientStep(sid, aid, "Waiting for the backend", "starting Python + IfcOpenShell");
        await api.waitForBackend();
        wait.done();
      }
      const session = sessionsRef.current.find((s) => s.id === sid);
      let projectId = session?.projectId;
      if (!projectId) {
        projectId = (await api.createProject(session?.title ?? "Untitled")).id;
        const pidNew = projectId;
        update(sid, (s) => ({ ...s, projectId: pidNew }));
      }
      const head = headOf(session);
      const pid = projectId;
      const v = await runPipeline(sid, aid, (onEvent) => api.sendPrompt(pid, prompt, head?.number ?? null, onEvent, planner || undefined));
      await loadVersion(sid, aid, v);
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setProgress(null);
      update(sid, patchRun(aid, { stage: "error", error: msg, endedAt: Date.now() }));
      platform.report({ status: "error", error: msg });
      return false;
    } finally {
      setBusy(false);
    }
  }, [clientStep, loadVersion, planner, runPipeline, update]);

  /** Make an older version the head again (recorded as a new version, so nothing is lost). */
  const restore = useCallback(async (sid: string, to: number) => {
    const session = sessionsRef.current.find((s) => s.id === sid);
    if (!session?.projectId) return;
    const aid = uid();
    update(sid, addMessage({ id: aid, role: "assistant", text: `Restoring version ${to}.`,
      run: { stage: "building", steps: [], startedAt: Date.now() } }));
    setBusy(true);
    try {
      const pid = session.projectId;
      const v = await runPipeline(sid, aid, (onEvent) => api.revert(pid, to, onEvent));
      await loadVersion(sid, aid, v);
    } catch (e) {
      update(sid, patchRun(aid, { stage: "error", error: e instanceof Error ? e.message : String(e), endedAt: Date.now() }));
    } finally {
      setBusy(false);
    }
  }, [loadVersion, runPipeline, update]);

  /** Show any version in the main viewer without changing the head. */
  const viewVersion = useCallback(async (sid: string, v: api.Version) => {
    const name = `v${v.number}.ifc`;
    try {
      setTab("model");
      await showModel(await api.fetchBytes(v.ifc_url), name, `${sid}:${name}`);
      update(sid, (s) => ({ ...s, model: { name, url: v.ifc_url } }));
    } catch (e) {
      setProgress(null);
      setLoadError(`Couldn't load version ${v.number}: ${e instanceof Error ? e.message : e}`);
    }
  }, [showModel, update]);

  const startSession = (prompt: string) => {
    const title = prompt.length > 48 ? `${prompt.slice(0, 46).trimEnd()}…` : prompt;
    return generate(create(title), prompt);
  };

  const openSessionWithModel = async (name: string, bytes: Uint8Array, url?: string) => {
    const sid = create(name);
    if (!url) localFiles.current.set(sid, bytes);
    update(sid, addMessage({ id: uid(), role: "assistant", text: `Opened ${name}. Explore it in the viewer, or describe a new building below.` }));
    setTab("model");
    await showModel(bytes, name, `${sid}:${name}`);
    update(sid, (s) => ({ ...s, model: { name, url } }));
  };

  const openFile = async () => {
    try {
      const file = await platform.openIfc();
      if (file) await openSessionWithModel(file.name, file.data);
    } catch (e) {
      setProgress(null);
      setLoadError(String(e instanceof Error ? e.message : e));
    }
  };

  const openSample = async () => {
    try {
      await openSessionWithModel("sample-house.ifc", await api.fetchBytes(SAMPLE_URL), SAMPLE_URL);
    } catch (e) {
      setProgress(null);
      setLoadError(String(e instanceof Error ? e.message : e));
    }
  };

  const toggleRooms = async () => {
    const next = !roomsVisible;
    setRoomsVisible(next);
    await viewerRef.current?.setCategoryVisible("IFCSPACE", next);
    setTreeVersion((n) => n + 1);
  };

  // Smoke-test hooks (BIM_AUTOLOAD / BIM_PROMPT / BIM_SMOKE_SELECT) once everything is up.
  useEffect(() => {
    if (!viewerReady || !options) return;
    platform.report({ status: "viewer-ready" });
    const { autoload, prompt, select, tab: smokeTab, smoke } = options;
    (async () => {
      if (autoload) await openSessionWithModel(autoload.split("/").pop()!, await api.fetchBytes(autoload), autoload);
      else if (prompt) {
        const [first, ...more] = prompt.split(" || ");
        if (!(await startSession(first))) return;
        for (const next of more) {
          const sid = activeRef.current!;
          if (!(await generate(sid, next))) return;
        }
      } else if (smoke && smokeTab === "reset") {
        // Test hygiene: forget sessions created by earlier smoke runs.
        localStorage.removeItem("gbim.sessions.v1");
        return platform.report({ status: "ready", screen: "reset" });
      } else if (smoke) {
        // Home screen: nothing to load.
        await new Promise((r) => setTimeout(r, 800));
        return platform.report({ status: "ready", screen: "home" });
      } else return;
      if (select) await viewerRef.current!.selectFirstOf(select);
      if (smokeTab === "model" || smokeTab === "elements" || smokeTab === "data") setTab(smokeTab);
      if (smokeTab === "levels") setTreeOpen(true);
      if (smokeTab === "trace") (document.querySelector(".reasoning-head") as HTMLElement | null)?.click();
      await new Promise((r) => setTimeout(r, 800));
      platform.report({
        status: "ready",
        model: document.querySelector(".ws-file")?.textContent,
        levels: [...document.querySelectorAll(".lrow.bold")].map((e) => e.textContent),
        rows: document.querySelectorAll(".data-scroll tbody tr").length,
        info: document.querySelector(".info-card")?.textContent?.slice(0, 160),
      });
    })().catch((e) => platform.report({ status: "error", error: String(e) }));
  }, [viewerReady, options]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- layout -------------------------------------------------------------------

  const running = active?.messages.some((m) => m.run && !["done", "error"].includes(m.run.stage));
  const status = loadError
    ?? (progress !== null ? `Loading model… ${Math.round(progress * 100)}%` : null)
    ?? (!loaded && running ? "Generating model…" : null)
    ?? (!loaded && active ? "No model in this session yet." : null);
  const v = viewerRef.current;

  return (
    <IfcViewerProvider runtime={runtime}>
    <div className="app">
      {sidebarOpen && (
        <Sidebar sessions={sessions} activeId={activeId} onSelect={setActiveId} onNew={() => setActiveId(null)}
          onOpenFile={openFile} onSample={openSample} onDelete={remove} onCollapse={() => setSidebarOpen(false)}
          backendUp={backendUp} planners={planners} />
      )}
      <div className="main">
        <TopBar title={active?.title ?? null} sidebarOpen={sidebarOpen} assistantOpen={assistantOpen}
          showAssistantToggle={!!active} onHome={() => setActiveId(null)}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} onToggleAssistant={() => setAssistantOpen(!assistantOpen)}
          onExport={loaded ? () => platform.saveIfc(loaded.name, loaded.bytes) : null}
          onDelete={active ? () => remove(active.id) : null} />
        <div className="content">
          <Workspace hostRef={hostRef} viewer={viewerReady ? v : null}
            fileName={loaded?.name ?? (active?.model?.name ?? null)} schema={loaded?.schema ?? ""}
            status={status} progress={progress} tab={tab} setTab={setTab}
            treeOpen={treeOpen} setTreeOpen={setTreeOpen} treeVersion={treeVersion}
            onClose={() => { if (active) update(active.id, (s) => ({ ...s, model: undefined })); clearModel(); }}
            stats={stats} levels={levels} rows={rows} selectedId={selectedId} selected={selected} properties={properties}
            onSelect={(id) => v?.select(id)}
            onPick={(id) => { setTab("model"); v?.select(id); }}
            onVisible={(ids, vis) => v?.setItemsVisible(ids, vis)}
            roomsVisible={roomsVisible} onRooms={toggleRooms} />
          {active && assistantOpen && (
            <Assistant session={active} busy={busy} planners={planners} planner={planner} setPlanner={setPlanner}
              onSubmit={(t) => generate(active.id, t)} onAttach={openFile}
              viewing={loaded?.key.startsWith(`${active.id}:`) ? loaded.name : null}
              onView={(v) => viewVersion(active.id, v)} onRestore={(n) => restore(active.id, n)} />
          )}
          {!active && (
            <div className="home-layer">
              <Home busy={busy} planners={planners} planner={planner} setPlanner={setPlanner}
                onSubmit={startSession} onAttach={openFile} />
            </div>
          )}
        </div>
      </div>
    </div>
    </IfcViewerProvider>
  );
}

/** Top-level trace titles for the pipeline's stages. */
const STAGE_TITLE: Record<string, string> = {
  program: "Designing the building program",
  edit: "Working out the edit",
  apply: "Applying edit operations",
  solve: "Solving the layout",
  compile: "Compiling the IFC",
};

const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
