/// <reference lib="webworker" />
// Dedicated worker that converts IFC bytes to fragments so parsing large
// files never blocks the UI thread.
import { IfcImporter } from "@thatopen/fragments";

export interface ConvertRequest {
  id: number;
  bytes: Uint8Array;
  wasmPath: string;
}

export type ConvertResponse =
  | { ready: true }
  | { id: number; ok: true; frag: Uint8Array }
  | { id: number; ok: false; error: string }
  | { id: number; progress: number };

const scope = self as unknown as DedicatedWorkerGlobalScope;

// Handshake: once this arrives, the script and its imports loaded fine, so
// any later worker error is a conversion failure, not a start failure.
scope.postMessage({ ready: true } satisfies ConvertResponse);

scope.onmessage = async (ev: MessageEvent<ConvertRequest>) => {
  const { id, bytes, wasmPath } = ev.data;
  try {
    const importer = new IfcImporter();
    importer.wasm = { absolute: true, path: wasmPath };
    const frag = await importer.process({
      bytes,
      progressCallback: (progress: number) => scope.postMessage({ id, progress } satisfies ConvertResponse),
    });
    scope.postMessage({ id, ok: true, frag } satisfies ConvertResponse, [frag.buffer as ArrayBuffer]);
  } catch (e) {
    scope.postMessage({ id, ok: false, error: String((e as Error)?.message ?? e) } satisfies ConvertResponse);
  }
};
