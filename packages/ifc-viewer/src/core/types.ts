/**
 * One agent turn's IFC output. The host app owns these records; the viewer
 * only reads them and reports back snapshot paths and errors.
 */
export interface TurnRef {
  /** Stable, unique id for the turn (e.g. "turn-7"). */
  id: string;
  /** Where the IFC lives. Opaque to the viewer; passed back to TurnSource.readIfc. */
  ifcPath: string;
  /** ISO timestamp. */
  createdAt: string;
  /** Optional short label shown on the card (e.g. the user's prompt). */
  label?: string;
  /** Set by the viewer once a snapshot PNG has been written via TurnSource.writeSnapshot. */
  pngPath?: string;
}

/**
 * Adapter the host app implements. In Tauri this wraps plugin-fs / invoke /
 * event listeners; in the playground it wraps fetch and an in-memory map.
 */
export interface TurnSource {
  /** Return the raw IFC bytes for a turn. */
  readIfc(turn: TurnRef): Promise<Uint8Array>;
  /**
   * Persist a snapshot PNG for the turn (e.g. next to the IFC so the agent
   * loop can hand it to a vision model). Return the written path, if any.
   */
  writeSnapshot?(turn: TurnRef, png: Uint8Array, meta: SnapshotMeta): Promise<string | void>;
  /** Optional persistent fragments cache, keyed by the IFC content hash. */
  readFrag?(hash: string): Promise<Uint8Array | null>;
  writeFrag?(hash: string, frag: Uint8Array): Promise<void>;
  /** Subscribe to new turns produced by the agent. Returns an unsubscribe fn. */
  onTurnAdded?(cb: (turn: TurnRef) => void): () => void;
}

export type SnapshotView = "iso" | "top" | "front" | "side";

export interface SnapshotOptions {
  width?: number;
  height?: number;
  view?: SnapshotView;
  /** CSS colour for the background. Defaults to white, which vision models read best. */
  background?: string;
}

export interface SnapshotMeta {
  width: number;
  height: number;
  view: SnapshotView;
}

export type TurnStatus = "pending" | "loading" | "ready" | "error";

/** Viewer-side state for a turn, exposed to UIs via TurnStore. */
export interface TurnState {
  turn: TurnRef;
  status: TurnStatus;
  /** Human-readable failure reason when status === "error". */
  error?: string;
  /** IFC schema from the file header, when known. */
  schema?: string;
  /** SHA-256 of the IFC bytes; the fragments cache key. */
  hash?: string;
  /** Object URL for the snapshot PNG, for <img> display. */
  snapshotUrl?: string;
  /** Wall-clock timings in ms, useful for tuning the loop. */
  timings?: { read?: number; convert?: number; snapshot?: number };
  /** Whether the fragments came from cache rather than a fresh conversion. */
  cached?: boolean;
}
