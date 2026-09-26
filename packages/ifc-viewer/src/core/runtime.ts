import { FragCache, sha256Hex } from "./cache";
import { configureIfcViewer, getConfig, type IfcViewerConfig } from "./config";
import { IfcConverter } from "./convert";
import { LruPool } from "./pool";
import { preflightIfc } from "./preflight";
import type { SnapshotMeta, SnapshotOptions, TurnRef, TurnSource, TurnState } from "./types";
import { IfcViewport } from "./viewport";

type Listener = () => void;
type RevokeHandler = () => void;

/**
 * Orchestrates the per-turn pipeline and owns all GPU resources:
 *
 *   read IFC -> preflight -> hash -> fragments (cache or convert)
 *            -> snapshot on a dedicated offscreen viewport -> writeSnapshot
 *
 * UIs subscribe to turn state and borrow pooled live viewports for inline
 * cards. One runtime per app window.
 */
export class IfcViewerRuntime {
  readonly pool: LruPool<IfcViewport>;
  private readonly cache: FragCache;
  private readonly converter = new IfcConverter();
  private readonly states = new Map<string, TurnState>();
  private order: string[] = [];
  private snapshotCache: TurnState[] = [];
  private listeners = new Set<Listener>();
  private revokers = new Map<string, RevokeHandler>();
  private snapshotter: IfcViewport | null = null;
  private queue: Promise<unknown> = Promise.resolve();
  private fragInflight = new Map<string, Promise<Uint8Array>>();
  /**
   * Generation per turn id. Re-adding or removing a turn bumps it, so work
   * started for an older version can tell it is stale and drop its results.
   */
  private gens = new Map<string, number>();
  private genSeq = 0;
  private unsubscribeSource: (() => void) | null = null;
  private disposed = false;

  constructor(
    readonly source: TurnSource,
    config: Partial<IfcViewerConfig> = {},
  ) {
    const cfg = configureIfcViewer(config);
    this.cache = new FragCache(cfg.cacheBytes);
    this.pool = new LruPool<IfcViewport>(cfg.poolSize, {
      create: () => new IfcViewport({ interactive: true }),
      onRevoke: (key, viewport, reason) => {
        viewport.unmount();
        if (reason === "evicted") this.revokers.get(key)?.();
        this.revokers.delete(key);
      },
    });
  }

  /** Begin listening for new turns from the source, if it supports it. */
  start(): this {
    if (!this.unsubscribeSource && this.source.onTurnAdded) {
      this.unsubscribeSource = this.source.onTurnAdded((t) => this.addTurn(t));
    }
    return this;
  }

  // ------------------------------------------------------------ state

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Stable array reference until something changes (for useSyncExternalStore). */
  getTurns(): TurnState[] {
    return this.snapshotCache;
  }

  getTurn(id: string): TurnState | undefined {
    return this.states.get(id);
  }

  private patch(id: string, patch: Partial<TurnState>): void {
    const prev = this.states.get(id);
    if (!prev) return;
    this.states.set(id, { ...prev, ...patch });
    this.snapshotCache = this.order.map((k) => this.states.get(k)!);
    for (const l of this.listeners) l();
  }

  /**
   * Register a turn and process it in the background. Re-adding an existing
   * id reprocesses it (useful when the agent overwrites a file in place).
   */
  addTurn(turn: TurnRef): Promise<TurnState | undefined> {
    if (this.disposed) return Promise.reject(new Error("Runtime disposed"));
    const existing = this.states.get(turn.id);
    if (existing?.snapshotUrl) URL.revokeObjectURL(existing.snapshotUrl);
    if (!existing) this.order = [...this.order, turn.id];
    const gen = ++this.genSeq;
    this.gens.set(turn.id, gen);
    this.states.set(turn.id, { turn, status: "pending" });
    this.patch(turn.id, {});
    const job = this.queue.then(() => this.process(turn.id, gen));
    this.queue = job.catch(() => undefined);
    return job;
  }

  removeTurn(id: string): void {
    const s = this.states.get(id);
    if (!s) return;
    if (s.snapshotUrl) URL.revokeObjectURL(s.snapshotUrl);
    this.gens.delete(id);
    this.states.delete(id);
    this.order = this.order.filter((k) => k !== id);
    this.snapshotCache = this.order.map((k) => this.states.get(k)!);
    for (const l of this.listeners) l();
  }

  // ------------------------------------------------------------ pipeline

  private isCurrent(id: string, gen: number): boolean {
    return !this.disposed && this.gens.get(id) === gen;
  }

  /** Patch only if `gen` is still the turn's live generation. */
  private patchIf(id: string, gen: number, patch: Partial<TurnState>): void {
    if (this.isCurrent(id, gen)) this.patch(id, patch);
  }

  private async process(id: string, gen: number): Promise<TurnState | undefined> {
    const turn = this.states.get(id)?.turn;
    if (!turn || !this.isCurrent(id, gen)) return this.states.get(id);
    this.patch(id, { status: "loading", error: undefined });
    try {
      const frag = await this.getFrag(id);
      if (!this.isCurrent(id, gen)) return this.states.get(id);
      const t0 = performance.now();
      const { png, meta } = await this.renderSnapshot(frag, {});
      const snapshotMs = performance.now() - t0;
      if (!this.isCurrent(id, gen)) return this.states.get(id);
      let pngPath: string | undefined;
      if (this.source.writeSnapshot) {
        pngPath = (await this.source.writeSnapshot(turn, png, meta)) ?? undefined;
      }
      // Re-check after every await: the turn may have been re-added or removed.
      if (!this.isCurrent(id, gen)) return this.states.get(id);
      const url = URL.createObjectURL(new Blob([png as BlobPart], { type: "image/png" }));
      const prev = this.states.get(id)!;
      this.patch(id, {
        status: "ready",
        snapshotUrl: url,
        turn: pngPath ? { ...turn, pngPath } : turn,
        timings: { ...prev.timings, snapshot: Math.round(snapshotMs) },
      });
    } catch (e) {
      this.patchIf(id, gen, { status: "error", error: String((e as Error)?.message ?? e) });
    }
    return this.states.get(id);
  }

  /**
   * Fragments bytes for the turn's current version: memory cache, then the
   * source's persistent cache, then a fresh conversion. Concurrent callers
   * for the same version share one conversion.
   */
  getFrag(id: string): Promise<Uint8Array> {
    const gen = this.gens.get(id);
    if (gen === undefined) return Promise.reject(new Error(`Unknown turn ${id}`));
    const key = `${id}#${gen}`;
    const inflight = this.fragInflight.get(key);
    if (inflight) return inflight;
    const p = this.loadFrag(id, gen).finally(() => this.fragInflight.delete(key));
    this.fragInflight.set(key, p);
    return p;
  }

  private async loadFrag(id: string, gen: number): Promise<Uint8Array> {
    const state = this.states.get(id);
    if (!state) throw new Error(`Unknown turn ${id}`);
    if (state.hash) {
      const hit = this.cache.get(state.hash);
      if (hit) return hit;
    }
    const t0 = performance.now();
    const bytes = await this.source.readIfc(state.turn);
    const readMs = performance.now() - t0;
    const pre = preflightIfc(bytes);
    if (!pre.ok) {
      this.patchIf(id, gen, { schema: pre.schema });
      throw new Error(pre.error);
    }
    const hash = await sha256Hex(bytes);
    this.patchIf(id, gen, { schema: pre.schema, hash });

    let frag = this.cache.get(hash);
    let cached = !!frag;
    if (!frag && this.source.readFrag) {
      frag = (await this.source.readFrag(hash)) ?? undefined;
      cached = !!frag;
    }
    const t1 = performance.now();
    if (!frag) {
      frag = await this.converter.convert(bytes);
      void this.source.writeFrag?.(hash, frag).catch((e) =>
        console.warn("@nocoast/ifc-viewer: writeFrag failed", e),
      );
    }
    this.cache.set(hash, frag);
    this.patchIf(id, gen, {
      cached,
      timings: { read: Math.round(readMs), convert: cached ? 0 : Math.round(performance.now() - t1) },
    });
    return frag;
  }

  // ------------------------------------------------------------ snapshots

  private ensureSnapshotter(): IfcViewport {
    // A job queued before dispose() must not create a context nobody frees.
    if (this.disposed) throw new Error("Runtime disposed");
    if (this.snapshotter) return this.snapshotter;
    const v = new IfcViewport({ interactive: false });
    const { width, height } = getConfig().snapshot;
    Object.assign(v.host.style, {
      position: "fixed",
      left: "-20000px",
      top: "0",
      width: `${width}px`,
      height: `${height}px`,
      pointerEvents: "none",
    });
    v.host.setAttribute("aria-hidden", "true");
    v.world.renderer!.three.setPixelRatio(1);
    document.body.appendChild(v.host);
    v.resize();
    this.snapshotter = v;
    return v;
  }

  private async renderSnapshot(frag: Uint8Array, opts: SnapshotOptions): Promise<{ png: Uint8Array; meta: SnapshotMeta }> {
    const cfg = getConfig().snapshot;
    const width = opts.width ?? cfg.width;
    const height = opts.height ?? cfg.height;
    const view = opts.view ?? "iso";
    const v = this.ensureSnapshotter();
    if (v.host.clientWidth !== width || v.host.clientHeight !== height) {
      v.host.style.width = `${width}px`;
      v.host.style.height = `${height}px`;
      v.resize();
    }
    // The viewport reloads whenever the bytes differ, so an overwritten
    // turn never snapshots the previous model.
    await v.show("snapshot", frag, view);
    if (!v.modelBox()) throw new Error("Model has no renderable geometry.");
    await v.frame(view, false);
    const png = await v.capturePng(opts.background ?? "#ffffff");
    return { png, meta: { width, height, view } };
  }

  /**
   * On-demand snapshot for the agent loop, e.g. several views of one turn
   * for a vision model. Serialised with background processing.
   */
  captureSnapshot(id: string, opts: SnapshotOptions = {}): Promise<Uint8Array> {
    if (this.disposed) return Promise.reject(new Error("Runtime disposed"));
    const job = this.queue.then(async () => {
      const frag = await this.getFrag(id);
      return (await this.renderSnapshot(frag, opts)).png;
    });
    this.queue = job.catch(() => undefined);
    return job;
  }

  // ------------------------------------------------------------ live viewports

  /**
   * Borrow a live viewport for `cardKey`. `onRevoke` fires if the viewport
   * is later evicted for another card; the card should show its snapshot.
   */
  acquireViewport(cardKey: string, onRevoke: RevokeHandler): IfcViewport | null {
    const v = this.pool.acquire(cardKey);
    if (v) this.revokers.set(cardKey, onRevoke);
    return v;
  }

  releaseViewport(cardKey: string): void {
    this.pool.release(cardKey);
  }

  // ------------------------------------------------------------ lifecycle

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.unsubscribeSource?.();
    this.pool.forEach((v) => v.dispose());
    this.pool.clear();
    this.snapshotter?.dispose();
    this.converter.dispose();
    this.cache.clear();
    this.gens.clear();
    for (const s of this.states.values()) if (s.snapshotUrl) URL.revokeObjectURL(s.snapshotUrl);
    this.listeners.clear();
  }
}
