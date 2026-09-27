import { useEffect, useState } from "react";
import { History, Play } from "lucide-react";
import * as api from "../api/client";
import type { Attachment } from "../state/attachments";
import { Composer } from "./Composer";

const SUGGESTIONS: [string, string][] = [
  ["Architecture studio", "An architecture studio for 40 people: open design studio, two meeting rooms, a model shop, kitchen and WCs, over two floors."],
  ["Primary school", "A primary school with 6 classrooms, a hall, offices, WCs and a staff room."],
  ["Three-storey offices", "A three storey office building with open plan offices, meeting rooms, a reception and a cafe on the ground floor."],
  ["Family house", "A two storey family house with an open kitchen and living room, three bedrooms, two bathrooms, a study and a garage."],
  ["Open an IFC file", ""],
];
const SHOWN_RUNS = 4;

interface Props {
  busy: boolean;
  planners: string[];
  planner: string | null;
  setPlanner: (p: string) => void;
  onSubmit: (text: string, images: Attachment[]) => void;
  onAttach: () => void;
  onReplay: (run: api.RunSummary) => void;
  backendUp: boolean | null;
}

const minutes = (s: number) => (s >= 90 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`);

export function Home({ onReplay, backendUp, ...p }: Props) {
  const [runs, setRuns] = useState<api.RunSummary[]>([]);
  useEffect(() => {
    if (!backendUp) return;
    // Runs by a real model make the best replays; the offline mock is quick enough to run live.
    api.listRuns().then((all) => setRuns(all.filter((r) => r.llm !== "mock").slice(0, SHOWN_RUNS))).catch(() => setRuns([]));
  }, [backendUp]);

  return (
    <div className="home">
      <h1>What are we building today?</h1>
      <p className="home-sub">From a brief to an IFC model, a code review against the IBC, a drawing set with DXF plans and Excel schedules, and a cost and carbon plan.</p>
      <Composer size="hero" {...p} placeholder="Describe a building — use, storeys, rooms, occupants…" />
      <div className="suggestions">
        {SUGGESTIONS.map(([label, prompt]) => (
          <button key={label} className="suggestion" onClick={() => (prompt ? p.onSubmit(prompt, []) : p.onAttach())}>
            {label}
          </button>
        ))}
      </div>
      {runs.length > 0 && (
        <section className="replays">
          <h2><History size={14} /> Recorded runs</h2>
          {runs.map((r) => (
            <button key={`${r.project}:${r.version}`} className="replay" disabled={p.busy} onClick={() => onReplay(r)}
              title="Play the recorded run back: the same reasoning, previews and deliverables, without calling the model">
              <Play size={14} />
              <span className="replay-prompt">{r.prompt}</span>
              <span className="replay-meta">{r.llm} · {minutes(r.duration)} live</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
