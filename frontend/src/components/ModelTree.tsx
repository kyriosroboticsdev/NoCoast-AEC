import { useState } from "react";
import type { TreeNode } from "../viewer/BimViewer";

interface Props {
  tree: TreeNode | null;
  selectedId: number | null;
  onSelect: (localId: number) => void;
  onToggle: (node: TreeNode, visible: boolean) => void;
}

export function ModelTree({ tree, selectedId, onSelect, onToggle }: Props) {
  if (!tree) return <p className="muted pad">No model loaded.</p>;
  return (
    <ul className="tree">
      <Node node={tree} depth={0} selectedId={selectedId} onSelect={onSelect} onToggle={onToggle} />
    </ul>
  );
}

function Node({ node, depth, ...rest }: { node: TreeNode; depth: number } & Omit<Props, "tree">) {
  const [open, setOpen] = useState(depth < 5);
  const [visible, setVisible] = useState(true);
  const hasKids = node.children.length > 0;
  // Collapse runs of category-only grouping nodes to keep the tree readable.
  return (
    <li>
      <div
        className={`row ${node.localId !== null && node.localId === rest.selectedId ? "sel" : ""} ${visible ? "" : "hidden"}`}
        style={{ paddingLeft: 6 + depth * 12 }}
      >
        <span className="twisty" onClick={() => setOpen(!open)}>{hasKids ? (open ? "▾" : "▸") : ""}</span>
        <span className="name" onClick={() => (node.localId !== null ? rest.onSelect(node.localId) : setOpen(!open))}
          title={node.category}>
          {node.label}
          {hasKids && <span className="muted"> {node.children.length}</span>}
        </span>
        <button className="eye" title={visible ? "Hide" : "Show"}
          onClick={() => { rest.onToggle(node, !visible); setVisible(!visible); }}>
          {visible ? "◉" : "○"}
        </button>
      </div>
      {open && hasKids && (
        <ul>{node.children.map((c) => <Node key={c.key} node={c} depth={depth + 1} {...rest} />)}</ul>
      )}
    </li>
  );
}
