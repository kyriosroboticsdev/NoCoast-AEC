#!/usr/bin/env node
// End-to-end check of the playground in a real browser (installed Chrome or
// Edge, headless). Builds the playground, serves it, drives the simulated
// agent loop, and asserts on rendering, snapshots, pooling, and inspection.
// Screenshots and snapshot PNGs land in test-results/ for eyeballing.
//
// Usage: node scripts/e2e.mjs [--headed]
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build, preview } from "vite";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const out = join(root, "test-results");
mkdirSync(out, { recursive: true });
const headed = process.argv.includes("--headed");

const BROWSERS = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);
const executablePath = BROWSERS.find((p) => existsSync(p));
if (!executablePath) throw new Error("No Chrome/Edge found; set CHROME_PATH.");

const configFile = join(root, "playground", "vite.config.ts");
await build({ configFile, logLevel: "warn" });
const server = await preview({ configFile, logLevel: "warn" });
const url = server.resolvedUrls.local[0];

const browser = await chromium.launch({
  executablePath,
  headless: !headed,
  args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const consoleErrors = [];
page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(`${m.text()} [${m.location()?.url ?? "?"}]`);
});
page.on("pageerror", (e) => consoleErrors.push(`${e}\n${e.stack ?? ""}`));
page.on("response", (r) => {
  if (r.status() >= 400) consoleErrors.push(`HTTP ${r.status()} ${r.url()}`);
});

const results = [];
async function step(name, fn) {
  const t0 = Date.now();
  try {
    const detail = await fn();
    results.push({ name, ok: true, ms: Date.now() - t0, detail });
    console.log(`PASS ${name} (${Date.now() - t0} ms)${detail ? ` ${JSON.stringify(detail)}` : ""}`);
  } catch (e) {
    results.push({ name, ok: false, ms: Date.now() - t0, error: String(e?.message ?? e) });
    console.log(`FAIL ${name}: ${e?.message ?? e}`);
    await page.screenshot({ path: join(out, `fail-${name.replace(/\W+/g, "_")}.png`) }).catch(() => {});
  }
}
const assert = (cond, msg) => {
  if (!cond) throw new Error(msg);
};
const statuses = () => page.evaluate(() => window.__ncv.runtime.getTurns().map((t) => ({ id: t.turn.id, status: t.status, error: t.error, timings: t.timings, cached: t.cached })));
async function waitSettled(count, timeout = 60_000) {
  await page.waitForFunction(
    (n) => {
      const ts = window.__ncv.runtime.getTurns();
      return ts.length >= n && ts.every((t) => t.status === "ready" || t.status === "error");
    },
    count,
    { timeout, polling: 100 },
  );
}

try {
  await page.goto(url);
  await page.waitForFunction(() => !!window.__ncv, null, { timeout: 30_000 });
  await page.locator(".pg-app").waitFor({ timeout: 10_000 }).catch(() => {
    throw new Error(`App did not mount.\n${consoleErrors.join("\n")}`);
  });

  await step("five agent turns render and snapshot", async () => {
    await page.evaluate(() => {
      for (let i = 0; i < 5; i++) window.__ncv.next();
    });
    await waitSettled(5);
    const s = await statuses();
    assert(s.every((t) => t.status === "ready"), `not all ready: ${JSON.stringify(s)}`);
    const snaps = await page.evaluate(() =>
      [...window.__ncv.source.snapshots.entries()].map(([id, { png, meta }]) => {
        let bin = "";
        for (let i = 0; i < png.length; i += 0x8000) bin += String.fromCharCode(...png.subarray(i, i + 0x8000));
        return { id, meta, b64: btoa(bin) };
      }),
    );
    assert(snaps.length === 5, `expected 5 snapshots, got ${snaps.length}`);
    const sizes = {};
    for (const snap of snaps) {
      const buf = Buffer.from(snap.b64, "base64");
      writeFileSync(join(out, `${snap.id}.png`), buf);
      sizes[snap.id] = buf.length;
      assert(buf.subarray(1, 4).toString() === "PNG", `${snap.id} is not a PNG`);
      assert(snap.meta.width === 1024 && snap.meta.height === 768, `${snap.id} wrong size`);
    }
    // A snapshot of real geometry is far larger than a blank frame.
    assert(Object.values(sizes).every((n) => n > 15_000), `suspiciously small snapshots: ${JSON.stringify(sizes)}`);
    return { sizes, timings: s.map((t) => t.timings) };
  });

  await step("snapshot pixels show geometry, not a blank frame", async () => {
    const stats = await page.evaluate(async () => {
      const [, { png }] = [...window.__ncv.source.snapshots.entries()].at(-1);
      const bmp = await createImageBitmap(new Blob([png], { type: "image/png" }));
      const c = new OffscreenCanvas(bmp.width, bmp.height);
      const ctx = c.getContext("2d");
      ctx.drawImage(bmp, 0, 0);
      const { data } = ctx.getImageData(0, 0, bmp.width, bmp.height);
      let nonWhite = 0;
      for (let i = 0; i < data.length; i += 4) if (data[i] < 235 || data[i + 1] < 235 || data[i + 2] < 235) nonWhite++;
      return { nonWhiteRatio: nonWhite / (data.length / 4) };
    });
    assert(stats.nonWhiteRatio > 0.05, `only ${(stats.nonWhiteRatio * 100).toFixed(1)}% of pixels are non-background`);
    return stats;
  });

  await step("snapshots are complete: a re-capture is pixel-identical", async () => {
    // If a capture fired while geometry was still streaming, a later capture
    // of the same turn would contain more elements and differ.
    const r = await page.evaluate(async () => {
      const out = {};
      for (const id of ["turn-2", "turn-4", "turn-5"]) {
        const first = window.__ncv.source.snapshots.get(id).png;
        const again = await window.__ncv.runtime.captureSnapshot(id);
        const same = first.length === again.length && first.every((b, i) => b === again[i]);
        out[id] = { same, first: first.length, again: again.length };
      }
      return out;
    });
    for (const [id, v] of Object.entries(r)) assert(v.same, `${id} snapshot changed on re-capture: ${JSON.stringify(v)}`);
    return r;
  });

  await step("truncated IFC is reported as an error, not half-rendered", async () => {
    await page.evaluate(() => window.__ncv.broken());
    await waitSettled(6);
    const s = (await statuses()).at(-1);
    assert(s.status === "error" && /truncated/i.test(s.error ?? ""), `unexpected: ${JSON.stringify(s)}`);
    await page.locator(".ncv-card[data-status=error]").first().waitFor();
    return { error: s.error };
  });

  await step("hovering an older card makes it live and orbitable", async () => {
    const card = page.locator('.ncv-card[data-turn="turn-2"]');
    await card.scrollIntoViewIfNeeded();
    await card.hover();
    await page.waitForSelector('.ncv-card[data-turn="turn-2"][data-live]', { timeout: 15_000 });
    await page.waitForTimeout(500);
    const box = await card.boundingBox();
    const before = await card.screenshot();
    // A live card must show the model, not an empty stage.
    const live = await page.evaluate(async () => {
      const c = document.querySelector('.ncv-card[data-turn="turn-2"] canvas');
      return { w: c?.width ?? 0, h: c?.height ?? 0 };
    });
    assert(live.w > 100 && live.h > 100, `live canvas has no size: ${JSON.stringify(live)}`);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 20, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(600);
    const after = await card.screenshot();
    writeFileSync(join(out, "card-before-orbit.png"), before);
    writeFileSync(join(out, "card-after-orbit.png"), after);
    assert(!before.equals(after), "orbit drag did not change the rendered card");
  });

  await step("inspector: click selects an element and shows its property set", async () => {
    await page.locator('.ncv-card[data-turn="turn-5"] button', { hasText: "Inspect" }).click();
    await page.waitForFunction(() => document.querySelector(".ncv-inspector")?.getAttribute("data-turn") === "turn-5");
    await page.waitForTimeout(1500);
    const stage = page.locator(".ncv-insp-stage canvas");
    const box = await stage.boundingBox();
    // Scan a coarse grid until the raycast hits something.
    let name = null;
    outer: for (const fy of [0.5, 0.45, 0.55, 0.4, 0.6]) {
      for (const fx of [0.5, 0.45, 0.55, 0.4, 0.6]) {
        await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
        await page.waitForTimeout(400);
        const title = await page.locator(".ncv-el-title").textContent().catch(() => null);
        if (title) {
          name = title;
          break outer;
        }
      }
    }
    assert(name, "no element was selected by clicking the model");
    const props = await page.locator('[data-testid="ncv-properties"]').textContent();
    assert(/NoCoast_Agent/.test(props) && /AgentTurn/.test(props), `property set missing: ${props.slice(0, 200)}`);
    await page.locator(".ncv-inspector").screenshot({ path: join(out, "inspector-selected.png") });
    return { selected: name.trim() };
  });

  await step("inspector: levels and categories list and toggle", async () => {
    await page.getByRole("tab", { name: "Levels & categories" }).click();
    const text = await page.locator('[data-testid="ncv-structure"]').textContent();
    for (const needle of ["Level 0", "Level 1", "Level 2", "IFCWALL", "IFCSLAB", "IFCCOLUMN"]) {
      assert(text.includes(needle), `missing group ${needle}`);
    }
    const stage = page.locator(".ncv-insp-stage");
    const before = await stage.screenshot();
    await page.locator(".ncv-group", { hasText: "Level 1" }).locator("input").uncheck();
    await page.waitForTimeout(800);
    const after = await stage.screenshot();
    writeFileSync(join(out, "inspector-level1-hidden.png"), after);
    assert(!before.equals(after), "hiding Level 1 did not change the render");
    await page.locator(".ncv-group", { hasText: "Level 1" }).locator("input").check();
  });

  await step("inspector: section plane cuts the model", async () => {
    const stage = page.locator(".ncv-insp-stage");
    await page.locator(".ncv-inspector button", { hasText: "Iso" }).click();
    await page.waitForTimeout(1200);
    const before = await stage.screenshot();
    await page.locator(".ncv-section input[type=checkbox]").check();
    await page.waitForTimeout(800);
    const after = await stage.screenshot();
    writeFileSync(join(out, "inspector-section.png"), after);
    assert(!before.equals(after), "section did not change the render");
    await page.locator(".ncv-section input[type=checkbox]").uncheck();
  });

  await step("overwriting a turn in place re-renders the new model", async () => {
    const r = await page.evaluate(async () => {
      const rt = window.__ncv.runtime;
      const src = window.__ncv.source;
      const before = rt.getTurn("turn-1");
      const oldPng = src.snapshots.get("turn-1").png.length;
      const base = { ...before.turn, createdAt: new Date().toISOString() };
      // Two overwrites back to back: only the last may win.
      const a = rt.addTurn({ ...base, ifcPath: "/fixtures/turn-3.ifc" });
      const b = rt.addTurn({ ...base, ifcPath: "/fixtures/turn-5.ifc" });
      await Promise.all([a, b]);
      const after = rt.getTurn("turn-1");
      const turn5Hash = rt.getTurn("turn-5").hash;
      return {
        status: after.status,
        sameHashAsTurn5: after.hash === turn5Hash,
        hashChanged: after.hash !== before.hash,
        oldPng,
        newPng: src.snapshots.get("turn-1").png.length,
        turn5Png: src.snapshots.get("turn-5").png.length,
      };
    });
    assert(r.status === "ready", `status ${r.status}`);
    assert(r.hashChanged && r.sameHashAsTurn5, `turn-1 does not carry turn-5 content: ${JSON.stringify(r)}`);
    // Same content and same framing give an identical PNG to turn-5's.
    assert(r.newPng === r.turn5Png && r.newPng !== r.oldPng, `snapshot not refreshed: ${JSON.stringify(r)}`);
    // The inspector showing turn-1 must also switch to the new model.
    await page.locator('.ncv-card[data-turn="turn-1"] button', { hasText: "Inspect" }).click();
    await page.waitForFunction(() => document.querySelector(".ncv-inspector")?.getAttribute("data-turn") === "turn-1");
    await page.getByRole("tab", { name: "Levels & categories" }).click();
    await page.waitForFunction(() => /IFCWINDOW/.test(document.querySelector('[data-testid="ncv-structure"]')?.textContent ?? ""), null, { timeout: 15_000 });
    return r;
  });

  await step("20 more turns: live WebGL canvases stay within the pool", async () => {
    await page.evaluate(() => window.__ncv.stress(20));
    await waitSettled(26, 120_000);
    const s = await statuses();
    const bad = s.filter((t) => t.id !== "turn-6" && t.status !== "ready");
    assert(bad.length === 0, `failed turns: ${JSON.stringify(bad)}`);
    const cached = s.filter((t) => t.cached).length;
    let maxLive = 0;
    const cards = page.locator(".ncv-card");
    const n = await cards.count();
    for (let i = 0; i < n; i += 2) {
      const c = cards.nth(i);
      await c.scrollIntoViewIfNeeded();
      await c.hover();
      await page.waitForTimeout(120);
      maxLive = Math.max(maxLive, await page.evaluate(() => window.__ncv.liveCanvases()));
    }
    const pool = await page.evaluate(() => window.__ncv.runtime.pool.created);
    assert(maxLive <= 3, `saw ${maxLive} live card canvases`);
    assert(pool <= 3, `pool created ${pool} viewports`);
    // The 20 stress turns reuse the 5 fixture files, so all should hit the cache.
    assert(cached >= 20, `expected >= 20 cache hits, got ${cached}`);
    // Re-entry: an evicted older card goes live again from the fragments cache.
    const target = page.locator('.ncv-card[data-turn="turn-3"]');
    await target.scrollIntoViewIfNeeded();
    await page.mouse.move(0, 0);
    const t0 = Date.now();
    await target.hover();
    const reentry = await page
      .waitForSelector('.ncv-card[data-turn="turn-3"][data-live]', { timeout: 10_000 })
      .then(() => Date.now() - t0)
      .catch(() => -1);
    assert(reentry >= 0, "card did not go live again within 10 s");
    return { maxLive, poolCreated: pool, cacheHits: cached, reentryMs: reentry };
  });

  await page.screenshot({ path: join(out, "playground.png") });

  await step("no console errors", async () => {
    const real = consoleErrors.filter((e) => !/favicon/i.test(e));
    assert(real.length === 0, real.slice(0, 5).join("\n"));
  });
} finally {
  await browser.close();
  await new Promise((r) => server.httpServer.close(r));
}

writeFileSync(join(out, "e2e-results.json"), JSON.stringify(results, null, 2));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} steps passed. Artifacts in ${out}`);
process.exit(failed.length ? 1 : 0);
