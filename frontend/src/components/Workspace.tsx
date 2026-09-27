import { Box, Calculator, FileStack, ShieldCheck, X, type LucideIcon } from "lucide-react";
import type { RefObject } from "react";
import type { ExportFormat } from "../api/client";
import type { Facts } from "../state/design";
import type { LegacyViewer, Picked, PropertySet } from "../viewer/LegacyViewer";
import type { SectionView } from "../viewer/section";
import { Deliverables, TABS, type DeliverableTab } from "./Deliverables";
import { AxisGizmo, InfoCard, SectionBar, Showing, ViewControls } from "./ViewerOverlays";

const TAB_ICONS: Record<DeliverableTab, LucideIcon> = {
  model: Box, drawings: FileStack, review: ShieldCheck, cost: Calculator,
};

interface Props {
  /** Which view of the version fills the workspace; the 3D viewport stays mounted underneath. */
  tab: DeliverableTab;
  onTab: (tab: DeliverableTab) => void;
  onExport: (format: ExportFormat) => void;
  onShow: (ids: string[]) => void;
  hostRef: RefObject<HTMLDivElement | null>;
  viewer: LegacyViewer | null;
  fileName: string | null;
  schema: string;
  status: string | null; // overlay text while there's nothing to show
  /** What the viewer currently shows (a preview while the model works, or a final version). */
  shown: { label: string; preview: boolean; version?: { project: string; number: number } | null } | null;
  section: SectionView | null;
  onSection: (tenths: number) => void;
  onFollow: (on: boolean) => void;
  onClose: () => void;
  picked: Picked | null;
  facts: Facts | null;
  properties: PropertySet[];
  onClearPick: () => void;
  roomsVisible: boolean;
  onRooms: () => void;
  /** Sizes of the floating panels over the model, and their drag handles (state/layout.ts). */
  inspector: { width: number; height: number };
  onResizeInspector: (size: { width?: number; height?: number }) => void;
  onResetInspector: () => void;
  viewTools: number;
  onResizeViewTools: (width: number) => void;
  onResetViewTools: () => void;
}

export function Workspace(p: Props) {
  const hasModel = !!p.shown;
  return (
    <section className="workspace">
      <div className="file-tabs">
        {p.fileName && (
          <div className="file-tab on" title={p.fileName}>
            <Box size={16} />
            <span>{p.fileName}</span>
            <button className="icon-btn tiny" title="Close model" onClick={p.onClose}><X size={14} /></button>
          </div>
        )}
        {p.shown && (
          <nav className="view-tabs" role="tablist">
            {TABS.map((t) => {
              const Icon = TAB_ICONS[t.id];
              const locked = t.id !== "model" && !p.shown?.version;
              return (
                <button key={t.id} role="tab" aria-selected={p.tab === t.id} className={`view-tab ${p.tab === t.id ? "on" : ""}`}
                  disabled={locked} title={locked ? "Available once the version is built" : t.label}
                  onClick={() => p.onTab(t.id)}>
                  <Icon size={14} /> {t.label}
                </button>
              );
            })}
          </nav>
        )}
      </div>
      <div className="ws-body">
        <div className={`model-area ${p.tab !== "model" ? "covered" : ""}`}>
          <div className="viewport" ref={p.hostRef} />
          {p.status && !hasModel && (
            <div className="viewport-status">
              <div>{p.status}</div>
            </div>
          )}
          {p.status && hasModel && <div className="viewport-toast">{p.status}</div>}
          {hasModel && p.viewer && (
            <>
              <Showing label={p.shown!.label} preview={p.shown!.preview} />
              <ViewControls viewer={p.viewer} roomsVisible={p.roomsVisible} onRooms={p.onRooms}
                width={p.viewTools} onResize={p.onResizeViewTools} onResetSize={p.onResetViewTools} />
              <InfoCard fileName={p.fileName ?? ""} schema={p.schema} picked={p.picked} facts={p.facts} properties={p.properties}
                onClear={p.onClearPick} width={p.inspector.width} height={p.inspector.height}
                onResize={p.onResizeInspector} onResetSize={p.onResetInspector} />
              {p.section && <SectionBar section={p.section} onValue={p.onSection} onFollow={p.onFollow} />}
              <div className="gizmo-wrap"><AxisGizmo viewer={p.viewer} /></div>
            </>
          )}
          {p.tab !== "model" && (
            <div className="deliverables-layer">
              <Deliverables tab={p.tab} version={p.shown?.version} onExport={p.onExport} onShow={p.onShow} />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
