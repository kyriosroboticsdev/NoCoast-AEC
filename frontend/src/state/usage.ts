// Token counts: how they are summed over a session and written for people.
import type { TokenUsage } from "../api/client";
import type { Session } from "./sessions";

export interface UsageTotal {
  input: number;
  output: number;
  cached: number;
  total: number;
  /** Model calls behind the numbers. */
  calls: number;
  /** Runs that used a model. */
  runs: number;
  /** At least part of the count is an estimate from the text, not the provider's own number. */
  estimated: boolean;
}

/** What a run used: the version's stored total once it has one, the live count while it works. */
export const runUsage = (run: { version?: { usage?: TokenUsage | null }; usage?: TokenUsage } | undefined): TokenUsage | null =>
  run?.version?.usage ?? run?.usage ?? null;

/** Every run of the session added up, failed runs included: their tokens were spent too. */
export function sessionUsage(session: Session): UsageTotal | null {
  const sum: UsageTotal = { input: 0, output: 0, cached: 0, total: 0, calls: 0, runs: 0, estimated: false };
  for (const m of session.messages) {
    const u = runUsage(m.run);
    if (!u) continue;
    sum.input += u.input_tokens;
    sum.output += u.output_tokens;
    sum.cached += u.cached_tokens ?? 0;
    sum.total += u.total_tokens;
    sum.calls += u.calls ?? 0;
    sum.runs += 1;
    sum.estimated ||= !!u.estimated;
  }
  return sum.runs ? sum : null;
}

/** 950 → "950", 12 430 → "12.4k", 1 250 000 → "1.25M". */
export function formatTokens(n: number): string {
  if (n < 1000) return String(Math.round(n));
  if (n < 999_950) return `${(n / 1000).toFixed(n < 99_950 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

/** The long form for a tooltip: "12,430 read (9,000 from cache) · 3,120 written · 4 model calls". */
export function describeUsage(u: { input: number; output: number; cached: number; calls: number; estimated: boolean }): string {
  const n = (x: number) => x.toLocaleString("en-US");
  const parts = [
    `${n(u.input)} read${u.cached ? ` (${n(u.cached)} from cache)` : ""}`,
    `${n(u.output)} written`,
    `${u.calls} model call${u.calls === 1 ? "" : "s"}`,
  ];
  return parts.join(" · ") + (u.estimated ? " · estimated from the text, about 4 characters a token" : "");
}
