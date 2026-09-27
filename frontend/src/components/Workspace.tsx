import { Box, X } from "lucide-react";
import type { RefObject } from "react";
import type { Facts } from "../state/design";
import type { LegacyViewer, Picked, PropertySet } from "../viewer/LegacyViewer";
import type { SectionView } from "../viewer/section";
import { AxisGizmo, InfoCard, SectionBar, Showing, ViewControls } from "./ViewerOverlays";

interface Props {
  hostRef: RefObject<HTMLDivElement | null>;
  viewer: LegacyViewer | null;
  fileName: string | null;
  schema: string;
  status: string | null; // overlay text while there's nothing to show
  /** What the viewer currently shows (a preview while the model works, or a final version). */
  shown: { label: string; preview: boolean } | null;
  section: SectionView | null;
  onSection: (tenths: number) => void;
  onFollow: (on: boolean) => void;
  onClose: () => void;
  picked: Picked | null;
  facts: Facts | null;
  properties: PropertySet[];
  /** How many elements are selected (shift-click selects several; the info card explains the last one). */
  selectedCount: number;
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
      </div>
      <div className="ws-body">
        <div className="model-area">
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
              <InfoCard fileName={p.fileName ?? ""} schema={p.schema} picked={p.picked} facts={p.facts} properties={p.properties} selectedCount={p.selectedCount}
                onClear={p.onClearPick} width={p.inspector.width} height={p.inspector.height}
                onResize={p.onResizeInspector} onResetSize={p.onResetInspector} />
              {p.section && <SectionBar section={p.section} onValue={p.onSection} onFollow={p.onFollow} />}
              <div className="gizmo-wrap"><AxisGizmo viewer={p.viewer} /></div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
