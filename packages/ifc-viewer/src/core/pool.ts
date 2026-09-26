/**
 * Fixed-capacity pool of expensive resources (here: WebGL viewports) handed
 * out to keyed borrowers with least-recently-used eviction.
 *
 * Browsers cap live WebGL contexts per page (roughly 8-16), so inline turn
 * cards cannot each own one. Cards borrow a slot while visible; when a new
 * card needs one and the pool is full, the least recently used unpinned
 * borrower is evicted and told to fall back to its snapshot image.
 */
export interface PoolCallbacks<V> {
  create(index: number): V;
  /** Called when a borrower loses its slot, either by eviction or release. */
  onRevoke?(key: string, value: V, reason: "evicted" | "released"): void;
}

interface Slot<V> {
  value: V;
  key: string | null;
  lastUsed: number;
}

export class LruPool<V> {
  private slots: Slot<V>[] = [];
  private pinned = new Set<string>();
  private clock = 0;

  constructor(
    readonly capacity: number,
    private readonly cb: PoolCallbacks<V>,
  ) {
    if (capacity < 1) throw new Error("LruPool capacity must be at least 1");
  }

  /** Keys currently holding a slot, most recently used first. */
  get holders(): string[] {
    return this.slots
      .filter((s) => s.key !== null)
      .sort((a, b) => b.lastUsed - a.lastUsed)
      .map((s) => s.key!);
  }

  get created(): number {
    return this.slots.length;
  }

  holds(key: string): boolean {
    return this.slots.some((s) => s.key === key);
  }

  /**
   * Get a slot for `key`. Reuses the key's existing slot, then a free slot,
   * then creates one if under capacity, then evicts the LRU unpinned holder.
   * Returns null only if every slot is pinned by other keys.
   */
  acquire(key: string): V | null {
    const tick = ++this.clock;
    const own = this.slots.find((s) => s.key === key);
    if (own) {
      own.lastUsed = tick;
      return own.value;
    }
    let slot = this.slots.find((s) => s.key === null);
    if (!slot && this.slots.length < this.capacity) {
      slot = { value: this.cb.create(this.slots.length), key: null, lastUsed: 0 };
      this.slots.push(slot);
    }
    if (!slot) {
      const victims = this.slots
        .filter((s) => s.key !== null && !this.pinned.has(s.key))
        .sort((a, b) => a.lastUsed - b.lastUsed);
      slot = victims[0];
      if (!slot) return null;
      const evicted = slot.key!;
      slot.key = null;
      this.cb.onRevoke?.(evicted, slot.value, "evicted");
    }
    slot.key = key;
    slot.lastUsed = tick;
    return slot.value;
  }

  /** Mark a key as recently used without acquiring. No-op if it holds no slot. */
  touch(key: string): void {
    const own = this.slots.find((s) => s.key === key);
    if (own) own.lastUsed = ++this.clock;
  }

  release(key: string): void {
    const own = this.slots.find((s) => s.key === key);
    this.pinned.delete(key);
    if (!own) return;
    own.key = null;
    this.cb.onRevoke?.(key, own.value, "released");
  }

  /** Pinned keys are never evicted (e.g. the card under the pointer). */
  pin(key: string): void {
    this.pinned.add(key);
  }

  unpin(key: string): void {
    this.pinned.delete(key);
  }

  forEach(fn: (value: V, key: string | null) => void): void {
    for (const s of this.slots) fn(s.value, s.key);
  }

  clear(): void {
    this.pinned.clear();
    this.slots = [];
  }
}
