import { Check, ChevronDown, ChevronUp, Code, Database, LoaderCircle, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Message, Run, Session } from "../state/sessions";
import { Composer } from "./Composer";

interface Props {
  session: Session;
  busy: boolean;
  planners: string[];
  planner: string;
  setPlanner: (p: string) => void;
  onSubmit: (text: string) => void;
  onAttach: () => void;
}

export function Assistant({ session, busy, ...composer }: Props) {
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
        {session.messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} m={m} /> : <AssistantMessage key={m.id} m={m} />))}
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

const STEPS: [Run["stage"], string][] = [
  ["planning", "Interpreting the prompt"],
  ["building", "Building IFC with IfcOpenShell"],
  ["loading", "Loading the model"],
];

function AssistantMessage({ m }: { m: Message }) {
  const run = m.run;
  if (!run) return <div className="answer"><p>{m.text}</p></div>;
  const idx = STEPS.findIndex(([s]) => s === run.stage);

  return (
    <div className="answer">
      {m.text && <p>{m.text}</p>}

      {run.plan && (
        <Collapsible icon={<Sparkles size={16} />} title={`Interpreted with the ${run.plan.planner} planner`}>
          <ul className="notes">{run.plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Collapsible>
      )}
      {run.plan && (
        <Collapsible icon={<Code size={16} />} title="Structured BIM instructions">
          <pre className="code">{JSON.stringify(run.plan.spec, null, 2)}</pre>
        </Collapsible>
      )}

      {run.stage !== "done" && run.stage !== "error" && (
        <ol className="progress">
          {STEPS.map(([s, label], i) => (
            <li key={s} className={i < idx ? "done" : i === idx ? "active" : ""}>
              {i < idx ? <Check size={15} /> : i === idx ? <LoaderCircle size={15} className="spin" /> : <span className="dot-sm" />}
              {label}
            </li>
          ))}
        </ol>
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
