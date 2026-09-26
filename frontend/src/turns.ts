// Bridges backend project versions to @nocoast/ifc-viewer turns: every version
// becomes one turn card in the history, with a snapshot the agent loop can use.
import { IfcViewerRuntime, type TurnRef, type TurnSource } from "@nocoast/ifc-viewer";
import { backendUrl, fetchBytes, type Version } from "./api/client";

export const turnId = (v: Pick<Version, "project_id" | "number">) => `${v.project_id}:v${v.number}`;

export function ensureTurn(v: Version) {
  const id = turnId(v);
  if (!runtime.getTurns().some((t) => t.turn.id === id)) void runtime.addTurn(toTurn(v));
}

export function toTurn(v: Version): TurnRef {
  return {
    id: turnId(v),
    ifcPath: v.ifc_url,
    createdAt: new Date(v.created * 1000).toISOString(),
    label: v.prompt ?? v.notes[0] ?? `version ${v.number}`,
  };
}

const source: TurnSource = {
  // Versions are immutable on the backend, so the bytes for a turn never change.
  readIfc: (turn) => fetchBytes(backendUrl(turn.ifcPath)),
  // Snapshots stay in memory for now (TurnState.snapshotUrl). To feed them to a
  // vision model, add a backend endpoint and POST the PNG here.
};

// Same asset locations Kailash's BimViewer uses; copied by scripts/copy-wasm.mjs.
export const runtime = new IfcViewerRuntime(source, {
  wasmPath: "wasm/",
  fragmentsWorkerUrl: new URL("fragments-worker.mjs", window.location.href).href,
});
