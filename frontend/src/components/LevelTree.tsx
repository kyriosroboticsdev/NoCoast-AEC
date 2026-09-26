import { ChevronDown, ChevronRight, Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import type { LevelNode } from "../viewer/BimViewer";

interface Props {
  levels: LevelNode[];
  selectedId: number | null;
  onSelect: (localId: number) => void;
  onVisible: (ids: number[], visible: boolean) => void;
  /** categories hidden by default (e.g. IFCSPACE) so their eye icons start closed */
  hiddenCategories?: string[];
}

export function LevelTree({ levels, selectedId, onSelect, onVisible, hiddenCategories = [] }: Props) {
  if (!levels.length) return <p className="muted small pad">No levels in this model.</p>;
  return (
    <ul className="ltree">
      {levels.map((l, i) => (
        <Level key={l.localId} level={l} startOpen={i === 0} selectedId={selectedId} onSelect={onSelect} onVisible={onVisible} hiddenCategories={hiddenCategories} />
      ))}
    </ul>
  );
}

function Level({ level, startOpen, ...rest }: { level: LevelNode; startOpen: boolean } & Omit<Props, "levels">) {
  const [open, setOpen] = useState(startOpen);
  const ids = level.groups.flatMap((g) => g.items.map((i) => i.localId));
  return (
    <li>
      <Row depth={0} open={open} hasKids={level.groups.length > 0} onToggle={() => setOpen(!open)} bold
        label={<>{level.name} <span className="muted">({fmtElev(level.elevation)})</span></>}
        onVisible={(v) => rest.onVisible(ids, v)} />
      {open && (
        <ul>
          {level.groups.map((g) => <Group key={g.category} group={g} {...rest} />)}
        </ul>
      )}
    </li>
  );
}

function Group({ group, selectedId, onSelect, onVisible, hiddenCategories = [] }: { group: LevelNode["groups"][number] } & Omit<Props, "levels">) {
  const [open, setOpen] = useState(false);
  const startVisible = !hiddenCategories.includes(group.category.toUpperCase());
  return (
    <li>
      <Row depth={1} open={open} hasKids onToggle={() => setOpen(!open)} startVisible={startVisible}
        label={<span className="muted-strong">{group.label} ({group.items.length})</span>}
        onVisible={(v) => onVisible(group.items.map((i) => i.localId), v)} />
      {open && (
        <ul>
          {group.items.map((it) => (
            <li key={it.localId}>
              <Row depth={2} hasKids={false} selected={it.localId === selectedId} label={it.name} startVisible={startVisible}
                onClick={() => onSelect(it.localId)} onVisible={(v) => onVisible([it.localId], v)} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Row(p: {
  depth: number;
  label: React.ReactNode;
  hasKids: boolean;
  open?: boolean;
  bold?: boolean;
  selected?: boolean;
  onToggle?: () => void;
  onClick?: () => void;
  onVisible: (v: boolean) => void;
  startVisible?: boolean;
}) {
  const [visible, setVisible] = useState(p.startVisible ?? true);
  return (
    <div className={`lrow ${p.selected ? "sel" : ""} ${visible ? "" : "hidden"} ${p.bold ? "bold" : ""}`}
      style={{ paddingLeft: 4 + p.depth * 18 }}
      onClick={p.onClick ?? p.onToggle}>
      <span className="twisty">
        {p.hasKids ? (p.open ? <ChevronDown size={15} /> : <ChevronRight size={15} />) : null}
      </span>
      <span className="lname">{p.label}</span>
      <button className="eye" title={visible ? "Hide" : "Show"}
        onClick={(e) => { e.stopPropagation(); p.onVisible(!visible); setVisible(!visible); }}>
        {visible ? <Eye size={14} /> : <EyeOff size={14} />}
      </button>
    </div>
  );
}

function fmtElev(z: number) {
  const r = Math.round(z * 100) / 100;
  return `${Object.is(r, -0) ? 0 : r} m`;
}
