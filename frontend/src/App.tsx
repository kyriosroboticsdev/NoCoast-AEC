import { useCallback, useEffect, useRef, useState } from "react";
import { IfcViewerProvider } from "@nocoast/ifc-viewer";
import * as api from "./api/client";
import { Assistant } from "./components/Assistant";
import type { DeliverableTab } from "./components/Deliverables";
import { Home } from "./components/Home";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import * as platform from "./platform";
import type { Attachment } from "./state/attachments";
import { describeElement, roomAt, type Design, type Facts } from "./state/design";
import { clearFiles, deleteFile, getFile, keepFilesFor, putFile } from "./state/files";
import { useLayout } from "./state/layout";
import {
  addMessage, linkImages, patchRun, uid, upsertStep, useSessions, type Session, type TraceStep,
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
  /** Set when the model on screen is a stored version, which is what can be exported in full. */
  version?: { project: string; number: number } | null;
}

export default function App() {
  const { sessions, active, activeId, setActiveId, create, update, remove, clear } = useSessions();
  const { size, layout, resize, resetPanel, setFlag } = useLayout();
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
  const [tab, setTab] = useState<DeliverableTab>("model");
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

  // --- chrome ---------------------------------------------------------------
  const [options, setOptions] = useState<platform.LaunchOptions | null>(null);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  // "Planner" = the backend's LLM provider for prompts; defaults to the one it's configured with.
  const [planners, setPlanners] = useState<string[]>([]);
  const [planner, setPlanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Bytes of a file opened from disk, by session id: a memory cache in front of IndexedDB (state/files.ts).
  const localFiles = useRef(new Map<string, Uint8Array>());

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
    opts: { keepCamera?: boolean; label: string; preview: boolean; design?: Design | null; version?: { project: string; number: number } | null },
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
    setShown({ label: opts.label, preview: opts.preview, version: opts.version ?? null });
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
    return showModel(bytes, versionName(v), `${sid}:${versionName(v)}`, {
      keepCamera: inSession(sid), label: versionLabel(v), preview: false, design,
      version: { project: v.project_id, number: v.number },
    });
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
    const sid = active.id;
    (async () => {
      try {
        if (model.url) {
          const ver = versionOf(model.url);
          const design = ver ? await fetchDesign(ver.project, ver.number) : null;
          await showModel(await api.fetchBytes(model.url), model.name, key,
            { label: ver ? `v${ver.number} · final` : model.name, preview: false, design, version: ver });
          return;
        }
        // Opened from disk: this run's bytes, or the copy kept for the session since an earlier run.
        let local = localFiles.current.get(sid);
        if (!local) {
          const stored = await getFile(sid);
          if (stored) {
            local = stored.bytes;
            localFiles.current.set(sid, local);
          }
        }
        if (local) await showModel(local, model.name, key, { label: model.name, preview: false, design: null });
        else {
          clearModel();
          setLoadError(`${model.name} was opened from disk and is no longer available. Open it again to view it.`);
        }
      } catch (e) {
        setLoadError(`Couldn't load ${model.name}: ${e instanceof Error ? e.message : e}`);
      }
    })();
  }, [viewerReady, active?.id, active?.model?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * Take the head of an open session's project from the backend. Versions live there,
   * the session only remembers where it got to, so a run whose result never reached the
   * browser — the app was closed, the window reloaded mid-build — is picked up here
   * instead of leaving the session one version behind for good.
   */
  useEffect(() => {
    const sid = active?.id;
    const pid = active?.project?.id;
    if (!sid || !pid || !backendUp || busy) return;
    let cancelled = false;
    api.getProject(pid).then((detail) => {
      const head = detail.head;
      if (cancelled || !head) return;
      update(sid, (s) => {
        if (s.project?.id !== pid) return s;
        const behind = s.project.head === null || head.number > s.project.head;
        if (!behind && s.model) return s;
        ensureTurn(head);
        return {
          ...s,
          project: { id: pid, head: head.number },
          model: behind || !s.model ? { name: versionName(head), url: head.ifc_url } : s.model,
        };
      });
    }, () => {
      // Offline or a project the backend no longer has: keep showing what the session remembers.
    });
    return () => { cancelled = true; };
  }, [active?.id, active?.project?.id, backendUp, busy, update]);

  // Files opened from disk outlive their session otherwise.
  useEffect(() => {
    void keepFilesFor(sessionsRef.current.map((s) => s.id));
  }, []);

  // --- actions ------------------------------------------------------------------

  /**
   * Run one pipeline call (prompt or revert) for a session as an assistant message with a
   * live trace, then make the resulting version the session's head and show it.
   */
  const execute = useCallback(async (
    sid: string,
    text: string,
    call: (project: NonNullable<Session["project"]>, onEvent: (e: api.StageEvent) => void) => Promise<api.Version>,
    /** The user message whose attachments this run carries; they get the backend's URLs when it lands. */
    attachedTo?: string,
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
      onApproach: (approach) => update(sid, patchRun(aid, { approach })),
      onLive: (drafting) => update(sid, patchRun(aid, { drafting })),
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
      if (attachedTo && version.images?.length) update(sid, linkImages(attachedTo, version.images.map((i) => i.url)));
      ensureTurn(version);

      const name = versionName(version);
      if (forActive()) {
        current = step("Loading the finished model", version.ifc_url);
        const shownNow = await loadVersion(sid, version);
        current.done(`${name} · ${shownNow.levels} storey${shownNow.levels === 1 ? "" : "s"} · ${version.summary.elements} elements`);
        current = null;
      }
      update(sid, (s) => ({ ...patchRun(aid, { stage: "done", drafting: null, endedAt: Date.now() })(s), model: { name, url: version.ifc_url } }));
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (current) current.fail(msg);
      else tracer.fail(msg);
      update(sid, patchRun(aid, { stage: "error", error: msg, drafting: null, endedAt: Date.now() }));
      platform.report({ status: "error", error: msg });
      return false;
    } finally {
      finalArrived = true;
      setBusy(false);
      if (runStarted) sectionRef.current?.finishRun();
    }
  }, [loadVersion, showModel, update]);

  /** First prompt in a session designs a building; later prompts edit its head version — about `target` if one is
   *  selected. Attached images travel with this prompt only; the version keeps them. */
  const generate = useCallback((sid: string, prompt: string, target: { id: string; label: string } | null = null,
                                images: Attachment[] = []) => {
    const mid = uid();
    update(sid, addMessage({
      id: mid, role: "user", text: target ? `${prompt}\n\n↳ ${target.label}` : prompt,
      images: images.map((i) => ({ name: i.name, mediaType: i.mediaType, size: i.size, dataUrl: i.dataUrl })),
    }));
    setFocus(null);
    return execute(sid, "", (project, onEvent) =>
      api.sendPrompt(project.id, prompt, project.head, onEvent, planner ?? undefined, target?.id,
        images.map((i) => ({ name: i.name, media_type: i.mediaType, data: i.data }))), mid);
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

  /**
   * Export what the workspace is showing. A backend version can produce every artefact (bundle,
   * schedule, spec …); a file opened from disk only has its own bytes, so only the IFC is offered.
   */
  const exportShown = useCallback(async (format: api.ExportFormat) => {
    if (!loaded) return null;
    const ver = shown?.version;
    if (!ver) return platform.saveFile(loaded.name, loaded.bytes);
    const name = api.exportName(ver.project, ver.number, format);
    return platform.saveFile(name, await api.fetchExport(ver.project, ver.number, format));
  }, [loaded, shown?.version]);

  const exportDisabled = !loaded ? "Nothing to export yet"
    : shown?.preview ? "Wait for the model to finish, then export the version"
    : null;

  const removeSession = (id: string) => {
    const s = sessionsRef.current.find((x) => x.id === id);
    for (const m of s?.messages ?? []) if (m.run?.version) runtime.removeTurn(turnId(m.run.version));
    localFiles.current.delete(id);
    void deleteFile(id);
    remove(id);
  };

  const startSession = (prompt: string, images: Attachment[] = []) => {
    const title = prompt.length > 48 ? `${prompt.slice(0, 46).trimEnd()}…` : prompt;
    return generate(create(title), prompt, null, images);
  };

  const openSessionWithModel = async (name: string, bytes: Uint8Array, url?: string) => {
    const sid = create(name);
    if (!url) {
      localFiles.current.set(sid, bytes);
      void putFile(sid, name, bytes); // so the session still has its model after a restart
    }
    update(sid, addMessage({ id: uid(), role: "assistant", text: `Opened ${name}. Explore it in the viewer, or describe a new building below.` }));
    const ver = versionOf(url);
    const design = ver ? await fetchDesign(ver.project, ver.number) : null;
    await showModel(bytes, name, `${sid}:${name}`, { label: ver ? `v${ver.number} · final` : name, preview: false, design, version: ver });
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

  /** From a review issue back to the model: the elements it names, highlighted in 3D. */
  const showInModel = (ids: string[]) => {
    setTab("model");
    if (ids.some((id) => id.includes("-space-")) && !roomsVisible) toggleRooms();
    viewerRef.current?.highlight(ids);
  };

  // Previews and files opened from disk have no deliverables; only the model tab makes sense then.
  const viewTab: DeliverableTab = shown?.version && !shown.preview ? tab : "model";

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
        clear();
        await clearFiles();
        return platform.report({ status: "ready", screen: "reset" });
      } else if (smoke) {
        // Home screen: nothing to load, and no restored session in the way.
        setActiveId(null);
        await new Promise((r) => setTimeout(r, 800));
        return platform.report({ status: "ready", screen: "home" });
      } else return;
      if (select) viewerRef.current!.selectFirstOf(select);
      if (smokeTab === "trace") (document.querySelector(".reasoning-head") as HTMLElement | null)?.click();
      if (smokeTab === "drawings" || smokeTab === "review" || smokeTab === "cost") setTab(smokeTab);
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
    // A restored session has a model before the viewer has read it back.
    ?? (!shown && active?.model ? `Loading ${active.model.name}…` : null)
    ?? (!shown && active ? "No model in this session yet." : null);
  const v = viewerRef.current;
  // The selection is only meaningful as prompt context when the workspace shows a version of this session.
  const focusFor = active?.project && loaded?.key.startsWith(`${active.id}:v`) ? focus : null;

  return (
    <IfcViewerProvider runtime={runtime}>
    <div className="app">
      {layout.sidebarOpen && (
        <Sidebar sessions={sessions} activeId={activeId} onSelect={setActiveId} onNew={() => setActiveId(null)}
          onOpenFile={openFile} onSample={openSample} onDelete={removeSession} onCollapse={() => setFlag("sidebarOpen", false)}
          backendUp={backendUp} planners={planners}
          width={size.sidebar} onResize={(w) => resize("sidebar", w)} onResetWidth={() => resetPanel("sidebar")} />
      )}
      <div className="main">
        <TopBar title={active?.title ?? null} sidebarOpen={layout.sidebarOpen} assistantOpen={layout.assistantOpen}
          showAssistantToggle={!!active} onHome={() => setActiveId(null)}
          onToggleSidebar={() => setFlag("sidebarOpen", !layout.sidebarOpen)}
          onToggleAssistant={() => setFlag("assistantOpen", !layout.assistantOpen)}
          onExport={exportShown} exportDisabled={exportDisabled}
          onDelete={active ? () => removeSession(active.id) : null} />
        <div className="content">
          <Workspace hostRef={hostRef} viewer={viewerReady ? v : null}
            tab={viewTab} onTab={setTab} onExport={(f) => void exportShown(f)} onShow={showInModel}
            fileName={loaded?.name ?? (active?.model?.name ?? null)} schema={loaded?.schema ?? ""}
            status={status} shown={shown}
            section={section} onSection={(t) => sectionRef.current?.setValue(t)} onFollow={(on) => sectionRef.current?.setFollow(on)}
            onClose={() => { if (active) update(active.id, (s) => ({ ...s, model: undefined })); clearModel(); }}
            picked={picked} facts={facts} properties={properties} onClearPick={() => v?.clearSelection()}
            roomsVisible={roomsVisible} onRooms={toggleRooms}
            inspector={{ width: size.inspectorW, height: size.inspectorH }}
            onResizeInspector={({ width, height }) => {
              if (width !== undefined) resize("inspectorW", width);
              if (height !== undefined) resize("inspectorH", height);
            }}
            onResetInspector={() => { resetPanel("inspectorW"); resetPanel("inspectorH"); }}
            viewTools={size.viewTools} onResizeViewTools={(w) => resize("viewTools", w)}
            onResetViewTools={() => resetPanel("viewTools")} />
          {active && layout.assistantOpen && (
            <Assistant session={active} busy={busy} planners={planners} planner={planner} setPlanner={setPlanner}
              onSubmit={(t, images) => generate(active.id, t, focusFor, images)} onAttach={openFile}
              focus={focusFor} onClearFocus={() => v?.clearSelection()}
              viewing={loaded?.key ?? null} onView={viewVersion} onRestore={(n) => restore(active.id, n)}
              onOpenTab={setTab}
              width={size.assistant} onResize={(w) => resize("assistant", w)} onResetWidth={() => resetPanel("assistant")}
              cardHeight={size.turnCard} onResizeCard={(h) => resize("turnCard", h)} onResetCard={() => resetPanel("turnCard")} />
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
