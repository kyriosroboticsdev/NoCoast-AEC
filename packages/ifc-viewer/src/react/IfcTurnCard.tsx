import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { IfcViewport } from "../core/viewport";
import { useIfcRuntime, useTurn } from "./context";

export interface IfcTurnCardProps {
  turnId: string;
  /** Card height in px. Width fills the parent. */
  height?: number;
  /**
   * When the card becomes a live 3D view:
   * - "hover": on pointer enter or tap (default)
   * - "visible": as soon as it scrolls into view (use for the latest turn)
   */
  liveOn?: "hover" | "visible";
  onExpand?: (turnId: string) => void;
  className?: string;
}

/**
 * Inline, image-like preview of one agent turn. Shows the turn's snapshot
 * PNG by default and swaps in an orbitable live viewport borrowed from the
 * runtime's pool when the user engages with it. If the pool evicts it for
 * another card, it falls back to the snapshot seamlessly.
 */
export function IfcTurnCard({ turnId, height = 260, liveOn = "hover", onExpand, className }: IfcTurnCardProps) {
  const rt = useIfcRuntime();
  const state = useTurn(turnId);
  const cardKey = `card:${turnId}:${useId()}`;
  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const vpRef = useRef<IfcViewport | null>(null);
  const [visible, setVisible] = useState(false);
  const [live, setLive] = useState(false);
  const [engaging, setEngaging] = useState(false);
  const ready = state?.status === "ready";

  // Track viewport visibility so offscreen cards return their WebGL slot.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const goLive = useCallback(async () => {
    if (!ready || vpRef.current || !stageRef.current) return;
    const vp = rt.acquireViewport(cardKey, () => {
      vpRef.current = null;
      setLive(false);
    });
    if (!vp) return;
    vpRef.current = vp;
    vp.mount(stageRef.current);
    try {
      const frag = await rt.getFrag(turnId);
      if (vpRef.current !== vp) return;
      await vp.show(turnId, frag, "iso");
      if (vpRef.current === vp) setLive(true);
    } catch (e) {
      console.warn("@nocoast/ifc-viewer: live view failed", e);
      if (vpRef.current === vp) {
        vpRef.current = null;
        rt.releaseViewport(cardKey);
      }
    }
  }, [ready, rt, cardKey, turnId]);

  const goStill = useCallback(() => {
    if (!vpRef.current) return;
    vpRef.current = null;
    setLive(false);
    rt.releaseViewport(cardKey);
  }, [rt, cardKey]);

  useEffect(() => {
    if (!visible) goStill();
    else if (liveOn === "visible" || engaging) void goLive();
  }, [visible, liveOn, engaging, goLive, goStill]);

  // Reload if the turn is reprocessed (e.g. the agent overwrote the file).
  useEffect(() => {
    if (!ready) goStill();
  }, [ready, goStill]);

  useEffect(() => () => rt.releaseViewport(cardKey), [rt, cardKey]);

  const onEnter = () => {
    rt.pool.pin(cardKey);
    setEngaging(true);
  };
  const onLeave = () => {
    rt.pool.unpin(cardKey);
    rt.pool.touch(cardKey);
    setEngaging(false);
  };

  const status = state?.status ?? "pending";
  return (
    <div
      ref={rootRef}
      className={`ncv-root ncv-card ${live ? "is-live" : ""} ${className ?? ""}`}
      style={{ height }}
      data-turn={turnId}
      data-status={status}
      data-live={live || undefined}
      onPointerEnter={onEnter}
      onPointerLeave={onLeave}
      onFocus={onEnter}
      onBlur={onLeave}
      tabIndex={0}
    >
      {state?.snapshotUrl && <img className="ncv-card-still" src={state.snapshotUrl} alt={`3D render of ${turnId}`} draggable={false} />}
      {/* Kept in layout (visibility, not display:none) so the borrowed
          viewport can measure a real size before it becomes visible. */}
      <div ref={stageRef} className={`ncv-card-stage ${live ? "" : "is-idle"}`} />

      {(status === "pending" || status === "loading") && (
        <div className="ncv-card-overlay">
          <div className="ncv-spinner" aria-hidden />
          <span>Rendering model…</span>
        </div>
      )}
      {status === "error" && (
        <div className="ncv-card-overlay is-error" role="alert">
          <strong>Couldn't render this turn</strong>
          <span>{state?.error}</span>
        </div>
      )}

      {ready && (
        <div className="ncv-card-chrome">
          <span className="ncv-chip">{live ? "Drag to orbit · scroll to zoom" : "Hover to explore in 3D"}</span>
          <span className="ncv-card-actions">
            {live && (
              <button type="button" className="ncv-btn" onClick={() => void vpRef.current?.frame("iso")} title="Reset view">
                Reset
              </button>
            )}
            {onExpand && (
              <button type="button" className="ncv-btn" onClick={() => onExpand(turnId)} title="Open in inspector">
                Inspect
              </button>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
