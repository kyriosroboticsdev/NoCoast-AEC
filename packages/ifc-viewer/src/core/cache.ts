/** Hex SHA-256 of a byte array, via WebCrypto (browser, worker, and Node 20+). */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * In-memory LRU cache of converted fragments, bounded by total bytes.
 * Keyed by IFC content hash so an unchanged file across turns is never
 * converted twice.
 */
export class FragCache {
  private map = new Map<string, Uint8Array>();
  private bytes = 0;

  constructor(private readonly budget: number) {}

  get size(): number {
    return this.map.size;
  }

  get totalBytes(): number {
    return this.bytes;
  }

  has(key: string): boolean {
    return this.map.has(key);
  }

  get(key: string): Uint8Array | undefined {
    const v = this.map.get(key);
    if (v) {
      // Refresh recency.
      this.map.delete(key);
      this.map.set(key, v);
    }
    return v;
  }

  set(key: string, value: Uint8Array): void {
    const old = this.map.get(key);
    if (old) {
      this.bytes -= old.byteLength;
      this.map.delete(key);
    }
    // An entry larger than the whole budget is still kept alone, because
    // refusing it would force a reconversion on every view.
    this.map.set(key, value);
    this.bytes += value.byteLength;
    for (const [k, v] of this.map) {
      if (this.bytes <= this.budget || this.map.size === 1) break;
      this.map.delete(k);
      this.bytes -= v.byteLength;
    }
  }

  clear(): void {
    this.map.clear();
    this.bytes = 0;
  }
}
