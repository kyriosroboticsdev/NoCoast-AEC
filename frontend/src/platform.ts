// Desktop integration. Inside Tauri this uses native dialogs and Rust commands;
// in a plain browser (e.g. `npm run vite:dev`) it falls back to web equivalents.
import { invoke, isTauri } from "@tauri-apps/api/core";
import { open, save } from "@tauri-apps/plugin-dialog";

export const isDesktop = isTauri();

export interface LaunchOptions {
  backendUrl: string;
  /** smoke-test hooks */
  autoload: string | null;
  prompt: string | null;
  select: string | null;
  tab: string | null;
  smoke: boolean;
  /** LLM provider to preselect (`?planner=mock` for smoke tests). */
  planner: string | null;
}

const DEFAULT_BACKEND = "http://127.0.0.1:8765";
const IFC_FILTER = [{ name: "IFC", extensions: ["ifc"] }];

export async function launchOptions(): Promise<LaunchOptions> {
  if (isDesktop) {
    const o = await invoke<{
      backend_url: string; autoload: string | null; prompt: string | null; select: string | null; tab: string | null; smoke: boolean;
    }>("launch_options");
    return { backendUrl: o.backend_url, autoload: o.autoload, prompt: o.prompt, select: o.select, tab: o.tab, smoke: o.smoke, planner: null };
  }
  const q = new URLSearchParams(location.search);
  return {
    backendUrl: q.get("backend") ?? DEFAULT_BACKEND,
    autoload: q.get("autoload"),
    prompt: q.get("prompt"),
    select: q.get("select"),
    tab: q.get("tab"),
    smoke: q.has("smoke"),
    planner: q.get("planner"),
  };
}

/** Pick several IFC files at once (component attachments). Returns [] when cancelled. */
export async function openIfcs(): Promise<{ name: string; data: Uint8Array }[]> {
  if (isDesktop) {
    const picked = await open({ filters: IFC_FILTER, multiple: true, directory: false });
    const paths = Array.isArray(picked) ? picked : picked ? [picked] : [];
    return Promise.all(paths.map(async (path) => ({
      name: path.split(/[\\/]/).pop()!,
      data: new Uint8Array(await invoke<ArrayBuffer>("read_ifc", { path })),
    })));
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".ifc";
    input.multiple = true;
    input.onchange = async () => {
      const files = [...(input.files ?? [])];
      resolve(await Promise.all(files.map(async (f) => ({ name: f.name, data: new Uint8Array(await f.arrayBuffer()) }))));
    };
    input.click();
  });
}

export async function openIfc(): Promise<{ name: string; data: Uint8Array } | null> {
  if (isDesktop) {
    const path = await open({ filters: IFC_FILTER, multiple: false, directory: false });
    if (!path) return null;
    const buffer = await invoke<ArrayBuffer>("read_ifc", { path });
    return { name: path.split(/[\\/]/).pop()!, data: new Uint8Array(buffer) };
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".ifc";
    input.onchange = async () => {
      const f = input.files?.[0];
      resolve(f ? { name: f.name, data: new Uint8Array(await f.arrayBuffer()) } : null);
    };
    input.click();
  });
}

export const saveIfc = (name: string, data: Uint8Array) => saveFile(name, data, "ifc");

/** Save bytes through the native dialog (desktop) or a download (browser). Returns the path/name, or null if cancelled. */
export async function saveFile(name: string, data: Uint8Array, kind: "ifc" | "zip"): Promise<string | null> {
  if (isDesktop) {
    const filters = kind === "zip" ? [{ name: "Export bundle", extensions: ["zip"] }] : IFC_FILTER;
    const path = await save({ defaultPath: name, filters });
    if (!path) return null;
    await invoke("write_ifc", data, { headers: { path } });
    return path;
  }
  const url = URL.createObjectURL(new Blob([data as BlobPart], { type: "application/octet-stream" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
  return name;
}

declare global {
  interface Window {
    __bim?: Record<string, unknown>;
  }
}

/** Publish app state for the smoke test (window.__bim, and stdout/file via Rust). */
export function report(state: Record<string, unknown>) {
  window.__bim = state;
  if (isDesktop) invoke("smoke_report", { state }).catch(() => {});
}
