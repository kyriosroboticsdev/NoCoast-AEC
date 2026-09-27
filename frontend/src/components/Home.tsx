import type { Attachment } from "../state/attachments";
import { Composer } from "./Composer";

const SUGGESTIONS: [string, string][] = [
  ["Two-story house", "Create a two-story rectangular house. The first floor should have a kitchen and living room. The second floor should have three bedrooms. Add windows to the exterior walls and a garage."],
  ["Family home + garage", "Create a two-story house with four bedrooms, a garage, and a flat roof."],
  ["Bright bungalow", "Design a modern single storey house with lots of natural light and a front porch."],
  ["Open an IFC file", ""],
];

interface Props {
  busy: boolean;
  planners: string[];
  planner: string | null;
  setPlanner: (p: string) => void;
  onSubmit: (text: string, images: Attachment[]) => void;
  onAttach: () => void;
}

export function Home(p: Props) {
  return (
    <div className="home">
      <h1>What are we building today?</h1>
      <Composer size="hero" {...p} placeholder="Describe a building — storeys, rooms, garage, porch…" />
      <div className="suggestions">
        {SUGGESTIONS.map(([label, prompt]) => (
          <button key={label} className="suggestion" onClick={() => (prompt ? p.onSubmit(prompt, []) : p.onAttach())}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
