import { IfcImporter } from "@thatopen/fragments";
import { getConfig, resolvedWasmPath } from "./config";
import type { ConvertRequest, ConvertResponse } from "./convert.worker";

type Pending = {
  resolve: (frag: Uint8Array) => void;
  reject: (e: Error) => void;
  onProgress?: (p: number) => void;
};

/**
 * Converts IFC bytes to fragments bytes. Uses a dedicated worker when
 * possible and falls back to the main thread if the worker cannot start
 * (for example when a host bundler does not emit worker chunks).
 */
export class IfcConverter {
  private worker: Worker | null = null;
  private workerBroken = false;
  private seq = 0;
  private pending = new Map<number, Pending>();

  async convert(bytes: Uint8Array, onProgress?: (p: number) => void): Promise<Uint8Array> {
    if (getConfig().convertInWorker && !this.workerBroken) {
      try {
        return await this.viaWorker(bytes, onProgress);
      } catch (e) {
        if (!(e instanceof WorkerStartError)) throw e;
        console.warn("@nocoast/ifc-viewer: conversion worker unavailable, using main thread.", e.cause);
        this.workerBroken = true;
      }
    }
    return this.onMainThread(bytes, onProgress);
  }

  dispose(): void {
    this.worker?.terminate();
    this.worker = null;
    for (const p of this.pending.values()) p.reject(new Error("Converter disposed"));
    this.pending.clear();
  }

  private async onMainThread(bytes: Uint8Array, onProgress?: (p: number) => void): Promise<Uint8Array> {
    const importer = new IfcImporter();
    importer.wasm = { absolute: true, path: resolvedWasmPath() };
    return importer.process({ bytes, progressCallback: (p: number) => onProgress?.(p) });
  }

  private ensureWorker(): Worker {
    if (this.worker) return this.worker;
    let w: Worker;
    try {
      w = new Worker(new URL("./convert.worker.ts", import.meta.url), { type: "module" });
    } catch (cause) {
      throw new WorkerStartError(cause);
    }
    let started = false;
    w.onmessage = (ev: MessageEvent<ConvertResponse>) => {
      const msg = ev.data;
      if ("ready" in msg) {
        started = true;
        return;
      }
      const p = this.pending.get(msg.id);
      if (!p) return;
      if ("progress" in msg) {
        p.onProgress?.(msg.progress);
        return;
      }
      this.pending.delete(msg.id);
      if (msg.ok) p.resolve(msg.frag);
      else p.reject(new Error(msg.error));
    };
    // An error before the ready handshake means the script never loaded:
    // fall back to the main thread. An error after it is a crash during a
    // conversion (e.g. wasm out of memory): fail that conversion and let the
    // next call spawn a fresh worker, rather than retrying a huge file on
    // the UI thread.
    w.onerror = (ev) => {
      ev.preventDefault();
      const message = ev.message || "worker error";
      const err = started ? new Error(`IFC conversion crashed: ${message}`) : new WorkerStartError(message);
      for (const p of this.pending.values()) p.reject(err);
      this.pending.clear();
      w.terminate();
      if (this.worker === w) this.worker = null;
    };
    this.worker = w;
    return w;
  }

  private viaWorker(bytes: Uint8Array, onProgress?: (p: number) => void): Promise<Uint8Array> {
    const worker = this.ensureWorker();
    const id = ++this.seq;
    return new Promise<Uint8Array>((resolve, reject) => {
      this.pending.set(id, { resolve, reject, onProgress });
      // Copy so the caller's buffer stays usable (it may be cached or re-read).
      const copy = bytes.slice();
      const req: ConvertRequest = { id, bytes: copy, wasmPath: resolvedWasmPath() };
      worker.postMessage(req, [copy.buffer]);
    });
  }
}

class WorkerStartError extends Error {
  constructor(cause: unknown) {
    super("Conversion worker failed to start");
    this.cause = cause;
  }
}
