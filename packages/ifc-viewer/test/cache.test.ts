import { describe, expect, it } from "vitest";
import { FragCache, sha256Hex } from "../src/core/cache";

const bytes = (n: number) => new Uint8Array(n);

describe("sha256Hex", () => {
  it("matches the known digest of 'abc'", async () => {
    expect(await sha256Hex(new TextEncoder().encode("abc"))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
});

describe("FragCache", () => {
  it("evicts least recently used entries to stay within budget", () => {
    const c = new FragCache(100);
    c.set("a", bytes(40));
    c.set("b", bytes(40));
    c.get("a"); // a is now most recent
    c.set("c", bytes(40)); // over budget: evict b
    expect(c.has("a")).toBe(true);
    expect(c.has("b")).toBe(false);
    expect(c.has("c")).toBe(true);
    expect(c.totalBytes).toBe(80);
  });

  it("keeps a single oversized entry rather than thrashing", () => {
    const c = new FragCache(10);
    c.set("big", bytes(50));
    expect(c.has("big")).toBe(true);
    c.set("big2", bytes(50));
    expect(c.has("big")).toBe(false);
    expect(c.has("big2")).toBe(true);
  });

  it("replacing a key updates the byte count", () => {
    const c = new FragCache(100);
    c.set("a", bytes(30));
    c.set("a", bytes(10));
    expect(c.totalBytes).toBe(10);
    expect(c.size).toBe(1);
  });
});
