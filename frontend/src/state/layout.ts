// Panel geometry: how wide the sidebar and the assistant are, how big the floating
// inspector and view palette are, how tall a version's turn card renders, and which
// side panels are open. Persisted in localStorage, so the window reopens in the
// layout it was dragged into.
import { useCallback, useEffect, useMemo, useState } from "react";

export const LAYOUT_KEY = "gbim.layout.v1";

/** Sizes in CSS pixels. */
export interface Layout {
  sidebar: number;
  assistant: number;
  inspectorW: number;
  inspectorH: number;
  viewTools: number;
  turnCard: number;
  sidebarOpen: boolean;
  assistantOpen: boolean;
}

export type PanelSize = "sidebar" | "assistant" | "inspectorW" | "inspectorH" | "viewTools" | "turnCard";
export type PanelFlag = "sidebarOpen" | "assistantOpen";

export const DEFAULT_LAYOUT: Layout = {
  sidebar: 272,
  assistant: 440,
  inspectorW: 330,
  inspectorH: 380,
  viewTools: 172,
  turnCard: 170,
  sidebarOpen: true,
  assistantOpen: true,
};

/** What a panel may be dragged to, regardless of the window size. */
export const PANEL_RANGE: Record<PanelSize, { min: number; max: number }> = {
  sidebar: { min: 200, max: 560 },
  assistant: { min: 320, max: 820 },
  inspectorW: { min: 240, max: 640 },
  inspectorH: { min: 160, max: 1000 },
  viewTools: { min: 140, max: 360 },
  turnCard: { min: 110, max: 560 },
};

/** The 3D view never shrinks below this: the side panels give way first. */
const MIN_VIEWPORT = 340;

const fit = (n: number, min: number, max: number) => Math.max(min, Math.min(Math.max(min, max), Math.round(n)));

/** Sizes as rendered: the stored width a user dragged, capped to what this window can show. */
export type PanelSizes = Record<PanelSize, number>;

function forWindow(l: Layout, vw: number, vh: number): PanelSizes {
  const r = PANEL_RANGE;
  const room = vw - MIN_VIEWPORT;
  let sidebar = fit(l.sidebar, r.sidebar.min, Math.min(r.sidebar.max, room));
  const assistant = fit(l.assistant, r.assistant.min, Math.min(r.assistant.max, room - (l.sidebarOpen ? sidebar : 0)));
  // Both at their minimum can still be too much for a narrow window; the sidebar gives way first.
  const over = (l.sidebarOpen ? sidebar : 0) + (l.assistantOpen ? assistant : 0) - room;
  if (over > 0 && l.sidebarOpen) sidebar = Math.max(r.sidebar.min, sidebar - over);
  const free = vw - (l.sidebarOpen ? sidebar : 0) - (l.assistantOpen ? assistant : 0);
  // The panels floating over the model never cover more than about half of it.
  const floating = free * 0.6;
  return {
    sidebar,
    assistant,
    inspectorW: fit(l.inspectorW, r.inspectorW.min, Math.min(r.inspectorW.max, floating)),
    inspectorH: fit(l.inspectorH, r.inspectorH.min, Math.min(r.inspectorH.max, vh - 230)),
    viewTools: fit(l.viewTools, r.viewTools.min, Math.min(r.viewTools.max, floating)),
    turnCard: fit(l.turnCard, r.turnCard.min, Math.min(r.turnCard.max, vh - 200)),
  };
}

function load(): Layout {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    const stored = raw ? (JSON.parse(raw) as Partial<Layout>) : {};
    const l = { ...DEFAULT_LAYOUT };
    for (const key of Object.keys(PANEL_RANGE) as PanelSize[]) {
      const v = stored[key];
      if (typeof v === "number" && Number.isFinite(v)) l[key] = fit(v, PANEL_RANGE[key].min, PANEL_RANGE[key].max);
    }
    for (const key of ["sidebarOpen", "assistantOpen"] as PanelFlag[]) {
      if (typeof stored[key] === "boolean") l[key] = stored[key];
    }
    return l;
  } catch {
    return { ...DEFAULT_LAYOUT };
  }
}

/**
 * Panel sizes with their drag handles' setters. `size` is what to render (clamped to
 * the window); `layout` is what the user asked for and what is stored, so shrinking a
 * window and growing it again gives the panels back.
 */
export function useLayout() {
  const [layout, setLayout] = useState<Layout>(load);
  const [view, setView] = useState(() => ({ w: window.innerWidth, h: window.innerHeight }));

  useEffect(() => {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    } catch {
      /* storage unavailable — the layout just won't outlive the window */
    }
  }, [layout]);

  useEffect(() => {
    const onResize = () => setView({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const resize = useCallback((key: PanelSize, value: number) => {
    setLayout((l) => {
      const next = fit(value, PANEL_RANGE[key].min, PANEL_RANGE[key].max);
      return next === l[key] ? l : { ...l, [key]: next };
    });
  }, []);

  const resetPanel = useCallback((key: PanelSize) => {
    setLayout((l) => ({ ...l, [key]: DEFAULT_LAYOUT[key] }));
  }, []);

  const setFlag = useCallback((key: PanelFlag, value: boolean) => {
    setLayout((l) => (l[key] === value ? l : { ...l, [key]: value }));
  }, []);

  const size = useMemo(() => forWindow(layout, view.w, view.h), [layout, view]);
  return { layout, size, resize, resetPanel, setFlag };
}
