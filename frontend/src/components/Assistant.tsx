import { ChevronDown, ChevronUp, Code, Database, Eye, RotateCcw, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Message, Session } from "../state/sessions";
import { IfcTurnCard } from "@nocoast/ifc-viewer";
import type { Version } from "../api/client";
import { turnId } from "../turns";
import { Composer } from "./Composer";
import { Reasoning } from "./Reasoning";

interface Props {
  session: Session;
  busy: boolean;
  planners: string[];
  planner: string;
  setPlanner: (p: string) => void;
  onSubmit: (text: string) => void;
  onAttach: () => void;
  /** name of the model in the viewer (e.g. "v3.ifc") when it belongs to this session */
  viewing: string | null;
  onView: (v: Version) => void;
  onRestore: (versionNumber: number) => void;
}

export function Assistant({ session, busy, viewing, onView, onRestore, ...composer }: Props) {
  const head = [...session.messages].reverse().find((m) => m.run?.version)?.run?.version?.number ?? null;
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    const el = scroller.current;
    if (el && atBottom) el.scrollTop = el.scrollHeight;
  }, [session.messages, atBottom]);

  return (
    <aside className="assistant">
      <div className="chat" ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
        }}>
        {session.messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} m={m} /> : (
          <AssistantMessage key={m.id} m={m} head={head} busy={busy} viewing={viewing} onView={onView} onRestore={onRestore} />
        )))}
      </div>
      {!atBottom && (
        <button className="jump" onClick={() => setAtBottom(true)} title="Jump to latest">
          <ChevronDown size={18} />
        </button>
      )}
      <div className="dock">
        <Composer size="dock" busy={busy} placeholder="Ask for another building…" {...composer} />
      </div>
    </aside>
  );
}

function UserBubble({ m }: { m: Message }) {
  return <div className="bubble">{m.text}</div>;
}

function AssistantMessage({ m, head, busy, viewing, onView, onRestore }: {
  m: Message; head: number | null; busy: boolean; viewing: string | null;
  onView: (v: Version) => void; onRestore: (n: number) => void;
}) {
  const run = m.run;
  if (!run) return <div className="answer"><p>{m.text}</p></div>;
  const v = run.version;

  return (
    <div className="answer">
      {m.text && <p>{m.text}</p>}
      <Reasoning run={run} />

      {run.plan && !run.steps?.length && ( // older sessions without a live trace
        <Collapsible icon={<Sparkles size={16} />} title={`Interpreted with the ${run.plan.planner} planner`}>
          <ul className="notes">{run.plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Collapsible>
      )}
      {run.plan && (
        <Collapsible icon={<Code size={16} />} title="Structured BIM instructions">
          <pre className="code">{JSON.stringify(run.plan.spec, null, 2)}</pre>
        </Collapsible>
      )}

      {run.build && (
        <div className="results">
          <div className="results-head">
            <span className="results-icon"><Database size={18} /></span>
            <span className="results-title">
              <b>Built IFC</b>
              <small>From {run.build.ifc_url}</small>
            </span>
            <span className="chip">{run.build.summary.elements} elements</span>
          </div>
          <table className="grid">
            <thead><tr><th>IFC class</th><th className="num">Count</th></tr></thead>
            <tbody>
              {Object.entries(run.build.summary.counts).map(([k, v]) => (
                <tr key={k}><td>{k}</td><td className="num">{v}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {run.stage === "done" && run.build && run.plan && (
        <p>
          Here's <b>{run.plan.spec.building.name}</b>: {run.build.summary.storeys.length} storeys and{" "}
          {run.build.summary.elements} elements, as valid {run.build.summary.schema}, built in {run.build.seconds}s.
          {run.build.summary.spaces.length > 0 && <> Rooms: {run.build.summary.spaces.join(", ")}.</>}
        </p>
      )}
      {v && run.stage === "done" && (
        <div className={`version-card ${viewing === `v${v.number}.ifc` ? "viewing" : ""}`}>
          <div className="version-head">
            <span className="version-badge">v{v.number}</span>
            <span className="version-meta">
              {v.mode}{v.llm ? ` · ${v.llm}` : ""} · {v.summary.elements} elements · {v.summary.storeys.length} storeys
            </span>
            {v.number === head && <span className="chip">latest</span>}
          </div>
          <IfcTurnCard turnId={turnId(v)} height={170} liveOn={v.number === head ? "visible" : "hover"} onExpand={() => onView(v)} />
          <div className="version-actions">
            <button className="btn ghost" onClick={() => onView(v)} disabled={viewing === `v${v.number}.ifc`}>
              <Eye size={15} /> {viewing === `v${v.number}.ifc` ? "In viewer" : "View"}
            </button>
            {v.number !== head && (
              <button className="btn ghost" onClick={() => onRestore(v.number)} disabled={busy} title="Make this the latest version again">
                <RotateCcw size={15} /> Restore
              </button>
            )}
          </div>
          {v.notes.length > 0 && (
            <ul className="notes small">{v.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
          )}
        </div>
      )}
      {run.stage === "error" && <div className="error-card"><X size={15} /> {run.error}</div>}
    </div>
  );
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
