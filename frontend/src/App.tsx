import { useCallback, useEffect, useRef, useState } from "react";
import { IfcViewerProvider } from "@nocoast/ifc-viewer";
import * as api from "./api/client";
import { Assistant } from "./components/Assistant";
import { ExportDialog } from "./components/ExportDialog";
import { Home } from "./components/Home";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import * as platform from "./platform";
import { describeElement, roomAt, type Design, type Facts } from "./state/design";
import {
  addMessage, patchRun, SESSIONS_KEY, uid, upsertStep, useSessions, type Session, type TraceStep,
} from "./state/sessions";
import { stageTracer, type Preview } from "./state/trace";
import { runtime, toTurn, turnId } from "./turns";
import { LegacyViewer, type Picked, type PropertySet } from "./viewer/LegacyViewer";
import { SectionControl, type SectionView } from "./viewer/section";

const SAMPLE_URL = "samples/sample-house.ifc";

const versionName = (v: api.Version) => `v${v.number}.ifc`;
const versionLabel = (v: api.Version) => `v${v.number} · final · ${v.summary.elements} elements`;

/** Register a version's turn card once (addTurn re-renders an existing turn). */
const ensureTurn = (v: api.Version) => {
  if (!runtime.getTurn(turnId(v))) void runtime.addTurn(toTurn(v));
};

/** Project id and version number behind a backend IFC url, if it is one. */
const versionOf = (url: string | undefined) => {
  const m = url?.match(/\/projects\/([\w-]+)\/versions\/(\d+)\/ifc/);
  return m ? { project: m[1], number: Number(m[2]) } : null;
};

interface Loaded {
  key: string;
  name: string;
  schema: string;
  bytes: Uint8Array;
}

/** What the viewer currently shows: a preview while the model works, or a final version. */
interface Shown {
  label: string;
  preview: boolean;
}

export default function App() {
  const { sessions, active, activeId, setActiveId, create, update, remove } = useSessions();
  const activeRef = useRef(activeId);
  activeRef.current = activeId;
  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;

  // --- viewer ---------------------------------------------------------------
  const hostRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<LegacyViewer | null>(null);
  const sectionRef = useRef<SectionControl | null>(null);
  const [viewerReady, setViewerReady] = useState(false);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const loadedKey = useRef<string | null>(null); // sync copy, avoids double loads
  const [shown, setShown] = useState<Shown | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [section, setSection] = useState<SectionView | null>(null);
  const [roomsVisible, setRoomsVisible] = useState(false);
  // The camera is framed on the first model of a session and then left alone: previews and new versions
  // load into the same view so the building grows in place — unless it clearly outgrows the view.
  const framed = useRef(0);

  // --- selection --------------------------------------------------------------
  // One element at a time. Clicking a wall, door, window, stair or piece of furniture selects it; clicking a
  // floor selects the room under the click. The selection is highlighted, explained in the info card (design
  // facts first, IFC property sets underneath) and sent with the next prompt as `focus`.
  const designRef = useRef<Design | null>(null); // the shown version's design record (null for imports)
  const [picked, setPicked] = useState<Picked | null>(null);
  const [facts, setFacts] = useState<Facts | null>(null);
  const [properties, setProperties] = useState<PropertySet[]>([]);
  const [focus, setFocus] = useState<{ id: string; label: string } | null>(null);
  // IFC components attached to each session's project, and the state of an upload in flight.
  const [components, setComponents] = useState<Record<string, api.ComponentRecord[]>>({});
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadErrors, setUploadErrors] = useState<{ filename: string; error: string }[]>([]);

  // --- chrome ---------------------------------------------------------------
  const [options, setOptions] = useState<platform.LaunchOptions | null>(null);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  // "Planner" = the backend's LLM provider for prompts; defaults to the one it's configured with.
  const [planners, setPlanners] = useState<string[]>([]);
  const [planner, setPlanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [exporting, setExporting] = useState<api.Version | null>(null);
  const localFiles = useRef(new Map<string, Uint8Array>()); // session id → bytes of a file opened from disk

  const onPick = useCallback((p: Picked | null) => {
    const v = viewerRef.current!;
    setPicked(p);
    if (!p) {
      setFocus(null);
      setFacts(null);
      setProperties([]);
      v.highlight(null);
      return;
    }
    let id = p.tag || p.name;
    // A click on a floor slab selects the room under it.
    const slab = id.match(/^(\w+?)-(floor|slab)(-\d+)?$/);
    if (slab) {
      const room = roomAt(designRef.current, slab[1], p.point.x, p.point.y);
      if (room) id = `${slab[1]}-space-${room.id}`;
    }
    const f = describeElement(designRef.current, id);
    setFacts(f);
    setFocus(id ? { id, label: f?.title ?? id } : null);
    v.highlight(id || null);
    v.properties(p.expressID).then(setProperties, () => setProperties([]));
  }, []);

  useEffect(() => {
    if (!hostRef.current || viewerRef.current) return;
    const viewer = new LegacyViewer(hostRef.current);
    viewerRef.current = viewer;
    const sectionCtl = new SectionControl(viewer, setSection);
    sectionRef.current = sectionCtl;
    // Debug / smoke-test handles.
    (window as unknown as { __viewer: LegacyViewer; nocoast: unknown }).__viewer = viewer;
    (window as unknown as { nocoast: unknown }).nocoast = { viewer, section: sectionCtl };
    viewer.onSelect = onPick;
    setViewerReady(true);
    platform.launchOptions().then((o) => {
      api.setBackendUrl(o.backendUrl);
      if (o.planner) setPlanner(o.planner);
      setOptions(o);
    });
  }, [onPick]);

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

  /** Parse and draw. With `keepCamera` the change is animated in place (fade in/out of what changed). */
  const loadIntoViewer = useCallback(async (bytes: Uint8Array, keepCamera: boolean) => {
    const v = viewerRef.current!;
    await v.loadIfc(bytes, undefined, undefined, keepCamera);
    const extent = v.extent();
    if (!keepCamera) framed.current = extent;
    else if (extent > framed.current * 1.4) { framed.current = extent; v.fit(); } // a lone first preview is not the building
    const s = sectionRef.current!;
    s.refresh(); // the section cut survives reloads; the range follows the new model's extent
    s.applyFollow();
  }, []);

  const showModel = useCallback(async (
    bytes: Uint8Array, name: string, key: string,
    opts: { keepCamera?: boolean; label: string; preview: boolean; design?: Design | null },
  ) => {
    const v = viewerRef.current!;
    loadedKey.current = key;
    setLoadError(null);
    if (opts.design !== undefined) designRef.current = opts.design;
    if (!opts.preview) v.clearSelection();
    await loadIntoViewer(bytes, !!opts.keepCamera);
    const head = new TextDecoder().decode(bytes.subarray(0, 4000));
    const schema = head.match(/FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'/i)?.[1] ?? "";
    setLoaded({ key, name, schema, bytes });
    setShown({ label: opts.label, preview: opts.preview });
    return { levels: v.storeys().length };
  }, [loadIntoViewer]);

  const clearModel = useCallback(() => {
    loadedKey.current = null;
    designRef.current = null;
    setLoaded(null);
    setShown(null);
    viewerRef.current?.clear();
    sectionRef.current?.refresh();
  }, []);

  const fetchDesign = async (project: string, number: number): Promise<Design | null> => {
    try {
      return (await api.getSpec(project, number)).design;
    } catch {
      return null; // imports and old versions have no design record; the inspector then shows IFC data only
    }
  };

  /** Whether the viewer currently shows something of this session (then the camera is kept across loads). */
  const inSession = (sid: string) => activeRef.current === sid && !!loadedKey.current?.startsWith(`${sid}:`);

  const loadVersion = useCallback(async (sid: string, v: api.Version) => {
    const design = await fetchDesign(v.project_id, v.number);
    const bytes = await api.fetchBytes(v.ifc_url);
    return showModel(bytes, versionName(v), `${sid}:${versionName(v)}`, { keepCamera: inSession(sid), label: versionLabel(v), preview: false, design });
  }, [showModel]);

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
        if (model.url) {
          const ver = versionOf(model.url);
          const design = ver ? await fetchDesign(ver.project, ver.number) : null;
          await showModel(await api.fetchBytes(model.url), model.name, key, { label: ver ? `v${ver.number} · final` : model.name, preview: false, design });
        } else if (local) await showModel(local, model.name, key, { label: model.name, preview: false, design: null });
        else {
          clearModel();
          setLoadError(`${model.name} was opened from disk in an earlier run. Open it again to view it.`);
        }
      } catch (e) {
        setLoadError(`Couldn't load ${model.name}: ${e instanceof Error ? e.message : e}`);
      }
    })();
  }, [viewerReady, active?.id, active?.model?.name]); // eslint-disable-line react-hooks/exhaustive-deps

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
    // A session created for this prompt becomes active on the next render, so "is this the session on
    // screen" is decided when events arrive, not now.
    const forActive = () => activeRef.current === sid;
    let runStarted = false;
    const ensureRun = () => {
      if (runStarted || !forActive()) return;
      runStarted = true;
      sectionRef.current?.startRun();
    };

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

    // Previews stream in while the model works (`partial` events carry a geometry-checked IFC of what
    // exists so far). Loads are serialised, only the newest pending preview is loaded, nothing is loaded
    // once the final version has arrived, and the camera is kept so the building grows in place.
    let finalArrived = false;
    let pending: Preview | null = null;
    let chain = Promise.resolve();
    const queuePreview = (p: Preview) => {
      pending = p;
      chain = chain.then(async () => {
        const next = pending;
        pending = null;
        if (!next || finalArrived || !forActive()) return;
        ensureRun();
        try {
          const bytes = await api.fetchBytes(next.url);
          if (finalArrived || !forActive()) return;
          await showModel(bytes, "preview.ifc", `${sid}:preview`, { keepCamera: inSession(sid), label: next.label.toLowerCase(), preview: true });
        } catch {
          // A preview is best effort: the final version replaces it anyway.
        }
      });
    };
    const tracer = stageTracer((s) => update(sid, upsertStep(aid, s)), {
      onPreview: queuePreview,
      // Follow build: the section cut tracks the storey the accepted steps are working on.
      onStep: (st, ok) => { ensureRun(); if (ok && forActive()) sectionRef.current?.learnStep(st); },
    });

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
        if (e.stage === "build" || e.stage === "step" || e.stage === "compile" || e.stage === "apply" || e.stage === "solve") {
          update(sid, patchRun(aid, { stage: "building" }));
        }
      });
      finalArrived = true;
      await chain; // let an in-flight preview finish before the final model replaces it
      update(sid, (s) => ({
        ...patchRun(aid, { version, stage: "loading" })(s),
        project: { id: version.project_id, head: version.number },
      }));
      ensureTurn(version);

      const name = versionName(version);
      if (forActive()) {
        current = step("Loading the finished model", version.ifc_url);
        const shownNow = await loadVersion(sid, version);
        current.done(`${name} · ${shownNow.levels} storey${shownNow.levels === 1 ? "" : "s"} · ${version.summary.elements} elements`);
        current = null;
      }
      update(sid, (s) => ({ ...patchRun(aid, { stage: "done", endedAt: Date.now() })(s), model: { name, url: version.ifc_url } }));
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (current) current.fail(msg);
      else tracer.fail(msg);
      update(sid, patchRun(aid, { stage: "error", error: msg, endedAt: Date.now() }));
      platform.report({ status: "error", error: msg });
      return false;
    } finally {
      finalArrived = true;
      setBusy(false);
      if (runStarted) sectionRef.current?.finishRun();
    }
  }, [loadVersion, showModel, update]);

  /** First prompt in a session designs a building; later prompts edit its head version — about `target` if one is selected. */
  const generate = useCallback((sid: string, prompt: string, target: { id: string; label: string } | null = null) => {
    update(sid, addMessage({ id: uid(), role: "user", text: target ? `${prompt}\n\n↳ ${target.label}` : prompt }));
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
      await loadVersion(active.id, v);
    } catch (e) {
      setLoadError(`Couldn't load ${versionName(v)}: ${e instanceof Error ? e.message : e}`);
    }
  }, [active, loadVersion]);

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
    const ver = versionOf(url);
    const design = ver ? await fetchDesign(ver.project, ver.number) : null;
    await showModel(bytes, name, `${sid}:${name}`, { label: ver ? `v${ver.number} · final` : name, preview: false, design });
    update(sid, (s) => ({ ...s, model: { name, url } }));
  };

  const openFile = async () => {
    try {
      const file = await platform.openIfc();
      if (file) await openSessionWithModel(file.name, file.data);
    } catch (e) {
      setLoadError(String(e instanceof Error ? e.message : e));
    }
  };

  const openSample = async () => {
    try {
      await openSessionWithModel("sample-house.ifc", await api.fetchBytes(SAMPLE_URL), SAMPLE_URL);
    } catch (e) {
      setLoadError(String(e instanceof Error ? e.message : e));
    }
  };

  const toggleRooms = () => {
    const next = !roomsVisible;
    setRoomsVisible(next);
    viewerRef.current?.setRoomsVisible(next);
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
      if (select) viewerRef.current!.selectFirstOf(select);
      if (smokeTab === "trace") (document.querySelector(".reasoning-head") as HTMLElement | null)?.click();
      await new Promise((r) => setTimeout(r, 800));
      platform.report({
        status: "ready",
        model: document.querySelector(".file-tab span")?.textContent,
        info: document.querySelector(".info-card")?.textContent?.slice(0, 160),
      });
    })().catch((e) => platform.report({ status: "error", error: String(e) }));
  }, [viewerReady, options]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- layout -------------------------------------------------------------------

  const running = active?.messages.some((m) => m.run && !["done", "error"].includes(m.run.stage));
  const status = loadError
    ?? (!shown && running ? "Generating model… the first preview appears after the first room." : null)
    ?? (!shown && active ? "No model in this session yet." : null);
  const v = viewerRef.current;
  // The selection is only meaningful as prompt context when the workspace shows a version of this session.
  const focusFor = active?.project && loaded?.key.startsWith(`${active.id}:v`) ? focus : null;

  // The version shown in the workspace, when it is one of this session's project versions (not a file
  // opened from disk). Export then goes through the validated, stamped export; otherwise it saves as is.
  const shownNumber = Number(loaded?.name.match(/^v(\d+)\.ifc$/)?.[1] ?? NaN);
  const shownVersion = active?.project && loaded?.key.startsWith(`${active.id}:`)
    ? active.messages.map((m) => m.run?.version).find((ver) => ver?.number === shownNumber) ?? null
    : null;
  const onExport = shown?.preview ? null // nothing to export while a live preview is on screen
    : shownVersion ? () => setExporting(shownVersion)
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
            status={status} shown={shown}
            section={section} onSection={(t) => sectionRef.current?.setValue(t)} onFollow={(on) => sectionRef.current?.setFollow(on)}
            onClose={() => { if (active) update(active.id, (s) => ({ ...s, model: undefined })); clearModel(); }}
            picked={picked} facts={facts} properties={properties} onClearPick={() => v?.clearSelection()}
            roomsVisible={roomsVisible} onRooms={toggleRooms} />
          {active && assistantOpen && (
            <Assistant session={active} busy={busy} planners={planners} planner={planner} setPlanner={setPlanner}
              onSubmit={(t) => generate(active.id, t, focusFor)} onAttach={openFile}
              components={components[active.id] ?? []}
              onAttachComponents={() => void attachComponents(active.id)}
              onRemoveComponent={(cid) => void removeComponent(active.id, cid)}
              uploading={uploading} uploadErrors={uploadErrors} onDismissErrors={() => setUploadErrors([])}
              focus={focusFor} onClearFocus={() => v?.clearSelection()}
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
