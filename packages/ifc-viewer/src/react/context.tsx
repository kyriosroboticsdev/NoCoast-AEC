import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";
import type { IfcViewerRuntime } from "../core/runtime";
import type { TurnState } from "../core/types";

const RuntimeContext = createContext<IfcViewerRuntime | null>(null);

/**
 * Supplies an IfcViewerRuntime to cards and inspectors. The host app creates
 * and disposes the runtime so its lifetime matches the window, not a view.
 */
export function IfcViewerProvider({ runtime, children }: { runtime: IfcViewerRuntime; children: ReactNode }) {
  return <RuntimeContext.Provider value={runtime}>{children}</RuntimeContext.Provider>;
}

export function useIfcRuntime(): IfcViewerRuntime {
  const rt = useContext(RuntimeContext);
  if (!rt) throw new Error("useIfcRuntime must be used inside <IfcViewerProvider>");
  return rt;
}

/** All turns in insertion order; re-renders on any turn change. */
export function useTurns(): TurnState[] {
  const rt = useIfcRuntime();
  return useSyncExternalStore(
    (cb) => rt.subscribe(cb),
    () => rt.getTurns(),
  );
}

/** One turn's state; re-renders only when that turn's state object changes. */
export function useTurn(id: string | null | undefined): TurnState | undefined {
  const rt = useIfcRuntime();
  return useSyncExternalStore(
    (cb) => rt.subscribe(cb),
    () => (id ? rt.getTurn(id) : undefined),
  );
}
