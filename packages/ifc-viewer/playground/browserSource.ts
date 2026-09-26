import type { SnapshotMeta, TurnRef, TurnSource } from "@nocoast/ifc-viewer";

export interface FixtureEntry {
  id: string;
  file: string;
  prompt: string;
  elements: number;
}

/**
 * Playground stand-in for the Tauri adapter: reads IFC over fetch and keeps
 * snapshots and fragments in memory. `emit` plays the role of the agent
 * writing a new turn file.
 */
export class BrowserTurnSource implements TurnSource {
  readonly snapshots = new Map<string, { png: Uint8Array; meta: SnapshotMeta }>();
  readonly frags = new Map<string, Uint8Array>();
  private listeners = new Set<(t: TurnRef) => void>();

  async readIfc(turn: TurnRef): Promise<Uint8Array> {
    const res = await fetch(turn.ifcPath);
    if (!res.ok) throw new Error(`HTTP ${res.status} reading ${turn.ifcPath}`);
    return new Uint8Array(await res.arrayBuffer());
  }

  async writeSnapshot(turn: TurnRef, png: Uint8Array, meta: SnapshotMeta): Promise<string> {
    this.snapshots.set(turn.id, { png, meta });
    return `memory://snapshots/${turn.id}.png`;
  }

  async readFrag(hash: string): Promise<Uint8Array | null> {
    return this.frags.get(hash) ?? null;
  }

  async writeFrag(hash: string, frag: Uint8Array): Promise<void> {
    this.frags.set(hash, frag);
  }

  onTurnAdded(cb: (t: TurnRef) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  emit(turn: TurnRef): void {
    for (const cb of this.listeners) cb(turn);
  }
}
