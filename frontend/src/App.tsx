import { useCallback, useEffect, useRef, useState } from "react";
import { IfcViewerProvider } from "@nocoast/ifc-viewer";
import * as api from "./api/client";
import { Assistant } from "./components/Assistant";
import { ExportDialog } from "./components/ExportDialog";
import { Home } from "./components/Home";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Workspace, type Tab } from "./components/Workspace";
import * as platform from "./platform";
import {
  addMessage, patchRun, SESSIONS_KEY, uid, upsertStep, useSessions, type Session, type TraceStep,
} from "./state/sessions";
import { stageTracer, type Preview } from "./state/trace";
import { runtime, toTurn, turnId } from "./turns";
import {
  BimViewer, type ElementRow, type ElementSummary, type LevelNode, type ModelStats, type PropertyGroup,
} from "./viewer/BimViewer";

const SAMPLE_URL = "samples/sample-house.ifc";

const versionName = (v: api.Version) => `v${v.number}.ifc`;

/** Register a version's turn card once (addTurn re-renders an existing turn). */
const ensureTurn = (v: api.Version) => {
  if (!runtime.getTurn(turnId(v))) void runtime.addTurn(toTurn(v));
};

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
  // "Planner" = the backend's LLM provider for prompts; defaults to the one it's configured with.
  const [planners, setPlanners] = useState<string[]>([]);
  const [planner, setPlanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [treeOpen, setTreeOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("model");
  const [exporting, setExporting] = useState<api.Version | null>(null);
  // Viewer selection sent with the next prompt as `focus` ("add a window" → on the selected wall).
  const [focus, setFocus] = useState<{ id: string; label: string } | null>(null);
  // IFC components attached to each session's project, and the state of an upload in flight.
  const [components, setComponents] = useState<Record<string, api.ComponentRecord[]>>({});
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadErrors, setUploadErrors] = useState<{ filename: string; error: string }[]>([]);
  const localFiles = useRef(new Map<string, Uint8Array>()); // session id → bytes of a file opened from disk

  useEffect(() => {
    if (!hostRef.current || viewerRef.current) return;
    const viewer = new BimViewer();
    viewerRef.current = viewer;
    (window as unknown as { __viewer: BimViewer }).__viewer = viewer; // debug / smoke-test handle
    viewer.setCategoryVisible("IFCSPACE", false); // room volumes hide the building
    viewer.onSelect = async (sel) => {
      setSelectedId(sel?.localId ?? null);
      const summary = sel ? await viewer.elementSummary(sel.localId) : null;
      setSelected(summary);
      setFocus(summary?.specId ? { id: summary.specId, label: `${summary.name} · ${summary.category}${summary.level ? ` · ${summary.level}` : ""}` } : null);
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
          const { provider, providers } = i.llm;
          setPlanners([provider, ...providers.filter((p) => p !== provider)]);
          setPlanner((p) => p ?? provider);
        }
      }
      timer = setTimeout(check, seen ? 4000 : 1000);
    };
    check();
    return () => clearTimeout(timer);
  }, [options]);

  // --- loading models into the viewer -----------------------------------------

  const showModel = useCallback(async (
    bytes: Uint8Array, name: string, key: string, onProgress?: (p: number) => void, opts: { keepCamera?: boolean } = {},
  ) => {
    const v = viewerRef.current!;
    loadedKey.current = key;
    setLoadError(null);
    setProgress(0);
    setSelectedId(null);
    setSelected(null);
    setProperties([]);
    setStats(null);
    setRows(null);
    await v.loadIfc(bytes, name, (p) => { setProgress(p); onProgress?.(p); }, opts);
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

  // Switching sessions loads that session's model and registers its version turn cards.
  useEffect(() => {
    if (!viewerReady) return;
    for (const m of active?.messages ?? []) if (m.run?.version) ensureTurn(m.run.version);
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
   * Run one pipeline call (prompt or revert) for a session as an assistant message with a
   * live trace, then make the resulting version the session's head and show it.
   */
  const execute = useCallback(async (
    sid: string,
    text: string,
    call: (project: NonNullable<Session["project"]>, onEvent: (e: api.StageEvent) => void) => Promise<api.Version>,
  ) => {
    const aid = uid();
    update(sid, addMessage({ id: aid, role: "assistant", text, run: { stage: "planning", steps: [], startedAt: Date.now() } }));
    setBusy(true);

    // Client-side steps join the backend's trace so the user sees the whole journey.
    const step = (title: string, detail: string | null = null) => {
      const base: TraceStep = { id: uid(), parent: null, phase: "load", title, detail, status: "running" };
      const t0 = performance.now();
      update(sid, upsertStep(aid, base));
      return {
        update: (d: string) => update(sid, upsertStep(aid, { ...base, detail: d })),
        done: (d?: string) => update(sid, upsertStep(aid, { ...base, detail: d ?? detail, status: "done", ms: Math.round(performance.now() - t0) })),
        fail: (msg: string) => update(sid, upsertStep(aid, { ...base, status: "error", error: msg, ms: Math.round(performance.now() - t0) })),
      };
    };
    // Previews stream in while the model works: load only the newest pending one, never after the
    // final version arrived, and keep the camera so the building grows in place.
    let finalArrived = false;
    let pending: Preview | null = null;
    let chain = Promise.resolve();
    const inSession = () => activeRef.current === sid && !!loadedKey.current?.startsWith(`${sid}:`);
    // The camera follows growth but not small changes: re-frame only when the model's extent clearly
    // outgrows what was last framed (the first preview can be a single column).
    const diag = (e: [number, number, number]) => Math.hypot(...e);
    let framed = 0;
    const growFrame = async (s: { extent: [number, number, number] }) => {
      const d = diag(s.extent);
      if (d > framed * 1.4) {
        framed = d;
        await viewerRef.current?.fit();
      }
    };
    const queuePreview = (p: Preview) => {
      pending = p;
      chain = chain.then(async () => {
        const next = pending;
        pending = null;
        if (!next || finalArrived || activeRef.current !== sid) return;
        try {
          const s = await showModel(await api.fetchBytes(next.url), `${next.label}.ifc`, `${sid}:preview`, undefined, { keepCamera: true });
          await growFrame(s);
        } catch {
          // A preview is best effort: the final version replaces it anyway.
        }
      });
    };
    const tracer = stageTracer((s) => update(sid, upsertStep(aid, s)), { onPreview: queuePreview });

    let current: ReturnType<typeof step> | null = null;
    try {
      if (!(await api.health())) {
        current = step("Waiting for the backend", "starting Python + IfcOpenShell");
        await api.waitForBackend();
        current.done();
        current = null;
      }

      let project = sessionsRef.current.find((s) => s.id === sid)?.project;
      if (!project) {
        const title = sessionsRef.current.find((s) => s.id === sid)?.title ?? "Untitled";
        project = { id: (await api.createProject(title)).id, head: null };
        const created = project;
        update(sid, (s) => ({ ...s, project: created }));
      }

      const version = await call(project, (e) => {
        tracer.event(e);
        if (e.stage === "apply" || e.stage === "solve" || e.stage === "compile") update(sid, patchRun(aid, { stage: "building" }));
      });
      finalArrived = true;
      await chain; // let an in-flight preview finish before the final model replaces it
      update(sid, (s) => ({
        ...patchRun(aid, { version, stage: "loading" })(s),
        project: { id: version.project_id, head: version.number },
      }));
      ensureTurn(version);

      const name = versionName(version);
      if (activeRef.current === sid) {
        setTab("model");
        current = step("Downloading the IFC", version.ifc_url);
        const bytes = await api.fetchBytes(version.ifc_url);
        current.done(`${name} · ${Math.round(bytes.length / 1024)} KB`);

        current = step("Loading into the 3D viewer", "converting IFC to fragments");
        const load = current;
        let shown = -1;
        const loaded = await showModel(bytes, name, `${sid}:${name}`, (p) => {
          const pct = Math.round(p * 100);
          if (pct >= shown + 10) { shown = pct; load.update(`converting IFC to fragments · ${pct}%`); }
        }, { keepCamera: inSession() });
        if (framed > 0) await growFrame(loaded);
        current.done(`${loaded.levels} levels · ${loaded.elements} elements · ${loaded.triangles.toLocaleString()} triangles`);
        current = null;
      }
      update(sid, (s) => ({ ...patchRun(aid, { stage: "done", endedAt: Date.now() })(s), model: { name, url: version.ifc_url } }));
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (current) current.fail(msg);
      else tracer.fail(msg);
      setProgress(null);
      update(sid, patchRun(aid, { stage: "error", error: msg, endedAt: Date.now() }));
      platform.report({ status: "error", error: msg });
      return false;
    } finally {
      setBusy(false);
    }
  }, [showModel, update]);

  /** First prompt in a session designs a building; later prompts edit its head version. */
  const generate = useCallback((sid: string, prompt: string, target: { id: string; label: string } | null = null) => {
    update(sid, addMessage({ id: uid(), role: "user", text: target ? `${prompt}

↳ ${target.label}` : prompt }));
    setFocus(null);
    return execute(sid, "", (project, onEvent) =>
      api.sendPrompt(project.id, prompt, project.head, onEvent, planner ?? undefined, target?.id));
  }, [execute, planner, update]);

  /** Make an older version the head again (recorded as a new version). */
  const restore = useCallback((sid: string, number: number) =>
    execute(sid, `Restoring version ${number}.`, (project, onEvent) => api.revert(project.id, number, onEvent)),
  [execute]);

  /** Show any version of the active session in the workspace without changing the head. */
  const viewVersion = useCallback(async (v: api.Version) => {
    if (!active) return;
    try {
      setTab("model");
      await showModel(await api.fetchBytes(v.ifc_url), versionName(v), `${active.id}:${versionName(v)}`);
    } catch (e) {
      setProgress(null);
      setLoadError(`Couldn't load ${versionName(v)}: ${e instanceof Error ? e.message : e}`);
    }
  }, [active, showModel]);

  /** The session's backend project, created on first use (a prompt or an attachment). */
  const ensureProject = useCallback(async (sid: string) => {
    const existing = sessionsRef.current.find((s) => s.id === sid)?.project;
    if (existing) return existing;
    await api.waitForBackend();
    const title = sessionsRef.current.find((s) => s.id === sid)?.title ?? "Untitled";
    const project = { id: (await api.createProject(title)).id, head: null };
    update(sid, (s) => ({ ...s, project }));
    return project;
  }, [update]);

  // The active session's attached components (they live on the backend, per project).
  const activeProject = active?.project?.id;
  useEffect(() => {
    if (!active || !activeProject || !backendUp) return;
    const sid = active.id;
    api.listComponents(activeProject).then((list) => setComponents((c) => ({ ...c, [sid]: list })), () => {});
  }, [activeProject, backendUp]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Attach one or more IFC files as components; from Home this starts a session for them. */
  const attachComponents = async (sid: string | null) => {
    const files = await platform.openIfcs();
    if (!files.length) return;
    const id = sid ?? create(files.length === 1 ? files[0].name.replace(/\.ifc$/i, "") : `${files.length} components`);
    setUploadErrors([]);
    setUploading(`Uploading ${files.length} file${files.length === 1 ? "" : "s"}…`);
    try {
      const project = await ensureProject(id);
      const res = await api.uploadComponents(project.id, files);
      setComponents((c) => ({ ...c, [id]: [...(c[id] ?? []), ...res.added] }));
      setUploadErrors(res.errors);
      if (res.added.length) {
        const names = res.added.map((c) => c.name).join(", ");
        const example = res.added[0].name;
        update(id, addMessage({
          id: uid(), role: "assistant",
          text: `Attached ${names}. Ask me to place ${res.added.length === 1 ? "it" : "them"}, for example "place the ${example} in the kitchen", or describe a building that uses ${res.added.length === 1 ? "it" : "them"}.`,
        }));
      }
    } catch (e) {
      setUploadErrors([{ filename: files.map((f) => f.name).join(", "), error: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setUploading(null);
    }
  };

  const removeComponent = async (sid: string, componentId: string) => {
    const project = sessionsRef.current.find((s) => s.id === sid)?.project;
    if (!project) return;
    try {
      await api.deleteComponent(project.id, componentId);
      setComponents((c) => ({ ...c, [sid]: (c[sid] ?? []).filter((x) => x.id !== componentId) }));
    } catch (e) {
      setUploadErrors([{ filename: componentId, error: e instanceof Error ? e.message : String(e) }]);
    }
  };

  const removeSession = (id: string) => {
    const s = sessionsRef.current.find((x) => x.id === id);
    for (const m of s?.messages ?? []) if (m.run?.version) runtime.removeTurn(turnId(m.run.version));
    remove(id);
  };

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
        if (!(await startSession(prompt))) return;
      } else if (smoke && smokeTab === "reset") {
        // Test hygiene: forget sessions created by earlier smoke runs.
        localStorage.removeItem(SESSIONS_KEY);
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

  // The version shown in the workspace, when it is one of this session's project versions (not a file
  // opened from disk). Export then goes through the validated, stamped export; otherwise it saves as is.
  const shownNumber = Number(loaded?.name.match(/^v(\d+)\.ifc$/)?.[1] ?? NaN);
  const shownVersion = active?.project && loaded?.key.startsWith(`${active.id}:`)
    ? active.messages.map((m) => m.run?.version).find((ver) => ver?.number === shownNumber) ?? null
    : null;
  const onExport = shownVersion
    ? () => setExporting(shownVersion)
    : loaded ? () => platform.saveIfc(loaded.name, loaded.bytes) : null;

  return (
    <IfcViewerProvider runtime={runtime}>
    <div className="app">
      {sidebarOpen && (
        <Sidebar sessions={sessions} activeId={activeId} onSelect={setActiveId} onNew={() => setActiveId(null)}
          onOpenFile={openFile} onSample={openSample} onDelete={removeSession} onCollapse={() => setSidebarOpen(false)}
          backendUp={backendUp} planners={planners} />
      )}
      <div className="main">
        <TopBar title={active?.title ?? null} sidebarOpen={sidebarOpen} assistantOpen={assistantOpen}
          showAssistantToggle={!!active} onHome={() => setActiveId(null)}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} onToggleAssistant={() => setAssistantOpen(!assistantOpen)}
          onExport={onExport}
          onDelete={active ? () => removeSession(active.id) : null} />
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
              onSubmit={(t) => generate(active.id, t, active.project && loaded?.key.startsWith(`${active.id}:v`) ? focus : null)}
              onAttach={openFile}
              components={components[active.id] ?? []}
              onAttachComponents={() => void attachComponents(active.id)}
              onRemoveComponent={(cid) => void removeComponent(active.id, cid)}
              uploading={uploading} uploadErrors={uploadErrors} onDismissErrors={() => setUploadErrors([])}
              focus={active.project && loaded?.key.startsWith(`${active.id}:v`) ? focus : null}
              onClearFocus={() => { setFocus(null); void v?.clearSelection(); }}
              viewing={loaded?.key ?? null} onView={viewVersion} onRestore={(n) => restore(active.id, n)} />
          )}
          {!active && (
            <div className="home-layer">
              <Home busy={busy} planners={planners} planner={planner} setPlanner={setPlanner}
                onSubmit={startSession} onAttach={openFile} onAttachComponents={() => void attachComponents(null)}
                uploading={uploading} uploadErrors={uploadErrors} onDismissErrors={() => setUploadErrors([])} />
            </div>
          )}
        </div>
      </div>
      {exporting && (
        <ExportDialog projectId={exporting.project_id} version={exporting} onClose={() => setExporting(null)} />
      )}
    </div>
    </IfcViewerProvider>
  );
}
