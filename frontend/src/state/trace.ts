// Turns the backend's pipeline stream into the assistant's reasoning trace: a design log, grouped
// the way a project actually runs — brief, massing, floor plates, circulation, envelope, structure,
// fit-out, review, IFC, code review, cost and carbon, drawing issue.
//
// Stages (backend README §4.5): requirements · focus · approach · build · llm · stream · draft ·
// step · partial · verify · compile · code · estimate · deliver · done · error.
//
// The backend does the narration now: a `step` event carries `headline` (a sentence about the
// building), `why` (the model's own reasoning) and `facts` (areas, dimensions, running totals), and
// says which `phase` it belongs to. `describe()` below is the fallback for older backends that only
// sent the raw step. Previews (`partial`) are handed to the caller so the viewer can show the
// building as it grows; `draft` events are handed over as the live "writing…" line.
import type { StageEvent } from "../api/client";
import { uid, type TracePhase, type TraceStep } from "./sessions";

type Step = Record<string, unknown>;

const SIDES: Record<string, string> = { N: "north", S: "south", E: "east", W: "west", center: "middle" };
const side = (s: unknown) => SIDES[String(s)] ?? String(s ?? "");
const kindName = (k: unknown) => String(k ?? "").replace(/_/g, " ");
const cap = (s: string) => s.replace(/^\w/, (c) => c.toUpperCase());
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Heading for each phase of the work; the trace shows one group per phase, in this order. */
export const PHASE_TITLES: Record<string, string> = {
  brief: "Reading the brief",
  research: "Looking up parts and precedents",
  concept: "Design thinking",
  massing: "Massing and storey heights",
  plan: "Planning the floor plates",
  circulation: "Circulation and access",
  envelope: "Envelope, openings and roof",
  structure: "Structure and site works",
  fitout: "Fit-out and equipment",
  review: "Checking the model against the brief",
  output: "Compiling the IFC model",
  code: "Code review",
  cost: "Cost and carbon",
  issue: "Issuing the drawing set",
};

type Tone = NonNullable<TraceStep["tone"]>;
interface Finding {
  title: string; reference: string; status: Tone; value: string; target: string; detail: string; advice: string;
  fix?: number;
}

const money = (v: number) => (v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : `$${Math.round(v / 1e3).toLocaleString()}k`);
const PHASE_ORDER = Object.keys(PHASE_TITLES);
/** Phases whose groups collect the build's moves, and so carry its running tally. */
const BUILDING = new Set<string>(["massing", "plan", "circulation", "envelope", "structure", "fitout"]);

export function levelName(id: unknown): string {
  if (typeof id !== "string") return "the ground floor";
  if (/^B\d+$/i.test(id)) {
    const b = Number(id.slice(1));
    return b === 1 ? "the basement" : `basement level ${b}`;
  }
  const n = Number(id.replace(/^L/i, ""));
  return n === 1 ? "the ground floor" : n === 2 ? "the first floor" : `level ${n}`;
}

const LEGACY: Record<string, { phase: TracePhase; title: string }> = {
  program: { phase: "brief", title: "Reading the brief" },
  edit: { phase: "plan", title: "Working out the edit" },
  apply: { phase: "review", title: "Applying the operations" },
  solve: { phase: "plan", title: "Solving the layout" },
};

export interface Preview {
  url: string;
  label: string;
}

interface Open {
  step: TraceStep;
  t0: number;
}

interface Hooks {
  onPreview?: (p: Preview) => void;
  onStep?: (step: Step, ok: boolean) => void;
  /** The design strategy, as soon as the model has written it. */
  onApproach?: (text: string) => void;
  /** What the model is writing right now; null when it has landed. */
  onLive?: (text: string | null) => void;
}

/**
 * "16 m² · 4 × 4 m" — the numbers worth putting next to a line. Only for the moves whose subject is
 * a piece of floor area; hanging the room's area off every door and chair would just be noise.
 */
function metricOf(kind: string, facts: Record<string, unknown> | undefined): string | null {
  if (!facts || !["room", "layout"].includes(kind)) return null;
  const bits: string[] = [];
  const area = facts.plate_area ?? facts.area;
  if (typeof area === "number" && area > 0) bits.push(`${Math.round(area)} m²`);
  if (typeof facts.width === "number" && typeof facts.depth === "number") bits.push(`${facts.width} × ${facts.depth} m`);
  return bits.join(" · ") || null;
}

/**
 * A research call as a line in the design log: "Specified the school desk — 1.2 × 0.55 × 0.75 m"
 * rather than the raw call and the brick card it returned. Returns the title and any detail worth
 * keeping (a check's findings); the full card is for the model, not the reader.
 */
export function narrateTool(tool: string, args: Record<string, unknown>, result: string): { title: string; detail: string | null; failed: boolean } {
  const first = result.split("\n")[0] ?? "";
  const failed = result.startsWith("error:") || /^(no |not valid|invalid)/.test(first);
  const id = kindName(args.id);
  switch (tool) {
    case "get_brick": {
      if (failed) return { title: `No ${id} in the library — to be modelled as a purpose-made part`, detail: null, failed: false };
      const name = /—\s*([^[]+?)\s*\[/.exec(first)?.[1] ?? id;
      const size = /(\d[\d.]*)x(\d[\d.]*)x(\d[\d.]*) m/.exec(first);
      const inSentence = name.replace(/[\w-]+/g, (w) => (w === w.toUpperCase() ? w : w.toLowerCase()));
      return { title: `Specified the ${inSentence}` + (size ? ` — ${size[1]} × ${size[2]} × ${size[3]} m` : ""), detail: null, failed };
    }
    case "get_skill": {
      const topic = /^SKILL [\w-]+:\s*(.+)$/.exec(first)?.[1]?.replace(/\s*\([^)]*\)\s*$/, "");
      return { title: topic ? `Consulted the guidance on ${topic.replace(/^\w/, (c) => c.toLowerCase())}` : `Consulted the ${id} guidance`, detail: null, failed };
    }
    case "search_bricks": {
      const hits = failed ? 0 : result.split("\n").filter(Boolean).length;
      return { title: `Searched the parts library for “${String(args.query ?? args.tag ?? "")}” — ${hits ? `${hits} ${hits === 1 ? "match" : "matches"}` : "nothing suitable"}`, detail: null, failed: false };
    }
    case "list_skills":
      return { title: "Reviewed the index of design guidance", detail: null, failed };
    case "check_asset":
      return { title: failed ? "A purpose-made part failed its check and was redrawn" : "Checked a purpose-made part builds", detail: failed ? first : null, failed };
    case "check_design":
    case "structure_report": {
      const what = tool === "check_design" ? "Coordination check" : "Structural check";
      const lines = result.split("\n").filter(Boolean);
      const clean = lines.length === 0 || /^no issues|nothing to check/.test(first);
      return { title: clean ? `${what}: no issues` : `${what}: ${plural(lines.length, "finding")}`, detail: clean ? null : lines.slice(0, 3).join("\n"), failed: false };
    }
    default:
      return { title: cap(`${tool.replace(/_/g, " ")}${id ? ` ${id}` : ""}`), detail: first.slice(0, 200) || null, failed };
  }
}

export function stageTracer(push: (step: TraceStep) => void, hooks: Hooks = {}) {
  const rooms: Record<string, string> = {}; // room id / slug → display name, learned from the steps
  const roomLevel: Record<string, string> = {};
  const groups: Record<string, Open> = {}; // phase → its group step
  const layerOf: Record<string, Open> = {}; // storey id → its floor-plate step inside the plan group
  let lastGroup: Open | null = null;
  const tally: Record<string, { applied: number; skipped: number }> = {}; // phase → its moves
  let applied = 0;
  let skipped = 0;
  let previews = 0;
  let gfa = 0;

  const roomName = (id: unknown) => {
    if (typeof id !== "string") return "the room";
    if (rooms[id]) return `the ${rooms[id]}`;
    if (id === "outside") return "outside";
    return `the ${id.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}`;
  };

  const open = (phase: TracePhase, title: string, detail: string | null = null, extra: Partial<TraceStep> = {}): Open => {
    const step: TraceStep = { id: uid(), parent: null, phase, title, detail, status: "running", ...extra };
    push(step);
    return { step, t0: performance.now() };
  };
  const finish = (o: Open | null, patch: Partial<TraceStep> = {}) => {
    if (!o || o.step.status !== "running") return;
    o.step = { ...o.step, status: "done", ms: Math.round(performance.now() - o.t0), ...patch };
    push(o.step);
  };
  const child = (parent: Open, title: string, detail: string | null, status: TraceStep["status"] = "done",
                 extra: Partial<TraceStep> = {}) =>
    push({ id: uid(), parent: parent.step.id, phase: parent.step.phase, title, detail, status, ...extra });
  const setDetail = (o: Open | null, detail: string) => {
    if (!o) return;
    o.step = { ...o.step, detail };
    push(o.step);
  };

  /** The group for a phase: opened the first time it is needed, reopened if a later step belongs to it. */
  const group = (phase: string, title?: string): Open => {
    const existing = groups[phase];
    if (existing) {
      if (existing.step.status !== "running") {
        existing.step = { ...existing.step, status: "running" };
        push(existing.step);
      }
      if (title && title !== existing.step.title) {
        existing.step = { ...existing.step, title };
        push(existing.step);
      }
      lastGroup = existing;
      return existing;
    }
    // Finish groups that come earlier in the run, so only the current one spins.
    const rank = PHASE_ORDER.indexOf(phase);
    for (const [name, g] of Object.entries(groups)) if (PHASE_ORDER.indexOf(name) < rank) finish(g);
    const created = open(phase as TracePhase, title ?? PHASE_TITLES[phase] ?? cap(phase));
    groups[phase] = created;
    lastGroup = created;
    return created;
  };
  const closeAll = () => {
    for (const g of Object.values(groups)) finish(g);
    for (const l of Object.values(layerOf)) finish(l);
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

  /** Narration for backends that don't send a headline (kept so an older backend still reads well). */
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

  /** Phase of a step, when the backend didn't say. */
  const phaseOf = (kind: string): string => ({
    building: "brief", note: "brief", level: "massing", room: "plan", layout: "plan", remove: "plan",
    door: "circulation", stair: "circulation", window: "envelope", balcony: "envelope", porch: "envelope",
    roof: "envelope", material: "envelope", column: "structure", element: "structure", furniture: "fitout",
    custom: "fitout",
  }[kind] ?? "plan");

  const reason = (error: unknown) =>
    String(error ?? "")
      .replace(/^applying this step makes the design unbuildable: /, "")
      .replace(/^(door|window|stair|balcony|furniture|room|layout|level|remove)\b[^:]*: /, "");

  function onStep(e: StageEvent) {
    const d = e.data ?? {};
    const step = (d.step as Step) ?? {};
    const ok = d.ok !== false;
    const facts = d.facts as Record<string, unknown> | undefined;
    const kind = String(step.step ?? "");
    if (ok) learn(step);
    hooks.onStep?.(step, ok);
    hooks.onLive?.(null);
    const what = (typeof d.headline === "string" && d.headline ? d.headline : describe(step, e.message))
      .replace(/^\p{Ll}/u, (c) => c.toUpperCase());
    // A note is the model's own commentary on the design, not part of reading the brief.
    const phase = kind === "note" ? "concept" : String(d.phase ?? facts?.phase ?? phaseOf(kind));
    const why = typeof d.why === "string" ? d.why : null;
    if (typeof facts?.gfa === "number") gfa = facts.gfa;

    // A storey's floor plate is its own block inside the plan group: it is the move people watch for.
    if (ok && kind === "layout" && typeof step.level === "string") {
      const plan = group("plan");
      const existing = layerOf[step.level];
      const patch = { title: what, status: "running" as const, why, metric: metricOf(kind, facts) };
      if (existing) {
        existing.step = { ...existing.step, ...patch };
        push(existing.step);
      } else {
        layerOf[step.level] = open("plan", what, null, { layer: true, parent: plan.step.id, why, metric: metricOf(kind, facts) });
      }
      applied++;
      (tally.plan ??= { applied: 0, skipped: 0 }).applied++;
      return;
    }
    if (ok && kind !== "room") for (const l of Object.values(layerOf)) finish(l);

    // Single rooms belong to their storey's plate when we know which one it is.
    const level = typeof step.level === "string" ? step.level
      : typeof step.room === "string" ? roomLevel[step.room] : undefined;
    const parent = (kind === "room" && level && layerOf[level]) || group(phase);
    const count = (tally[parent.step.phase] ??= { applied: 0, skipped: 0 });
    if (ok) count.applied++;
    else count.skipped++;

    if (ok) {
      applied++;
      const pruned = (d.message as string | undefined)?.includes("; removed ")
        ? String(d.message).split("; ").slice(1).map((s) => s.replace(/^removed (\w+) ([\w-]+): /, "dropped a $1 because ")).join("\n")
        : null;
      child(parent, what, pruned, "done", { why, metric: metricOf(kind, facts) });
    } else {
      skipped++;
      child(parent, `${what} — set aside`, reason(d.error), "error");
    }
  }

  return {
    event(e: StageEvent) {
      const d = e.data ?? {};
      switch (e.stage) {
        case "requirements": {
          const brief = group("brief");
          if (!Array.isArray(d.requirements)) return;
          const reqs = d.requirements as { text: string; supported?: boolean }[];
          const unsupported = reqs.filter((r) => r.supported === false);
          for (const r of reqs) child(brief, r.supported === false ? `Out of scope: ${r.text}` : r.text, null, r.supported === false ? "error" : "done");
          finish(brief, {
            title: `Brief: ${plural(reqs.length, "requirement")}${unsupported.length ? `, ${unsupported.length} outside what I can model` : ""}`,
            detail: null,
          });
          return;
        }
        case "focus":
          child(group("brief"), `Working on ${String(d.text ?? "the selection").replace(/ \((wall|room) id [^)]*\)/, "")}`, null);
          return;
        case "approach":
          if (typeof d.approach === "string") hooks.onApproach?.(d.approach);
          return;
        case "research": {
          // The model reading the brick library and the skills before it starts drawing.
          const g = group("research");
          if (Array.isArray(d.bricks) || Array.isArray(d.skills)) {
            const bricks = (d.bricks as string[] | undefined) ?? [];
            const skills = (d.skills as string[] | undefined) ?? [];
            if (d.chars !== undefined) {
              finish(g, { title: `Read ${plural(bricks.length, "part")} and ${plural(skills.length, "playbook")}`, detail: null });
              return;
            }
          }
          setDetail(g, e.message);
          return;
        }
        case "tool": {
          const args = (d.args as Record<string, unknown> | undefined) ?? {};
          const line = narrateTool(String(d.tool ?? args.tool ?? ""), args, String(d.result ?? ""));
          child(group("research"), line.title, line.detail, line.failed ? "error" : "done");
          return;
        }
        case "coordinate": {
          const g = group("review", "Coordinating clashes, services and structure");
          const issues = (d.issues as { message?: string; level?: string }[] | undefined) ?? [];
          for (const i of issues) child(g, String(i.message ?? ""), null, i.level === "error" ? "error" : "done");
          finish(g, { title: cap(e.message) });
          return;
        }
        case "look": {
          // The model checking its own work from rendered screenshots.
          const g = group("review", "Looking at the model");
          if (d.skipped) {
            finish(g, { title: "Skipped the visual check", detail: e.message });
            return;
          }
          const problems = (d.problems as string[] | undefined) ?? [];
          if (problems.length) {
            for (const p of problems) child(g, p, null, "error");
            setDetail(g, `${plural(problems.length, "problem")} seen`);
            return;
          }
          child(g, cap(e.message), (d.error as string | undefined) ?? null,
                d.error ? "error" : "done", { image: typeof d.image === "string" ? d.image : undefined });
          return;
        }
        case "build": {
          const problems = (d.problems as string[]) ?? [];
          const unmet = (d.unmet as string[]) ?? [];
          if (problems.length) {
            const g = group("review", `Reworking ${plural(problems.length, "move")} that did not build`);
            setDetail(g, problems.slice(0, 3).map((x) => `• ${x}`).join("\n"));
          } else if (unmet.length) {
            const g = group("review", `Closing ${plural(unmet.length, "gap")} against the brief`);
            setDetail(g, unmet.map((x) => `• ${x}`).join("\n"));
          }
          return;
        }
        case "think": {
          // The model's own reasoning (Claude's summarised thinking, or an open model's <think> block).
          if (typeof d.live === "string") {
            hooks.onLive?.(`Thinking · ${d.live}`);
            return;
          }
          const purpose = String(d.purpose ?? "");
          const phase = purpose === "requirements" ? "brief" : purpose === "research" ? "research"
            : purpose === "build" && !applied ? "concept" : "review";
          const g = group(phase);
          const text = typeof d.text === "string" ? d.text : "";
          const heading = typeof d.title === "string" && d.title ? d.title : null;
          // Without a heading the title is the paragraph's first sentence; don't say it twice.
          const flat = text.replace(/\s+/g, " ").trim();
          const lead = /^(.{12,320}?[.!?])(?:\s+(.*))?$/.exec(flat);
          const [title, body] = heading ? [heading, text]
            : lead ? [lead[1], lead[2] ?? ""]
            : flat.length <= 320 ? [flat || e.message, ""]
            : [e.message, text];
          child(g, title, null, "done", { why: body && body !== title ? body : null, tone: null, badge: null });
          return;
        }
        case "llm":
          if (d.provider && lastGroup && BUILDING.has(lastGroup.step.phase)) {
            setDetail(lastGroup, `${d.provider}${d.model ? ` ${d.model}` : ""} is drawing…`);
          }
          return;
        case "stream":
          if (d.waiting) hooks.onLive?.(e.message);
          return;
        case "draft":
          hooks.onLive?.(e.message);
          return;
        case "step":
          onStep(e);
          if (lastGroup && BUILDING.has(lastGroup.step.phase)) {
            const t = tally[lastGroup.step.phase] ?? { applied: 0, skipped: 0 };
            setDetail(lastGroup, [plural(t.applied, "move"), t.skipped ? `${t.skipped} skipped` : "",
              gfa ? `${Math.round(gfa)} m² so far` : "", previews ? `preview ${previews}` : ""].filter(Boolean).join(" · "));
          }
          return;
        case "partial":
          if (typeof d.ifc_url === "string") {
            previews++;
            hooks.onPreview?.({ url: d.ifc_url, label: `Preview ${d.preview ?? previews} · ${d.elements ?? "?"} elements` });
          }
          return;
        case "verify": {
          hooks.onLive?.(null);
          for (const l of Object.values(layerOf)) finish(l);
          const rs = (d.results as { text: string; status: string; detail: string }[]) ?? [];
          const met = rs.filter((r) => r.status === "met").length;
          const checkable = rs.filter((r) => r.status === "met" || r.status === "unmet").length;
          const g = group("review", rs.length ? `Checked against the brief: ${met} of ${checkable} met` : "Checking against the brief");
          for (const r of rs) {
            if (r.status === "met" || r.status === "unmet") child(g, r.text, r.status === "unmet" ? r.detail : null, r.status === "unmet" ? "error" : "done");
          }
          if (rs.length && met === checkable) finish(g);
          return;
        }
        case "compile":
          hooks.onLive?.(null);
          for (const l of Object.values(layerOf)) finish(l);
          for (const [name, g] of Object.entries(groups)) if (name !== "output") finish(g);
          group("output");
          setDetail(groups.output, "walls, slabs, openings and roof → IFC4");
          return;
        case "code": {
          const g = group("code");
          if (d.error) {
            finish(g, { title: "Code review unavailable", detail: String(d.error) });
            return;
          }
          const score = (d.score ?? {}) as Record<string, number>;
          const occ = (d.occupancy ?? {}) as Record<string, unknown>;
          for (const c of (d.checks as Finding[] | undefined) ?? []) {
            const measured = c.value && c.target ? `${c.value} · required ${c.target}` : c.value || c.target || null;
            child(g, c.title, c.status === "pass" ? measured : [measured, c.detail].filter(Boolean).join("\n"),
                  "done", { badge: c.reference, tone: c.status, why: c.advice || null });
          }
          finish(g, {
            title: `Code review · ${d.code ?? ""}: ${score.pass ?? 0} of ${score.total ?? 0} clauses pass`,
            detail: `Occupancy ${occ.group ?? "?"} · ${occ.load ?? "?"} occupants · ${score.fail ? `${score.fail} to fix` : "nothing failing"}${score.warn ? ` · ${score.warn} to review` : ""}`,
            tone: score.fail ? "fail" : score.warn ? "warn" : "pass",
          });
          return;
        }
        case "precheck": {
          // The code screen before issue: failures go back to the model as a fix round.
          const score = (d.score ?? {}) as Record<string, number>;
          const failing = (d.checks as Finding[] | undefined) ?? [];
          const g = group("review", failing.length ? "Code screen before issue" : undefined);
          if (!failing.length) {
            child(g, `Code screen before issue: ${score.pass ?? 0} of ${score.total ?? 0} clauses pass`, null, "done", { badge: String(d.code ?? "").split(" ")[0] || null, tone: "pass" });
            return;
          }
          for (const c of failing) {
            const proposed = c.fix ? ` · ${c.fix} buildable fix step${c.fix === 1 ? "" : "s"} proposed` : "";
            child(g, `${c.title}: ${c.value} (required ${c.target})`, null, "done",
                  { badge: c.reference, tone: "fail", why: c.advice || proposed ? `Sent back to the model: ${c.advice}${proposed}` : null });
          }
          setDetail(g, `${failing.length} clause${failing.length === 1 ? "" : "s"} failing · the model is fixing them before the drawings are issued`);
          return;
        }
        case "estimate": {
          const g = group("cost");
          const cost = (d.cost ?? {}) as Record<string, number | string>;
          const carbon = (d.carbon ?? {}) as Record<string, unknown>;
          const best = d.best as { move: string; saving_kg: number; per_m2: number } | null | undefined;
          if (typeof cost.total === "number") {
            child(g, `Construction cost ${money(cost.total)} · $${Number(cost.per_sf).toLocaleString()}/sf`,
                  `${money(Number(cost.low))} – ${money(Number(cost.high))} range · ${String(cost.class ?? "")}`,
                  "done", { badge: "UniFormat II", tone: "info", why: String(cost.basis ?? "") || null });
          }
          if (typeof carbon.per_m2 === "number") {
            const meets = carbon.meets_2030 === true;
            child(g, `Upfront carbon ${carbon.per_m2} kgCO₂e/m² (A1–A5)`,
                  `LETI ${carbon.typology} · 2020 target ${carbon.target_2020} · 2030 target ${carbon.target_2030}`,
                  "done", { badge: `LETI ${carbon.band}`, tone: meets ? "pass" : "warn",
                            why: best ? `${best.move} would save ${(best.saving_kg / 1000).toFixed(1)} tCO₂e, taking it to ${best.per_m2} kgCO₂e/m².` : null });
          }
          finish(g, { title: cap(e.message) });
          return;
        }
        case "deliver": {
          const g = group("issue");
          const sheets = (d.sheets as { number: string; title: string }[] | undefined) ?? [];
          for (const s of sheets) child(g, s.title, null, "done", { badge: s.number });
          child(g, "Plans in model space on NCS layers, one storey per sheet of CAD", null, "done", { badge: "DXF" });
          child(g, "Area, room, door, window and equipment schedules with live totals", null, "done", { badge: "XLSX" });
          child(g, "Open issues exported as BCF 2.1, linked to IFC GlobalIds", null, "done", { badge: "BCF" });
          finish(g, { title: `Issued ${plural(sheets.length, "sheet")}, CAD plans, schedules, BCF issues and the cost plan`, detail: null });
          return;
        }
        case "done":
          hooks.onLive?.(null);
          closeAll();
          return;
        case "error":
          hooks.onLive?.(null);
          return; // the stream throws right after; fail() reports it once
        default: {
          const info = LEGACY[e.stage];
          if (!info) return;
          const errors = (d.errors as string[] | undefined) ?? [];
          const g = group(info.phase, info.title);
          if (errors.length) child(g, cap(e.message), `fixing: ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}`, "running");
        }
      }
    },
    /** Mark whatever was running as failed (the error shows on the innermost step). */
    fail(message: string) {
      hooks.onLive?.(null);
      const target = lastGroup;
      if (target) {
        target.step = { ...target.step, status: "error", error: message, ms: Math.round(performance.now() - target.t0) };
        push(target.step);
      }
      closeAll();
    },
  };
}
