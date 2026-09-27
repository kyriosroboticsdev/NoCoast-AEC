// Turns the backend's pipeline stream into the assistant's reasoning trace, in plain words.
//
// Stages (backend README §4.5): requirements · focus · build · llm · stream · step · partial ·
// verify · compile · done · error. Each storey the model lays out becomes a "layer" step; the
// doors, windows, stairs and furniture that follow nest under the storey they land on. Previews
// (`partial`) are handed to the caller so the viewer can show the building as it grows.
//
// Wording follows the design-layer UI on the backend branch (friendly mode). The older stage names
// (program | edit | apply | solve) are still understood for older backends.
import type { StageEvent } from "../api/client";
import { uid, type TraceStep } from "./sessions";

type Step = Record<string, unknown>;
type Phase = TraceStep["phase"];

const SIDES: Record<string, string> = { N: "north", S: "south", E: "east", W: "west", center: "middle" };
const side = (s: unknown) => SIDES[String(s)] ?? String(s ?? "");
const kindName = (k: unknown) => String(k ?? "").replace(/_/g, " ");
const cap = (s: string) => s.replace(/^\w/, (c) => c.toUpperCase());
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function levelName(id: unknown): string {
  if (typeof id !== "string") return "the ground floor";
  if (/^B\d+$/i.test(id)) {
    const b = Number(id.slice(1));
    return b === 1 ? "the basement" : `basement level ${b}`;
  }
  const n = Number(id.replace(/^L/i, ""));
  return n === 1 ? "the ground floor" : n === 2 ? "the first floor" : `level ${n}`;
}

const LEGACY: Record<string, { phase: Phase; title: string }> = {
  program: { phase: "plan", title: "Designing the building program" },
  edit: { phase: "plan", title: "Working out the edit" },
  apply: { phase: "validate", title: "Applying the operations" },
  solve: { phase: "build", title: "Solving the layout" },
  research: { phase: "plan", title: "Researching the brick library" },
  tool: { phase: "plan", title: "Looking up bricks and skills" },
  coordinate: { phase: "validate", title: "Coordinating clashes, services and structure" },
  look: { phase: "validate", title: "Looking at the model" },
};

export interface Preview {
  url: string;
  label: string;
}

interface Open {
  step: TraceStep;
  t0: number;
}

export function stageTracer(push: (step: TraceStep) => void, hooks: { onPreview?: (p: Preview) => void; onStep?: (step: Step, ok: boolean) => void } = {}) {
  const rooms: Record<string, string> = {}; // room id / slug → display name, learned from the steps
  const roomLevel: Record<string, string> = {};
  let top: Open | null = null; // the running top-level step
  let layerOf: Record<string, Open> = {}; // storey id → its layer step
  let lastLayer: Open | null = null;
  let applied = 0;
  let skipped = 0;
  let previews = 0;

  const roomName = (id: unknown) => {
    if (typeof id !== "string") return "the room";
    if (rooms[id]) return `the ${rooms[id]}`;
    if (id === "outside") return "outside";
    return `the ${id.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}`;
  };

  const open = (phase: Phase, title: string, detail: string | null = null, extra: Partial<TraceStep> = {}): Open => {
    const step: TraceStep = { id: uid(), parent: null, phase, title, detail, status: "running", ...extra };
    push(step);
    return { step, t0: performance.now() };
  };
  const finish = (o: Open | null, patch: Partial<TraceStep> = {}) => {
    if (!o || o.step.status !== "running") return;
    o.step = { ...o.step, status: "done", ms: Math.round(performance.now() - o.t0), ...patch };
    push(o.step);
  };
  const child = (parent: Open, title: string, detail: string | null, status: TraceStep["status"] = "done") =>
    push({ id: uid(), parent: parent.step.id, phase: parent.step.phase, title, detail, status });
  const setDetail = (o: Open | null, detail: string) => {
    if (!o) return;
    o.step = { ...o.step, detail };
    push(o.step);
  };
  const closeLayers = () => {
    for (const l of Object.values(layerOf)) finish(l);
  };
  const closeTop = () => {
    finish(top);
    top = null;
  };
  const startTop = (phase: Phase, title: string, detail: string | null = null) => {
    closeTop();
    top = open(phase, title, detail);
    return top;
  };

  function learn(step: Step) {
    if (step.step === "room" && typeof step.name === "string") {
      const id = typeof step.id === "string" ? step.id : slug(step.name);
      rooms[id] = rooms[slug(step.name)] = step.name;
      if (typeof step.level === "string") roomLevel[id] = step.level;
    }
    if (step.step === "layout" && Array.isArray(step.rooms)) {
      for (const r of step.rooms as { id?: string; name?: string }[]) {
        if (typeof r.name !== "string") continue;
        rooms[slug(r.name)] = r.name;
        if (r.id) rooms[r.id] = r.name;
        if (typeof step.level === "string") {
          roomLevel[slug(r.name)] = step.level;
          if (r.id) roomLevel[r.id] = step.level;
        }
      }
    }
  }

  function describe(step: Step, message: string): string {
    const rect = Array.isArray(step.rect) ? (step.rect as number[]) : null;
    const size = rect ? ` (${rect[2]} × ${rect[3]} m)` : "";
    const name = typeof step.name === "string" ? step.name : "";
    switch (step.step) {
      case "building": return name ? `Calling the building “${name}”` : "Describing the building";
      case "level": return `Adding ${levelName(step.id ?? step.level)}${step.height ? `, ${step.height} m high` : ""}`;
      case "room": return `${message.includes("updated") ? "Moving" : "Adding"} the ${name || roomName(step.id).replace(/^the /, "")} on ${levelName(step.level)}${size}`;
      case "layout": {
        const names = Array.isArray(step.rooms) ? (step.rooms as { name?: string }[]).map((r) => r.name).filter(Boolean) : [];
        const verb = message.includes("; removed") || message.includes("updated") ? "Rearranging" : "Laying out";
        return `${verb} ${levelName(step.level)}${names.length ? `: ${names.join(", ")}` : ""}`;
      }
      case "door": {
        const to = String(step.to ?? "outside");
        if (to === "outside" || to === "exterior") {
          return `${step.kind === "garage" ? "Garage door" : "Entrance door"} on the ${side(step.side) || "outer"} side of ${roomName(step.room)}`;
        }
        return `Door between ${roomName(step.room)} and ${roomName(to)}${step.kind && step.kind !== "single" ? ` (${kindName(step.kind)})` : ""}`;
      }
      case "window": return cap(`${step.kind && step.kind !== "standard" ? `${kindName(step.kind)} window` : "window"} on the ${side(step.side)} wall of ${roomName(step.room)}`);
      case "stair": return `Stairs in ${roomName(step.room)}, along the ${side(step.side ?? "W")} wall`;
      case "furniture": return `A ${kindName(step.kind)} in ${roomName(step.room)}${step.side && step.side !== "center" ? `, against the ${side(step.side)} wall` : ""}`;
      case "balcony": return `Balcony on the ${side(step.side)} side of ${roomName(step.room)}`;
      case "porch": return `Porch along the ${side(step.side ?? "S")} side`;
      case "roof": return `${cap(String(step.kind ?? "flat"))} roof${step.pitch ? ` at ${step.pitch}°` : ""}`;
      case "material": return `${cap(String(step.material ?? step.kind ?? ""))} exterior walls`;
      case "column": return `A column on ${levelName(step.level)}`;
      case "element": return `${cap(kindName(step.name ?? step.kind ?? "element"))}${step.name ? ` (free ${kindName(step.kind)})` : ""} on ${levelName(step.level)}${step.elevation ? `, ${step.elevation} m up` : ""}`;
      case "mep": case "plumbing": case "electrical": return message || "Routing services";
      case "remove": return `Removing ${roomName(step.id)}`;
      case "note": return String(step.text ?? "");
      default: return message || "A step";
    }
  }

  const reason = (error: unknown) =>
    String(error ?? "")
      .replace(/^applying this step makes the design unbuildable: /, "")
      .replace(/^(door|window|stair|balcony|furniture|room|layout|level|remove)\b[^:]*: /, "");

  /** Where a step lands: the storey's layer when we know it, else the running top step. */
  function parentFor(step: Step): Open | null {
    const level = typeof step.level === "string" ? step.level
      : typeof step.room === "string" ? roomLevel[step.room] : undefined;
    return (level && layerOf[level]) || lastLayer || top;
  }

  function onStep(e: StageEvent) {
    const d = e.data ?? {};
    const step = (d.step as Step) ?? {};
    const ok = d.ok !== false;
    if (ok) learn(step);
    hooks.onStep?.(step, ok);
    const what = describe(step, e.message);
    // Steps before the first storey (building, levels) gather under one build step; after that they
    // nest under their storey's layer, so no extra top-level step is needed.
    if (!lastLayer && (!top || top.step.phase !== "build")) startTop("build", "Laying out the building");

    if (ok && step.step === "layout" && typeof step.level === "string") {
      // One layer per storey. Re-laying out a storey updates its layer rather than adding one.
      const existing = layerOf[step.level];
      if (existing) {
        existing.step = { ...existing.step, title: what, status: "running" };
        push(existing.step);
        lastLayer = existing;
      } else {
        closeTop(); // storeys are top-level so the layer stack can count them
        lastLayer = layerOf[step.level] = open("build", what, null, { layer: true });
      }
      applied++;
      return;
    }
    if (ok && step.step === "roof") closeLayers();

    const parent = parentFor(step) ?? startTop("build", "Building the model");
    if (ok) {
      applied++;
      const pruned = e.message.includes("; removed ")
        ? e.message.split("; ").slice(1).map((s) => s.replace(/^removed (\w+) ([\w-]+): /, "dropped a $1 because ")).join("\n")
        : null;
      child(parent, what, pruned);
    } else {
      skipped++;
      child(parent, `Skipped: ${what.replace(/^\w/, (c) => c.toLowerCase())}`, reason(d.error), "error");
    }
  }

  return {
    event(e: StageEvent) {
      const d = e.data ?? {};
      switch (e.stage) {
        case "requirements": {
          if (!Array.isArray(d.requirements)) {
            if (!top || top.step.title !== "Reading your request") startTop("plan", "Reading your request");
            return;
          }
          const reqs = d.requirements as { text: string; supported?: boolean }[];
          const unsupported = reqs.filter((r) => r.supported === false);
          const title = `I understood ${plural(reqs.length, "thing")} to build${unsupported.length ? `, ${unsupported.length} of which I can't do` : ""}`;
          const t = top && top.step.title === "Reading your request" ? top : startTop("plan", "Reading your request");
          for (const r of reqs) child(t, r.supported === false ? `Can't do: ${r.text}` : r.text, null, r.supported === false ? "error" : "done");
          finish(t, { title, detail: null });
          top = null;
          return;
        }
        case "focus":
          child(top ?? startTop("plan", "Reading your request"),
            `Working on ${String(d.text ?? "the selection").replace(/ \((wall|room) id [^)]*\)/, "")}`, null);
          return;
        case "build": {
          const problems = (d.problems as string[]) ?? [];
          const unmet = (d.unmet as string[]) ?? [];
          const title = problems.length ? `Fixing ${plural(problems.length, "step")} that didn't work`
            : unmet.length ? `Going back for ${plural(unmet.length, "thing")} still missing`
            : e.message.startsWith("editing") ? "Working out what to change" : "Laying out the building";
          startTop("build", title, unmet.length ? unmet.map((x) => `• ${x}`).join("\n") : null);
          return;
        }
        case "llm":
          if (d.provider && top) setDetail(top, `asking ${d.provider}${d.model ? ` ${d.model}` : ""}…`);
          return;
        case "stream":
          if (e.message.startsWith("waiting")) setDetail(lastLayer ?? top, e.message);
          return;
        case "step":
          onStep(e);
          if (top) setDetail(top, `${plural(applied, "step")} applied${skipped ? ` · ${skipped} skipped` : ""}${previews ? ` · preview ${previews}` : ""}`);
          return;
        case "partial":
          if (typeof d.ifc_url === "string") {
            previews++;
            hooks.onPreview?.({ url: d.ifc_url, label: `Preview ${d.preview ?? previews} · ${d.elements ?? "?"} elements` });
          }
          return;
        case "verify": {
          closeLayers();
          const rs = (d.results as { text: string; status: string; detail: string }[]) ?? [];
          const met = rs.filter((r) => r.status === "met").length;
          const checkable = rs.filter((r) => r.status === "met" || r.status === "unmet").length;
          const t = startTop("validate", rs.length ? `Checked the result: ${met} of ${checkable} requirements met` : "Checking the result");
          for (const r of rs) {
            if (r.status === "met" || r.status === "unmet") child(t, `${r.text}`, r.status === "unmet" ? r.detail : null, r.status === "unmet" ? "error" : "done");
          }
          closeTop();
          return;
        }
        case "compile":
          closeLayers();
          startTop("build", "Finishing the model", "compiling IFC");
          return;
        case "done":
          closeLayers();
          closeTop();
          return;
        case "error":
          return; // the stream throws right after; fail() reports it once
        default: {
          const info = LEGACY[e.stage];
          if (!info) return;
          const errors = (d.errors as string[] | undefined) ?? [];
          if (top && top.step.title === info.title && errors.length) {
            child(top, cap(e.message), `fixing: ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}`, "running");
            return;
          }
          startTop(info.phase, info.title, e.message.toLowerCase() === info.title.toLowerCase() ? null : e.message);
        }
      }
    },
    /** Mark whatever was running as failed (the error shows on the innermost step). */
    fail(message: string) {
      const target = top ?? lastLayer;
      if (target) {
        target.step = { ...target.step, status: "error", error: message, ms: Math.round(performance.now() - target.t0) };
        push(target.step);
      }
      closeLayers();
      top = null;
    },
  };
}
