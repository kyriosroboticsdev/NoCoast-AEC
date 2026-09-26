import { Box, X } from "lucide-react";
import type { RefObject } from "react";
import type { LegacyViewer, Picked, PropertySet } from "../viewer/LegacyViewer";
import { AxisGizmo, InfoCard, ViewControls } from "./ViewerOverlays";

interface Props {
  hostRef: RefObject<HTMLDivElement | null>;
  viewer: LegacyViewer | null;
  fileName: string | null;
  schema: string;
  status: string | null; // overlay text while there's nothing to show
  progress: number | null;
  onClose: () => void;
  picked: Picked | null;
  properties: PropertySet[];
  roomsVisible: boolean;
  onRooms: () => void;
}

export function Workspace(p: Props) {
  const hasModel = !!p.fileName && p.progress === null;
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
          {p.status && (
            <div className="viewport-status">
              <div>{p.status}</div>
              {p.progress !== null && <div className="bar"><i style={{ width: `${p.progress * 100}%` }} /></div>}
            </div>
          )}
          {hasModel && p.viewer && (
            <>
              <ViewControls viewer={p.viewer} roomsVisible={p.roomsVisible} onRooms={p.onRooms} />
              <InfoCard fileName={p.fileName!} schema={p.schema} picked={p.picked} properties={p.properties} />
              <div className="gizmo-wrap"><AxisGizmo viewer={p.viewer} /></div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
