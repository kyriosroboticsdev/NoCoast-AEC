import { Box, Network, PanelRight, Table2, X } from "lucide-react";
import type { RefObject } from "react";
import type { BimViewer, ElementRow, ElementSummary, LevelNode, ModelStats, PropertyGroup } from "../viewer/BimViewer";
import { DataView, ElementsView } from "./DataViews";
import { LevelTree } from "./LevelTree";
import { AxisGizmo, InfoCard, ViewControls } from "./ViewerOverlays";

export type Tab = "model" | "elements" | "data";

interface Props {
  hostRef: RefObject<HTMLDivElement | null>;
  viewer: BimViewer | null;
  fileName: string | null;
  schema: string;
  status: string | null; // overlay text while there's nothing to show
  progress: number | null;
  tab: Tab;
  setTab: (t: Tab) => void;
  treeOpen: boolean;
  setTreeOpen: (o: boolean) => void;
  treeVersion: number;
  onClose: () => void;
  stats: ModelStats | null;
  levels: LevelNode[];
  rows: ElementRow[] | null;
  selectedId: number | null;
  selected: ElementSummary | null;
  properties: PropertyGroup[];
  onSelect: (localId: number) => void;
  onPick: (localId: number) => void;
  onVisible: (ids: number[], visible: boolean) => void;
  onRooms: () => void;
  roomsVisible: boolean;
}

const TABS: [Tab, string, typeof Box][] = [["model", "Model", Box], ["elements", "Elements", Network], ["data", "Data", Table2]];

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
      <div className="ws-head">
        <span className="ws-file">{p.fileName ?? ""}</span>
        <div className="segmented">
          {TABS.map(([t, label, Icon]) => (
            <button key={t} className={p.tab === t ? "on" : ""} onClick={() => p.setTab(t)} disabled={!hasModel && t !== "model"}>
              <Icon size={16} /> {label}
            </button>
          ))}
        </div>
        <span className="ws-file ghost" aria-hidden>{p.fileName ?? ""}</span>
      </div>

      <div className="ws-body">
        <div className={`model-area ${p.tab === "model" ? "" : "behind"}`}>
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
              <InfoCard fileName={p.fileName!} schema={p.schema} stats={p.stats} selected={p.selected} />
              <div className="gizmo-wrap"><AxisGizmo viewer={p.viewer} /></div>
              <button className={`icon-btn tree-toggle ${p.treeOpen ? "on" : ""}`} title={p.treeOpen ? "Hide levels" : "Show levels"}
                onClick={() => p.setTreeOpen(!p.treeOpen)}>
                <PanelRight size={17} />
              </button>
            </>
          )}
        </div>
        {hasModel && p.tab === "model" && p.treeOpen && (
          <aside className="level-panel">
            <LevelTree key={p.treeVersion} levels={p.levels} selectedId={p.selectedId} onSelect={p.onSelect} onVisible={p.onVisible}
              hiddenCategories={p.roomsVisible ? [] : ["IFCSPACE"]} />
          </aside>
        )}
        {hasModel && p.tab === "elements" && (
          <ElementsView levels={p.levels} selectedId={p.selectedId} properties={p.properties} onSelect={p.onSelect} onVisible={p.onVisible} />
        )}
        {hasModel && p.tab === "data" && <DataView rows={p.rows} selectedId={p.selectedId} onPick={p.onPick} />}
      </div>
    </section>
  );
}
