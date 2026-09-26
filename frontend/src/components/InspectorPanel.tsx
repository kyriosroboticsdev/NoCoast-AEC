import type { PropertyGroup, TreeNode } from "../viewer/BimViewer";
import { ModelTree } from "./ModelTree";

interface Props {
  tab: "tree" | "classes";
  setTab: (t: "tree" | "classes") => void;
  tree: TreeNode | null;
  categories: { name: string; count: number; visible: boolean }[];
  onCategory: (name: string, visible: boolean) => void;
  selectedId: number | null;
  onSelect: (localId: number) => void;
  onToggle: (node: TreeNode, visible: boolean) => void;
  properties: PropertyGroup[];
}

export function InspectorPanel(p: Props) {
  return (
    <aside className="panel right">
      <div className="tabs">
        <button className={p.tab === "tree" ? "on" : ""} onClick={() => p.setTab("tree")}>Hierarchy</button>
        <button className={p.tab === "classes" ? "on" : ""} onClick={() => p.setTab("classes")}>Classes</button>
      </div>
      <div className="scroll tree-box">
        {p.tab === "tree" ? (
          <ModelTree tree={p.tree} selectedId={p.selectedId} onSelect={p.onSelect} onToggle={p.onToggle} />
        ) : (
          <ul className="classes">
            {p.categories.map((c) => (
              <li key={c.name}>
                <label>
                  <input type="checkbox" checked={c.visible} onChange={(e) => p.onCategory(c.name, e.target.checked)} />
                  {c.name.replace(/^IFC/, "Ifc")} <span className="muted">{c.count}</span>
                </label>
              </li>
            ))}
            {!p.categories.length && <p className="muted pad">No model loaded.</p>}
          </ul>
        )}
      </div>
      <h3 className="section">Properties</h3>
      <div className="scroll props">
        {!p.properties.length && <p className="muted pad">Click an element to inspect it.</p>}
        {p.properties.map((g) => (
          <details key={g.title} open>
            <summary>{g.title}</summary>
            <table>
              <tbody>
                {g.rows.map(([k, v], i) => (
                  <tr key={k + i}><th>{k}</th><td>{v}</td></tr>
                ))}
              </tbody>
            </table>
          </details>
        ))}
      </div>
    </aside>
  );
}
