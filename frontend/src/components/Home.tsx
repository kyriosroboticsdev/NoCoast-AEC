import { useEffect, useState } from "react";
import { History, Play } from "lucide-react";
import * as api from "../api/client";
import type { Attachment } from "../state/attachments";
import { Composer } from "./Composer";

type Suggestion =
  | { kind: "sample"; label: string; name: string; url: string }
  | { kind: "prompt"; label: string; prompt: string }
  | { kind: "file"; label: string };

const SUGGESTIONS: Suggestion[] = [
  { kind: "sample", label: "Rome", name: "rome_colosseum_valley.ifc", url: "samples/rome_colosseum_valley.ifc" },
  { kind: "prompt", label: "Highway bridge", prompt: "A two-span highway bridge over a river, 80 m in all: two lanes each way, a sidewalk on one side, and approach embankments." },
  { kind: "prompt", label: "Access road", prompt: "A 1.2 km two-lane access road with a roundabout at the junction, drainage ditches, and a culvert where a farm track crosses." },
  { kind: "prompt", label: "Data center", prompt: "A 10 MW data center: a data hall, electrical and UPS rooms, a generator yard, offices for 40 people, and a loading dock." },
  { kind: "prompt", label: "Rail station", prompt: "A two-platform rail station with a footbridge between the platforms, a ticket hall, waiting rooms, and a bus interchange." },
  { kind: "prompt", label: "Treatment plant", prompt: "A water treatment plant: an intake, clarifiers, a filter building, chemical storage, and an operations office." },
  { kind: "prompt", label: "Substation", prompt: "A 132 kV substation: transformer bays, a control building, a switchyard, and a perimeter access road." },
  { kind: "file", label: "Open an IFC file" },
];
const SHOWN_RUNS = 4;

interface Props {
  busy: boolean;
  planners: string[];
  planner: string | null;
  setPlanner: (p: string) => void;
  onSubmit: (text: string, images: Attachment[]) => void;
  onAttach: () => void;
  onOpenSample: (name: string, url: string) => void;
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
      <Composer size="hero" {...p} placeholder="Describe an asset — a bridge, a road, a data center, a building…" />
      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s.label} className="suggestion" title={s.kind === "sample" ? "Open the Colosseum valley, c. 320 AD" : undefined}
            onClick={() => {
              switch (s.kind) {
                case "prompt":
                  p.onSubmit(s.prompt, []);
                  return;
                case "sample":
                  p.onOpenSample(s.name, s.url);
                  return;
                case "file":
                  p.onAttach();
                  return;
                default: {
                  const _never: never = s;
                  return _never;
                }
              }
            }}>
            {s.label}
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
