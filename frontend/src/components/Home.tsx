import { useEffect, useState } from "react";
import { History, Play } from "lucide-react";
import * as api from "../api/client";
import type { Attachment } from "../state/attachments";
import { Composer } from "./Composer";

const SUGGESTIONS: [string, string][] = [
  ["Highway bridge", "A two-span highway bridge over a river, 80 m in all: two lanes each way, a sidewalk on one side, and approach embankments."],
  ["Access road", "A 1.2 km two-lane access road with a roundabout at the junction, drainage ditches, and a culvert where a farm track crosses."],
  ["Data center", "A 10 MW data center: a data hall, electrical and UPS rooms, a generator yard, offices for 40 people, and a loading dock."],
  ["Rail station", "A two-platform rail station with a footbridge between the platforms, a ticket hall, waiting rooms, and a bus interchange."],
  ["Treatment plant", "A water treatment plant: an intake, clarifiers, a filter building, chemical storage, and an operations office."],
  ["Substation", "A 132 kV substation: transformer bays, a control building, a switchyard, and a perimeter access road."],
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
      <h1>What are we designing today?</h1>
      <p className="home-sub">From a brief to an IFC model, a code review, drawings with DXF plans and Excel schedules, and a cost and carbon plan.</p>
      <Composer size="hero" {...p} placeholder="Describe an asset — a bridge, a road, a data center, a building…" />
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
