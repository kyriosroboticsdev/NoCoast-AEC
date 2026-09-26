/**
 * Runtime asset locations. A desktop app must serve these locally so the
 * viewer works offline; nothing is fetched from a CDN.
 *
 * Vite / Tauri example:
 *   import fragmentsWorkerUrl from "@thatopen/fragments/worker?url";
 *   configureIfcViewer({ wasmPath: "/wasm/", fragmentsWorkerUrl });
 * and copy node_modules/web-ifc/web-ifc.wasm into public/wasm/.
 */
export interface IfcViewerConfig {
  /** Directory URL containing web-ifc.wasm, with trailing slash. */
  wasmPath: string;
  /** Whether wasmPath is absolute (true) or relative to the current page (false). */
  wasmPathAbsolute: boolean;
  /** URL of the @thatopen/fragments worker script. */
  fragmentsWorkerUrl: string | null;
  /**
   * Run IFC-to-fragments conversion in a dedicated worker so the UI stays
   * responsive. Falls back to the main thread if the worker fails to start.
   */
  convertInWorker: boolean;
  /** Maximum simultaneously live inline viewers (WebGL contexts). */
  poolSize: number;
  /** In-memory fragments cache budget in bytes. */
  cacheBytes: number;
  /** Default snapshot settings. */
  snapshot: { width: number; height: number };
}

const defaults: IfcViewerConfig = {
  wasmPath: "/wasm/",
  wasmPathAbsolute: false,
  fragmentsWorkerUrl: null,
  convertInWorker: true,
  poolSize: 3,
  cacheBytes: 256 * 1024 * 1024,
  snapshot: { width: 1024, height: 768 },
};

let current: IfcViewerConfig = { ...defaults };

export function configureIfcViewer(patch: Partial<IfcViewerConfig>): IfcViewerConfig {
  current = {
    ...current,
    ...patch,
    snapshot: { ...current.snapshot, ...patch.snapshot },
  };
  if (!current.wasmPath.endsWith("/")) current.wasmPath += "/";
  return current;
}

export function getConfig(): Readonly<IfcViewerConfig> {
  return current;
}

/** Absolute URL for the wasm directory, resolved against the page when relative. */
export function resolvedWasmPath(): string {
  const { wasmPath, wasmPathAbsolute } = current;
  if (wasmPathAbsolute || typeof location === "undefined") return wasmPath;
  return new URL(wasmPath, location.href).href;
}

export function requireWorkerUrl(): string {
  const url = current.fragmentsWorkerUrl;
  if (!url) {
    throw new Error(
      "@nocoast/ifc-viewer: fragmentsWorkerUrl is not configured. " +
        'Call configureIfcViewer({ fragmentsWorkerUrl }) with `import url from "@thatopen/fragments/worker?url"`.',
    );
  }
  return url;
}
