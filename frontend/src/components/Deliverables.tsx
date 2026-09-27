// The office side of a version: the drawing set, the code review and the cost / carbon plan the
// backend derives from the model (GET /projects/{id}/versions/{n}/analysis). Everything here is drawn
// from the same IFC the viewer shows, so the numbers and the geometry never disagree.
import {
  AlertTriangle, Building2, Check, Download, ExternalLink, FileText, Info, Leaf, LoaderCircle, Maximize2, Ruler,
  ShieldCheck, Users, X, type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import * as api from "../api/client";

export type DeliverableTab = "model" | "drawings" | "review" | "cost";

export const TABS: { id: DeliverableTab; label: string }[] = [
  { id: "model", label: "3D model" },
  { id: "drawings", label: "Drawings" },
  { id: "review", label: "Code review" },
  { id: "cost", label: "Cost & carbon" },
];

const cache = new Map<string, Promise<api.Analysis>>();

/** The analysis of one version; versions never change, so it is fetched once per session of the app. */
export function useAnalysis(version: { project: string; number: number } | null | undefined) {
  const [data, setData] = useState<api.Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = version ? `${version.project}/${version.number}` : null;
  useEffect(() => {
    setData(null);
    setError(null);
    if (!version || !key) return;
    let live = true;
    let p = cache.get(key);
    if (!p) {
      p = api.getAnalysis(version.project, version.number);
      cache.set(key, p);
      p.catch(() => cache.delete(key));
    }
    p.then((d) => live && setData(d), (e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error };
}

const usd = (v: number) => (v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : `$${Math.round(v / 1e3).toLocaleString()}k`);
const num = (v: number, d = 0) => v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });

interface Props {
  tab: DeliverableTab;
  version: { project: string; number: number } | null | undefined;
  onExport: (format: api.ExportFormat) => void;
  /** Show elements in the 3D model (switches to the model tab). */
  onShow: (ids: string[]) => void;
}

export function Deliverables({ tab, version, onExport, onShow }: Props) {
  const { data, error } = useAnalysis(version);
  if (!version) {
    return <div className="dl-empty"><Info size={18} /> Drawings, the code review and the cost plan appear once a version is built.</div>;
  }
  if (error) return <div className="dl-empty err"><X size={18} /> {error}</div>;
  if (!data) return <div className="dl-empty"><LoaderCircle size={18} className="spin" /> Drawing the set and running the review…</div>;
  return (
    <div className="deliverables">
      {tab === "drawings" && <Drawings data={data} onExport={onExport} />}
      {tab === "review" && <Review data={data} onExport={onExport} onShow={onShow} />}
      {tab === "cost" && <Cost data={data} onExport={onExport} />}
    </div>
  );
}

// --- drawings ----------------------------------------------------------------

function Drawings({ data, onExport }: { data: api.Analysis; onExport: Props["onExport"] }) {
  const [sel, setSel] = useState(data.sheets.find((s) => s.kind === "plan")?.number ?? data.sheets[0]?.number);
  const sheet = data.sheets.find((s) => s.number === sel) ?? data.sheets[0];
  const [zoom, setZoom] = useState(false);
  return (
    <div className="dl-drawings">
      <aside className="sheet-list">
        <div className="dl-list-head">
          <b>Drawing set</b>
          <span className="muted small">{data.sheets.length} sheets · A3 · US NCS numbering</span>
        </div>
        {data.sheets.map((s) => (
          <button key={s.number} className={`sheet-thumb ${s.number === sheet?.number ? "on" : ""}`} onClick={() => setSel(s.number)}>
            <img src={api.backendUrl(s.url)} alt={s.title} loading="lazy" />
            <span><b>{s.number}</b> {s.title}{s.scale && s.scale !== "NTS" ? <em> · {s.scale}</em> : null}</span>
          </button>
        ))}
      </aside>
      <div className="sheet-main">
        <div className="dl-toolbar">
          <div>
            <b>{sheet?.number}</b> <span className="muted-strong">{sheet?.title}</span>
            {sheet?.scale && sheet.scale !== "NTS" && <span className="chip tiny">{sheet.scale} @ A3</span>}
          </div>
          <span className="grow" />
          <button className="btn ghost" onClick={() => setZoom(true)}><Maximize2 size={15} /> Full screen</button>
          <a className="btn ghost" href={sheet ? api.backendUrl(sheet.url) : undefined} target="_blank" rel="noreferrer"><ExternalLink size={15} /> SVG</a>
          <button className="btn primary" onClick={() => onExport("drawings")}><Download size={15} /> PDF set</button>
          <button className="btn ghost" onClick={() => onExport("zip")}><Download size={15} /> Bundle</button>
        </div>
        {sheet && (
          <div className="sheet-frame" onDoubleClick={() => setZoom(true)}>
            <img key={sheet.number} src={api.backendUrl(sheet.url)} alt={sheet.title} />
          </div>
        )}
      </div>
      {zoom && sheet && (
        <div className="sheet-zoom" onClick={() => setZoom(false)}>
          <img src={api.backendUrl(sheet.url)} alt={sheet.title} />
          <button className="icon-btn round" title="Close"><X size={18} /></button>
        </div>
      )}
    </div>
  );
}

// --- code review -------------------------------------------------------------

const STATUS: Record<api.CheckStatus, { label: string; icon: LucideIcon }> = {
  pass: { label: "Pass", icon: Check },
  warn: { label: "Review", icon: AlertTriangle },
  fail: { label: "Fail", icon: X },
  info: { label: "Info", icon: Info },
};

function Kpi({ icon: Icon, label, value, sub }: { icon: LucideIcon; label: string; value: string; sub?: string }) {
  return (
    <div className="kpi">
      <span className="kpi-icon"><Icon size={16} /></span>
      <div>
        <div className="kpi-label">{label}</div>
        <div className="kpi-value">{value}</div>
        {sub && <div className="kpi-sub">{sub}</div>}
      </div>
    </div>
  );
}

function Review({ data, onExport, onShow }: { data: api.Analysis; onExport: Props["onExport"]; onShow: Props["onShow"] }) {
  const r = data.review;
  const order: Record<api.CheckStatus, number> = { fail: 0, warn: 1, info: 2, pass: 3 };
  const checks = [...r.checks].sort((a, b) => order[a.status] - order[b.status]);
  const [filter, setFilter] = useState<api.CheckStatus | "all">("all");
  const shown = checks.filter((c) => filter === "all" || c.status === filter);
  return (
    <div className="dl-scroll">
      <div className="dl-head">
        <div>
          <h2>Code review</h2>
          <p className="muted">{r.code} · indicative design-stage screen of the model geometry</p>
        </div>
        <span className="grow" />
        <button className="btn ghost" onClick={() => onExport("bcf")}><Download size={15} /> BCF issues</button>
        <button className="btn ghost" onClick={() => onExport("review")}><FileText size={15} /> Report</button>
      </div>
      <div className="kpis">
        <Kpi icon={Building2} label="Occupancy" value={r.occupancy.group} sub={r.occupancy.name.split("—").pop()?.trim()} />
        <Kpi icon={Users} label="Occupant load" value={`${r.occupancy.load}`} sub="IBC Table 1004.5" />
        <Kpi icon={Ruler} label="Gross floor area" value={`${num(r.totals.gia)} m²`} sub={`${num(r.totals.gia_sf)} sf · ${r.totals.storeys} storeys`} />
        <Kpi icon={ShieldCheck} label="Construction" value={r.occupancy.construction.split(" (")[0]} sub={r.occupancy.sprinklered ? "sprinklered" : "unsprinklered"} />
      </div>
      <div className="score-bar">
        {(["all", "fail", "warn", "pass", "info"] as const).map((k) => {
          const n = k === "all" ? r.score.total : r.score[k];
          if (k !== "all" && !n) return null;
          return (
            <button key={k} className={`score-chip ${k} ${filter === k ? "on" : ""}`} onClick={() => setFilter(k)}>
              <b>{n}</b> {k === "all" ? "clauses" : STATUS[k].label.toLowerCase()}
            </button>
          );
        })}
      </div>
      <ul className="checks">
        {shown.map((c) => {
          const S = STATUS[c.status];
          return (
            <li key={c.id} className={`check ${c.status}`}>
              <span className="check-icon"><S.icon size={14} /></span>
              <div className="check-main">
                <div className="check-line">
                  <b>{c.title}</b>
                  <span className="clause">{c.reference}</span>
                  <span className="grow" />
                  {c.elements.length > 0 && c.status !== "pass" && (
                    <button className="link-btn" onClick={() => onShow(c.elements)}>Show in model</button>
                  )}
                </div>
                <div className="check-values">
                  <span><em>Measured</em> {c.value}</span>
                  <span><em>Required</em> {c.target}</span>
                </div>
                {c.status !== "pass" && c.detail && <div className="check-detail">{c.detail}</div>}
                {c.advice && <div className="check-advice">→ {c.advice}</div>}
              </div>
            </li>
          );
        })}
      </ul>
      <h3>Area schedule</h3>
      <table className="dl-table">
        <thead><tr><th>No.</th><th>Room</th><th>Level</th><th className="r">m²</th><th className="r">sf</th><th className="r">Glazing</th><th className="r">Clear h</th><th className="r">Occ.</th></tr></thead>
        <tbody>
          {r.rooms.map((x) => (
            <tr key={x.id}>
              <td className="mono">{x.number}</td><td>{x.name}</td><td className="muted">{x.level_name}</td>
              <td className="r">{num(x.area, 1)}</td><td className="r muted">{num(x.area * 10.7639)}</td>
              <td className={`r ${x.window_floor_ratio < 0.08 && x.kind !== "hall" && x.kind !== "bathroom" ? "warn-text" : ""}`}>{Math.round(x.window_floor_ratio * 100)}%</td>
              <td className="r">{num(x.clear_height * 1000)}</td><td className="r">{x.occupants || "—"}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          {r.levels.map((l) => (
            <tr key={l.id}><td /><td><b>{l.name}</b></td><td className="muted">GIA {num(l.gia, 1)} m²</td><td className="r"><b>{num(l.nia, 1)}</b></td><td className="r muted">{num(l.nia * 10.7639)}</td><td className="r muted" colSpan={2}>NIA/GIA {Math.round(l.efficiency * 100)}%</td><td className="r">{l.occupants}</td></tr>
          ))}
        </tfoot>
      </table>
      <ul className="assumptions">{r.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
    </div>
  );
}

// --- cost and carbon -----------------------------------------------------------

const GROUPS: Record<string, string> = { A: "Substructure", B: "Shell", C: "Interiors", D: "Services", E: "Equipment" };
const BANDS = ["A++", "A+", "A", "B", "C", "D", "E", "F", "G"];
const BAND_COLOURS = ["#0f7b3f", "#2c9a4d", "#6ab04c", "#b5c334", "#f0c419", "#f39c12", "#e67e22", "#d35400", "#c0392b"];

function Cost({ data, onExport }: { data: api.Analysis; onExport: Props["onExport"] }) {
  const { cost, carbon, quantities: q } = data.estimate;
  const byGroup = useMemo(() => {
    const m = new Map<string, number>();
    for (const l of cost.lines) m.set(l.group, (m.get(l.group) ?? 0) + l.total);
    return [...m.entries()];
  }, [cost.lines]);
  const maxGroup = Math.max(...byGroup.map(([, v]) => v), 1);
  const maxCarbon = Math.max(...carbon.rows.map((r) => r.kg), 1);
  const band = Math.max(0, BANDS.indexOf(carbon.band));
  return (
    <div className="dl-scroll">
      <div className="dl-head">
        <div>
          <h2>Cost &amp; carbon</h2>
          <p className="muted">Priced and measured from the model's own quantities</p>
        </div>
        <span className="grow" />
        <button className="btn ghost" onClick={() => onExport("estimate")}><Download size={15} /> Cost plan (.csv)</button>
      </div>
      <div className="cost-grid">
        <section className="dl-card">
          <div className="card-label">Construction cost · {cost.class}</div>
          <div className="big">{usd(cost.total)}</div>
          <div className="muted-strong">{usd(cost.low)} – {usd(cost.high)} · <b>${num(cost.per_sf)}/sf</b> · ${num(cost.per_m2)}/m²</div>
          <div className="bars">
            {byGroup.map(([g, v]) => (
              <div key={g} className="bar-row">
                <span className="bar-label">{g} {GROUPS[g] ?? ""}</span>
                <span className="meter"><i style={{ width: `${(v / maxGroup) * 100}%` }} /></span>
                <span className="bar-value">{usd(v)}</span>
              </div>
            ))}
            <div className="bar-row muted"><span className="bar-label">GC, OH&amp;P + contingency</span><span className="meter" /><span className="bar-value">{usd(cost.general_conditions + cost.contingency)}</span></div>
          </div>
          <p className="muted small">{cost.basis}.</p>
        </section>
        <section className="dl-card">
          <div className="card-label"><Leaf size={13} /> Upfront embodied carbon · A1–A5</div>
          <div className="big">{num(carbon.per_m2)} <small>kgCO₂e/m²</small></div>
          <div className="muted-strong">{num(carbon.total_kg / 1000, 1)} tCO₂e total · LETI {carbon.typology} 2030 target ≤ {carbon.target_2030}</div>
          <div className="bands">
            {BANDS.map((b, i) => (
              <span key={b} className={`band ${i === band ? "on" : ""}`} style={{ background: BAND_COLOURS[i] }}>{b}</span>
            ))}
          </div>
          <div className="bars">
            {carbon.rows.map((r) => (
              <div key={r.element} className="bar-row">
                <span className="bar-label">{r.element}</span>
                <span className="meter green"><i style={{ width: `${(r.kg / maxCarbon) * 100}%` }} /></span>
                <span className="bar-value">{num(r.kg / 1000, 1)} t</span>
              </div>
            ))}
          </div>
        </section>
      </div>
      {carbon.options.length > 0 && (
        <section className="dl-card">
          <div className="card-label">Design moves that cut carbon</div>
          <ul className="moves">
            {carbon.options.map((o) => (
              <li key={o.move}>
                <b>−{num(o.saving_kg / 1000, 1)} tCO₂e</b>
                <span className="pill ok">−{Math.round(o.saving_pct * 100)}%</span>
                <span>{o.move}</span>
                <span className="grow" />
                <span className="muted">→ {o.per_m2} kgCO₂e/m²{o.per_m2 <= carbon.target_2030 ? " · meets 2030" : ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <h3>Quantities</h3>
      <table className="dl-table">
        <tbody>
          {[
            ["External wall (net)", `${num(q.external_wall_area as number, 1)} m²`],
            ["Internal partitions", `${num(q.internal_wall_area as number, 1)} m²`],
            ["Ground floor slab", `${num(q.ground_floor_area as number, 1)} m²`],
            ["Upper floors", `${num(q.upper_floor_area as number, 1)} m²`],
            ["Roof", `${num(q.roof_area as number, 1)} m²`],
            ["Glazing", `${num(q.window_area as number, 1)} m² · ${q.windows} windows · WWR ${Math.round((q.window_wall_ratio as number) * 100)}%`],
            ["Doors", `${q.doors} (${q.exterior_doors} exterior)`],
            ["Stairs / columns", `${q.stairs} / ${q.columns}`],
            ["Fixtures and equipment", `${q.fixtures} + ${q.assets} library assets`],
            ...(q.lifts ? [["Passenger elevators", `${q.lifts} (${q.lift_stops} stops)`]] : []),
          ].map(([k, v]) => <tr key={k}><td>{k}</td><td className="r">{v}</td></tr>)}
        </tbody>
      </table>
      <h3>Cost plan (UniFormat II)</h3>
      <table className="dl-table">
        <thead><tr><th>Element</th><th className="r">Qty</th><th>Unit</th><th className="r">Rate</th><th className="r">Total</th></tr></thead>
        <tbody>
          {cost.lines.map((l) => (
            <tr key={l.element}><td>{l.element}</td><td className="r">{num(l.quantity, 1)}</td><td className="muted">{l.unit}</td><td className="r muted">${num(l.rate)}</td><td className="r">${num(l.total)}</td></tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td>General conditions, OH&amp;P (12 %)</td><td /><td /><td /><td className="r">${num(cost.general_conditions)}</td></tr>
          <tr><td>Design contingency (15 %)</td><td /><td /><td /><td className="r">${num(cost.contingency)}</td></tr>
          <tr><td><b>Total</b></td><td /><td /><td /><td className="r"><b>${num(cost.total)}</b></td></tr>
        </tfoot>
      </table>
    </div>
  );
}

/** One-line summary of a version's deliverables, for the assistant's run card. */
export function DeliverablesSummary({ version, onOpen }: {
  version: { project: string; number: number };
  onOpen: (tab: DeliverableTab) => void;
}) {
  const { data } = useAnalysis(version);
  if (!data) return null;
  const { review: r, estimate: e } = data;
  return (
    <div className="dl-summary">
      <button onClick={() => onOpen("drawings")}><FileText size={14} /><b>{data.sheets.length}</b> sheets</button>
      <button onClick={() => onOpen("review")} className={r.score.fail ? "bad" : r.score.warn ? "warn" : "ok"}>
        <ShieldCheck size={14} /><b>{r.score.pass}/{r.score.total}</b> clauses pass
        {r.score.fail ? <em>{r.score.fail} fail</em> : r.score.warn ? <em>{r.score.warn} to review</em> : null}
      </button>
      <button onClick={() => onOpen("cost")}><b>{usd(e.cost.total)}</b> · ${num(e.cost.per_sf)}/sf</button>
      <button onClick={() => onOpen("cost")}><Leaf size={14} /><b>{num(e.carbon.per_m2)}</b> kgCO₂e/m² · {e.carbon.band}</button>
    </div>
  );
}
