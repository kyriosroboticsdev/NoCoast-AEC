# @nocoast/ifc-viewer

The render step of the NoCoast-AEC agent loop. Each time the agent writes an IFC
file, this package turns it into:

- an **inline turn card** for the chat transcript. It shows a snapshot like a
  generated image and becomes an orbitable 3D view when hovered.
- a **PNG snapshot** the loop can hand back to a vision model, so the agent can
  see what it built.
- an **inspector panel** with camera views, a section cut, level and category
  visibility, and click-to-see element properties.

It is built on [That Open](https://github.com/ThatOpen) (`web-ifc`,
`@thatopen/fragments`, `@thatopen/components`) and three.js. It runs entirely
locally and fetches nothing from a CDN, so it works offline inside Tauri.

## How it fits the app

```
agent writes turn-N.ifc
        │
        ▼
TurnSource (host app adapter: Tauri fs / events)
        │  readIfc
        ▼
IfcViewerRuntime ── preflight ── hash ── fragments (cache or convert in worker)
        │                                     │
        │                                     ▼
        │                       offscreen snapshot viewport ──► PNG
        │                                                        │
        │                              TurnSource.writeSnapshot ◄┘ (for the vision loop)
        ▼
<IfcTurnCard>  (borrows 1 of 3 pooled live viewports while hovered)
<IfcInspector> (its own viewport)
```

Browsers allow only about 8 to 16 live WebGL canvases per page, so cards share
a pool of 3. A card that loses its slot falls back to its snapshot. At most 5
contexts exist: 3 pooled, 1 inspector, 1 offscreen snapshotter.

## Install

The package keeps three.js, That Open, and web-ifc as **peer dependencies**. The
app must install exactly these versions, because That Open breaks when two
copies or mismatched versions are loaded.

```sh
npm install three@0.186.1 camera-controls@^3.1.2 web-ifc@0.0.77 \
  @thatopen/fragments@3.4.7 @thatopen/components@3.4.8
```

> **Keep `web-ifc` at 0.0.77.** In 0.0.78 the browser `web-ifc.wasm` does not
> match its own JavaScript, and every conversion fails with
> `function StreamMeshes called with 4 arguments, expected 3`. Node is not
> affected, so server-side tests will not catch it. Re-test in a browser
> before upgrading.

Two runtime assets must be served by the app:

1. `node_modules/web-ifc/web-ifc.wasm` copied to a public folder, such as
   `public/wasm/`. The playground's Vite config has a small plugin that does this.
2. The fragments worker, imported as a URL. See the configuration below.

## Usage (React)

```tsx
import fragmentsWorkerUrl from "@thatopen/fragments/worker?url";
import {
  IfcViewerRuntime, IfcViewerProvider, IfcTurnCard, IfcInspector, useTurns,
} from "@nocoast/ifc-viewer";
import "@nocoast/ifc-viewer/style.css";

// One runtime per window. Create it once, dispose it on window close.
const runtime = new IfcViewerRuntime(tauriTurnSource, {
  wasmPath: "/wasm/",
  fragmentsWorkerUrl,
}).start();

function Transcript() {
  const turns = useTurns();
  const [inspect, setInspect] = useState<string | null>(null);
  return (
    <>
      {turns.map((t, i) => (
        <IfcTurnCard
          key={t.turn.id}
          turnId={t.turn.id}
          liveOn={i === turns.length - 1 ? "visible" : "hover"}
          onExpand={setInspect}
        />
      ))}
      <IfcInspector turnId={inspect} onClose={() => setInspect(null)} />
    </>
  );
}

<IfcViewerProvider runtime={runtime}><Transcript /></IfcViewerProvider>;
```

The core classes (`IfcViewerRuntime`, `IfcViewport`, `InspectorController`) are
plain TypeScript, so a non-React host can use them directly.

## The adapter the app implements

```ts
interface TurnSource {
  readIfc(turn: TurnRef): Promise<Uint8Array>;
  writeSnapshot?(turn: TurnRef, png: Uint8Array, meta: SnapshotMeta): Promise<string | void>;
  readFrag?(hash: string): Promise<Uint8Array | null>;   // optional disk cache
  writeFrag?(hash: string, frag: Uint8Array): Promise<void>;
  onTurnAdded?(cb: (turn: TurnRef) => void): () => void;
}

interface TurnRef {
  id: string;          // stable per turn; re-adding the same id re-renders it
  ifcPath: string;     // opaque to the viewer, passed back to readIfc
  createdAt: string;
  label?: string;
  pngPath?: string;    // filled in from writeSnapshot's return value
}
```

### How the NoCoast app wires it

`frontend/src/turns.ts` is the real integration. Each backend project version
becomes a turn whose `ifcPath` is the version's `ifc_url`, and `readIfc` fetches
it over HTTP. `frontend/src/App.tsx` adds a turn per version and renders one
`IfcTurnCard` per version in the history. The frontend consumes this package
from source through a Vite alias and TypeScript `paths`, so there is no build
step. Both of those dedupe three.js and That Open onto the frontend's copies.

### Alternative: reading files through Tauri

If turns ever come from local files instead of the backend, a Tauri adapter
looks like this:

```ts
import { readFile, writeFile } from "@tauri-apps/plugin-fs";
import { listen } from "@tauri-apps/api/event";

export const tauriTurnSource: TurnSource = {
  readIfc: (t) => readFile(t.ifcPath),
  async writeSnapshot(t, png) {
    const path = t.ifcPath.replace(/\.ifc$/i, ".png");
    await writeFile(path, png);
    return path;                       // the agent loop reads this PNG
  },
  async readFrag(hash) {
    try { return await readFile(`${cacheDir}/${hash}.frag`); } catch { return null; }
  },
  writeFrag: (hash, frag) => writeFile(`${cacheDir}/${hash}.frag`, frag),
  onTurnAdded(cb) {
    // The backend emits this after the agent finishes writing a file.
    const un = listen<TurnRef>("ifc-turn-added", (e) => cb(e.payload));
    return () => void un.then((f) => f());
  },
};
```

The fs capability needs read access to the turns directory and write access for
the PNG and `.frag` cache. **Emit `ifc-turn-added` only after the file is fully
written and closed.** The viewer rejects files missing the IFC end marker, but
writing to a temp file and then renaming it avoids that race entirely.

## The vision loop

Each processed turn gets a 1024×768 PNG with an isometric view on a white
background. It is passed to `writeSnapshot` and exposed as `TurnState.snapshotUrl`.
For extra angles, request more views on demand:

```ts
const top   = await runtime.captureSnapshot("turn-7", { view: "top" });
const front = await runtime.captureSnapshot("turn-7", { view: "front", width: 1600, height: 1200 });
```

Available views are `iso`, `top`, `front` (looking at the IFC south face), and `side`.
Snapshot work is serialised, so it never races the live cards.

## Error handling

A turn ends in `status: "error"` with a readable `error` string instead of
rendering something misleading:

| Problem | Message shown |
| --- | --- |
| Truncated file (agent still writing, or crashed mid-write) | `File is truncated: missing END-ISO-10303-21 terminator…` |
| Not IFC STEP text, or IFCZIP | `Not an IFC STEP file…` or `File is a zip archive (IFCZIP)…` |
| Unsupported schema | `Unsupported IFC schema "…"` |
| Valid file with no geometry | `Model has no renderable geometry.` |

The truncation check exists because web-ifc does not fail on a truncated file.
It silently renders whatever entities were written, which in an agent loop
looks like a valid but incomplete building.

Re-adding an existing turn id re-renders it. Results from any older version of
that turn still in flight are discarded.

## Development

Run everything from this folder. On Windows Git Bash, call the binaries through
`node` if `npx` shims fail.

| Task | Command |
| --- | --- |
| Unit and integration tests | `npm test` |
| Typecheck | `npm run typecheck` |
| Browser playground (simulated agent session) | `npm run playground` then open http://localhost:5178 |
| End-to-end browser test (uses installed Chrome or Edge) | `npm run e2e` |
| Regenerate the sample IFC turns | `npm run fixtures` |
| Validate IFC files the way the viewer will | `npm run validate -- path/to/*.ifc` |
| Library build (`dist/`) | `npm run build` |

The end-to-end test writes snapshots and screenshots to `test-results/`.

The fixtures are generated IFC4 files for a 12 × 8 m two-storey building that
grows over five turns, plus a truncated copy. The playground's buttons play
the turns, inject the broken one, or add 20 turns to stress the pool.
