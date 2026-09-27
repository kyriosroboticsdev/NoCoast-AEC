import { IfcTurnCard } from "@nocoast/ifc-viewer";
import { ChevronDown, ChevronUp, Code, Database, Eye, ListChecks, RotateCcw, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { getSpec, type Version } from "../api/client";
import { PANEL_RANGE } from "../state/layout";
import type { Message, Session } from "../state/sessions";
import { turnId } from "../turns";
import { Composer } from "./Composer";
import { Reasoning } from "./Reasoning";
import { Resizer } from "./Resizer";

interface Props {
  session: Session;
  busy: boolean;
  planners: string[];
  planner: string | null;
  setPlanner: (p: string) => void;
  onSubmit: (text: string) => void;
  onAttach: () => void;
  /** Viewer selection that the next prompt will be about. */
  focus: { id: string; label: string } | null;
  onClearFocus: () => void;
  /** Key of the model in the workspace (`<session>:v<n>.ifc`). */
  viewing: string | null;
  onView: (v: Version) => void;
  onRestore: (n: number) => void;
  /** Panel width and turn-card height, both dragged by the user (state/layout.ts). */
  width: number;
  onResize: (width: number) => void;
  onResetWidth: () => void;
  cardHeight: number;
  onResizeCard: (height: number) => void;
  onResetCard: () => void;
}

export function Assistant({
  session, busy, viewing, onView, onRestore,
  width, onResize, onResetWidth, cardHeight, onResizeCard, onResetCard,
  ...composer
}: Props) {
  const head = session.project?.head ?? null;
  const latest = [...session.messages].reverse().find((m) => m.run?.version)?.id;
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    const el = scroller.current;
    if (el && atBottom) el.scrollTop = el.scrollHeight;
  }, [session.messages, atBottom]);

  return (
    <aside className="assistant" style={{ width }}>
      <Resizer className="resizer-assistant" label="Assistant width" onReset={onResetWidth}
        width={{ value: width, dir: -1, ...PANEL_RANGE.assistant, onChange: onResize }} />
      <div className="chat" ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
        }}>
        {session.messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} m={m} /> : (
          <AssistantMessage key={m.id} m={m} head={head} busy={busy} latest={m.id === latest}
            viewing={viewing === `${session.id}:v${m.run?.version?.number}.ifc`} onView={onView} onRestore={onRestore}
            cardHeight={cardHeight} onResizeCard={onResizeCard} onResetCard={onResetCard} />
        )))}
      </div>
      {!atBottom && (
        <button className="jump" onClick={() => setAtBottom(true)} title="Jump to latest">
          <ChevronDown size={18} />
        </button>
      )}
      <div className="dock">
        <Composer size="dock" busy={busy} placeholder={head ? "Describe a change…" : "Describe a building…"} {...composer} />
      </div>
    </aside>
  );
}

function UserBubble({ m }: { m: Message }) {
  return <div className="bubble">{m.text}</div>;
}

function AssistantMessage({ m, head, busy, latest, viewing, onView, onRestore, cardHeight, onResizeCard, onResetCard }: {
  m: Message; head: number | null; busy: boolean; latest: boolean; viewing: boolean;
  onView: (v: Version) => void; onRestore: (n: number) => void;
  cardHeight: number; onResizeCard: (height: number) => void; onResetCard: () => void;
}) {
  const run = m.run;
  if (!run) return <div className="answer"><p>{m.text}</p></div>;
  const v = run.version;

  return (
    <div className="answer">
      {m.text && <p>{m.text}</p>}
      <Reasoning run={run} />

      {v && v.checks && v.checks.length > 0 && <Checklist checks={v.checks} />}

      {v && v.notes.length > 0 && (
        <Collapsible icon={<Sparkles size={16} />} title={`Interpreted by ${v.llm ?? v.mode}`}>
          <ul className="notes">{v.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Collapsible>
      )}
      {v && (
        <Collapsible icon={<Code size={16} />} title="Structured BIM instructions">
          <SpecView v={v} />
        </Collapsible>
      )}

      {v && (
        <div className="results">
          <div className="results-head">
            <span className="results-icon"><Database size={18} /></span>
            <span className="results-title">
              <b>Version {v.number}</b>
              <small>{v.mode}{v.parent ? ` · from v${v.parent}` : ""}</small>
            </span>
            <span className="chip">{v.summary.elements} elements</span>
          </div>
          <table className="grid">
            <thead><tr><th>IFC class</th><th className="num">Count</th></tr></thead>
            <tbody>
              {Object.entries(v.summary.counts).map(([k, n]) => (
                <tr key={k}><td>{k}</td><td className="num">{n}</td></tr>
              ))}
            </tbody>
          </table>
          <div className={`turn-card ${viewing ? "viewing" : ""}`}>
            <IfcTurnCard turnId={turnId(v)} height={cardHeight} liveOn={latest ? "visible" : "hover"} onExpand={() => onView(v)} />
            <Resizer className="resizer-card" label="Version card height" onReset={onResetCard}
              height={{ value: cardHeight, dir: 1, ...PANEL_RANGE.turnCard, onChange: onResizeCard }} />
          </div>
          <div className="version-bar">
            <span className="muted">{v.number === head ? "Current version" : `Head is v${head}`}</span>
            <span className="grow" />
            <button onClick={() => onView(v)} disabled={viewing}><Eye size={13} /> {viewing ? "In workspace" : "View"}</button>
            {v.number !== head && (
              <button onClick={() => onRestore(v.number)} disabled={busy} title="Make this version the head again">
                <RotateCcw size={13} /> Restore
              </button>
            )}
          </div>
        </div>
      )}

      {run.stage === "done" && v && (
        <p>
          Version {v.number}: {v.summary.storeys.length} storeys and {v.summary.elements} elements
          {v.summary.schema ? <>, as valid {v.summary.schema}</> : null}.
          {v.summary.spaces.length > 0 && <> Rooms: {v.summary.spaces.join(", ")}.</>}
        </p>
      )}
      {run.stage === "error" && <div className="error-card"><X size={15} /> {run.error}</div>}
    </div>
  );
}

const CHECK_MARK: Record<string, string> = { met: "✓", unmet: "✗", unsupported: "–", skipped: "?" };

/** The design layer's requirement checks: what was asked for, and whether the model has it. */
function Checklist({ checks }: { checks: NonNullable<Version["checks"]> }) {
  const met = checks.filter((c) => c.status === "met").length;
  const checkable = checks.filter((c) => c.status === "met" || c.status === "unmet").length;
  const unmet = checks.filter((c) => c.status === "unmet").length;
  return (
    <Collapsible icon={<ListChecks size={16} />}
      title={`Requirements: ${met} of ${checkable} met${unmet ? ` · ${unmet} missing` : ""}`}>
      <ul className="req-list">
        {checks.map((c, i) => (
          <li key={i} className={c.status}>
            <span className="mark">{CHECK_MARK[c.status] ?? "?"}</span>
            <span>{c.text}{c.detail && c.status !== "met" ? <small className="muted"> — {c.detail}</small> : null}</span>
          </li>
        ))}
      </ul>
    </Collapsible>
  );
}

/** Fetched on first open: the spec lives on the backend, not in the session. */
function SpecView({ v }: { v: Version }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    getSpec(v.project_id, v.number).then(
      (r) => setText(JSON.stringify(r.spec, null, 2)),
      (e) => setText(`Couldn't load the spec: ${e instanceof Error ? e.message : e}`),
    );
  }, [v.project_id, v.number]);
  return <pre className="code">{text ?? "Loading…"}</pre>;
}

function Collapsible({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="block">
      <button className="block-head" onClick={() => setOpen(!open)}>
        {icon}
        <span>{title}</span>
        <span className="grow" />
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {open && <div className="block-body">{children}</div>}
    </div>
  );
}
