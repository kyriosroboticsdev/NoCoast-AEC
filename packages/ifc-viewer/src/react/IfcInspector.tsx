import { useEffect, useRef, useState } from "react";
import { InspectorController, type ElementInfo, type VisibilityGroup } from "../core/inspector";
import type { SnapshotView } from "../core/types";
import { IfcViewport } from "../core/viewport";
import { useIfcRuntime, useTurn } from "./context";

export interface IfcInspectorProps {
  turnId: string | null;
  onClose?: () => void;
  className?: string;
}

type Tab = "properties" | "structure";

/**
 * Full-size inspection panel for one turn: orbit, canonical views, a
 * horizontal section slider, storey/category visibility, and click-to-select
 * element properties. Owns one dedicated viewport outside the card pool.
 */
export function IfcInspector({ turnId, onClose, className }: IfcInspectorProps) {
  const rt = useIfcRuntime();
  const state = useTurn(turnId);
  const stageRef = useRef<HTMLDivElement>(null);
  const ctlRef = useRef<InspectorController | null>(null);
  const [selected, setSelected] = useState<ElementInfo | null>(null);
  const [groups, setGroups] = useState<VisibilityGroup[]>([]);
  const [section, setSection] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("properties");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // One viewport + controller for the inspector's lifetime.
  useEffect(() => {
    const vp = new IfcViewport({ interactive: true });
    vp.mount(stageRef.current!);
    const ctl = new InspectorController(vp);
    ctl.onSelect.add((info) => {
      setSelected(info);
      if (info) setTab("properties");
    });
    ctlRef.current = ctl;
    return () => {
      ctl.dispose();
      vp.dispose();
      ctlRef.current = null;
    };
  }, []);

  const ready = state?.status === "ready";
  useEffect(() => {
    const ctl = ctlRef.current;
    if (!ctl || !turnId || !ready) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelected(null);
    setSection(null);
    (async () => {
      try {
        const frag = await rt.getFrag(turnId);
        if (cancelled) return;
        await ctl.viewport.show(turnId, frag, "iso");
        await ctl.reset();
        if (!cancelled) setGroups(ctl.groups());
      } catch (e) {
        if (!cancelled) setError(String((e as Error)?.message ?? e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [rt, turnId, ready, state?.hash]);

  useEffect(() => {
    ctlRef.current?.setSection(section);
  }, [section]);

  const view = (v: SnapshotView) => void ctlRef.current?.viewport.frame(v);
  const toggleGroup = async (g: VisibilityGroup) => {
    const ctl = ctlRef.current;
    if (!ctl) return;
    // Update the checkbox immediately; applying visibility is async.
    setGroups((gs) =>
      gs.map((x) => (x.classification === g.classification && x.name === g.name ? { ...x, visible: !g.visible } : x)),
    );
    await ctl.setGroupVisible(g.classification, g.name, !g.visible);
    setGroups(ctl.groups());
  };
  const showAll = async () => {
    const ctl = ctlRef.current;
    if (!ctl) return;
    await ctl.showAll();
    setGroups(ctl.groups());
  };

  const levels = groups.filter((g) => g.classification === "Levels");
  const categories = groups.filter((g) => g.classification === "Categories");
  const shownError = error ?? (state?.status === "error" ? state.error : null);

  return (
    <div className={`ncv-root ncv-inspector ${className ?? ""}`} data-turn={turnId ?? undefined}>
      <div className="ncv-insp-toolbar">
        <strong className="ncv-insp-title">{turnId ?? "No turn selected"}</strong>
        <div className="ncv-btn-group" role="group" aria-label="Camera view">
          {(["iso", "top", "front", "side"] as const).map((v) => (
            <button key={v} type="button" className="ncv-btn" onClick={() => view(v)}>
              {v[0].toUpperCase() + v.slice(1)}
            </button>
          ))}
        </div>
        <label className="ncv-section">
          <input
            type="checkbox"
            checked={section !== null}
            onChange={(e) => setSection(e.target.checked ? 0.5 : null)}
          />
          Section
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={section ?? 0.5}
            disabled={section === null}
            onChange={(e) => setSection(Number(e.target.value))}
            aria-label="Section height"
          />
        </label>
        {onClose && (
          <button type="button" className="ncv-btn ncv-insp-close" onClick={onClose} aria-label="Close inspector">
            Close
          </button>
        )}
      </div>

      <div className="ncv-insp-body">
        <div className="ncv-insp-stage" ref={stageRef}>
          {(loading || state?.status === "loading" || state?.status === "pending") && (
            <div className="ncv-card-overlay">
              <div className="ncv-spinner" aria-hidden />
              <span>Loading model…</span>
            </div>
          )}
          {shownError && (
            <div className="ncv-card-overlay is-error" role="alert">
              <strong>Couldn't load this turn</strong>
              <span>{shownError}</span>
            </div>
          )}
          {!turnId && <div className="ncv-card-overlay">Choose a turn to inspect</div>}
        </div>

        <aside className="ncv-insp-side">
          <div className="ncv-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === "properties"} onClick={() => setTab("properties")}>
              Properties
            </button>
            <button type="button" role="tab" aria-selected={tab === "structure"} onClick={() => setTab("structure")}>
              Levels & categories
            </button>
          </div>

          {tab === "properties" && (
            <div className="ncv-panel" data-testid="ncv-properties">
              {!selected && <p className="ncv-muted">Click an element in the model to see its properties.</p>}
              {selected && (
                <>
                  <h4 className="ncv-el-title">
                    {selected.name || "(unnamed)"} <span className="ncv-muted">{selected.category}</span>
                  </h4>
                  <table className="ncv-props">
                    <tbody>
                      {Object.entries(selected.attributes).map(([k, v]) => (
                        <tr key={k}>
                          <th>{k}</th>
                          <td>{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {Object.entries(selected.psets).map(([pset, props]) => (
                    <section key={pset}>
                      <h5>{pset}</h5>
                      <table className="ncv-props">
                        <tbody>
                          {Object.entries(props).map(([k, v]) => (
                            <tr key={k}>
                              <th>{k}</th>
                              <td>{v}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </section>
                  ))}
                </>
              )}
            </div>
          )}

          {tab === "structure" && (
            <div className="ncv-panel" data-testid="ncv-structure">
              <button type="button" className="ncv-btn" onClick={() => void showAll()}>
                Show all
              </button>
              {[
                ["Levels", levels],
                ["Categories", categories],
              ].map(([title, list]) => (
                <section key={title as string}>
                  <h5>{title as string}</h5>
                  {(list as VisibilityGroup[]).length === 0 && <p className="ncv-muted">None</p>}
                  {(list as VisibilityGroup[]).map((g) => (
                    <label key={g.name} className="ncv-group">
                      <input type="checkbox" checked={g.visible} onChange={() => void toggleGroup(g)} />
                      <span>{g.name}</span>
                      <span className="ncv-muted">{g.count}</span>
                    </label>
                  ))}
                </section>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
