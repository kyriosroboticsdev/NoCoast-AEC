import { describe, expect, it, vi } from "vitest";
import { LruPool } from "../src/core/pool";

function makePool(capacity = 2) {
  let n = 0;
  const onRevoke = vi.fn();
  const pool = new LruPool<{ id: number }>(capacity, { create: () => ({ id: n++ }), onRevoke });
  return { pool, onRevoke };
}

describe("LruPool", () => {
  it("creates lazily up to capacity and reuses a key's own slot", () => {
    const { pool } = makePool(2);
    const a = pool.acquire("a");
    expect(pool.created).toBe(1);
    expect(pool.acquire("a")).toBe(a);
    pool.acquire("b");
    expect(pool.created).toBe(2);
  });

  it("evicts the least recently used holder and notifies it", () => {
    const { pool, onRevoke } = makePool(2);
    const a = pool.acquire("a")!;
    pool.acquire("b");
    pool.touch("a");
    const c = pool.acquire("c")!;
    expect(onRevoke).toHaveBeenCalledWith("b", expect.anything(), "evicted");
    expect(pool.holds("b")).toBe(false);
    expect(pool.holders).toEqual(["c", "a"]);
    expect(c).not.toBe(a);
  });

  it("never evicts pinned holders and returns null when all are pinned", () => {
    const { pool } = makePool(2);
    pool.acquire("a");
    pool.acquire("b");
    pool.pin("a");
    pool.pin("b");
    expect(pool.acquire("c")).toBeNull();
    pool.unpin("a");
    expect(pool.acquire("c")).not.toBeNull();
    expect(pool.holds("a")).toBe(false);
    expect(pool.holds("b")).toBe(true);
  });

  it("release frees the slot for reuse without creating more", () => {
    const { pool, onRevoke } = makePool(1);
    const a = pool.acquire("a");
    pool.release("a");
    expect(onRevoke).toHaveBeenCalledWith("a", a, "released");
    expect(pool.acquire("b")).toBe(a);
    expect(pool.created).toBe(1);
  });

  it("keeps the live slot count bounded under churn", () => {
    const { pool } = makePool(3);
    for (let i = 0; i < 50; i++) pool.acquire(`card-${i}`);
    expect(pool.created).toBe(3);
    expect(pool.holders).toEqual(["card-49", "card-48", "card-47"]);
  });
});
