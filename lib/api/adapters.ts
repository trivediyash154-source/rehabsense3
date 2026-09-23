/**
 * Backend payloads -> the shapes the workspace components already speak.
 *
 * The point of this file is that the visual work stays untouched while the
 * numbers behind it become real. Nothing here computes an indicator: every
 * value is carried straight from the API, because the analytics layer is
 * authoritative and a second implementation in React would eventually
 * disagree with it.
 *
 * The one thing this file *will* do is refuse to invent. A session that
 * recorded no usable signal has null metrics, and a null is not a zero — such
 * sessions are separated out rather than being drawn as a point at the origin.
 */

import type { ExerciseType, Milestone, Session } from "@/lib/demo-data";

/** One session as the progress and overview endpoints return it. */
export type ApiSessionBrief = {
  id: number;
  started_at: string | null;
  day_label: string | null;
  exercise_type: string;
  duration_s: number | null;
  rom_deg: number | null;
  symmetry_index_pct: number | null;
  cadence_spm: number | null;
  recovery_score: number | null;
  repetitions: number | null;
  confidence: number | null;
  confidence_band: string | null;
  coverage_pct: number | null;
  peak_angle_left_deg: number | null;
  peak_angle_right_deg: number | null;
  mode: string;
};

export type ApiProgress = {
  patient_id: number;
  operated_leg: string;
  session_count: number;
  sessions: ApiSessionBrief[];
  baseline: ApiSessionBrief | null;
  latest: ApiSessionBrief | null;
  trends: Record<string, { slope: number | null; direction: string; n: number }>;
  milestones: { id?: string; session_id?: number; title: string; detail: string; kind?: string }[];
  total_repetitions: number | null;
  analytics_version: string | null;
};

const EXERCISES: ExerciseType[] = [
  "WALK", "SQUAT", "SIT_TO_STAND", "STEP_UP", "SINGLE_LEG_BALANCE",
];

function exerciseOf(value: string): ExerciseType {
  return (EXERCISES as string[]).includes(value) ? (value as ExerciseType) : "WALK";
}

/**
 * Parse a backend timestamp.
 *
 * The API emits UTC with an explicit "Z". This still guards the legacy naive
 * form: a bare date-time is read as local by `Date.parse`, so it is pinned to
 * UTC here rather than silently shifting by the viewer's offset.
 */
function parseUtc(value: string | null): Date | null {
  if (!value) return null;
  const normalised = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
  const at = new Date(normalised);
  return Number.isNaN(at.getTime()) ? null : at;
}

/** Local date, e.g. "7 Sep". */
function shortDate(at: Date | null): string {
  return at ? at.toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "—";
}

/** Local time of day, e.g. "12:33". */
function shortTime(at: Date | null): string {
  return at ? at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "—";
}

function clock(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function band(value: string | null): Session["confidence"] {
  return value === "Higher" || value === "Moderate" || value === "Lower" ? value : "Lower";
}

/**
 * Whole days from the first recorded session, for the "Day N" axis.
 *
 * Counted from local calendar dates rather than elapsed milliseconds, so a
 * session at 23:50 and one at 00:10 the next morning read as Day 1 and Day 2
 * instead of both rounding to the same day.
 */
function dayIndex(first: Date | null, at: Date | null): number {
  if (!first || !at) return 1;
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.max(1, Math.round((midnight(at) - midnight(first)) / 86_400_000) + 1);
}

/**
 * True when a session actually produced movement analytics.
 *
 * A session can exist and be COMPLETED without ever receiving usable sensor
 * data -- the device never connected, or nothing was recorded before it
 * ended. Those carry null metrics and must not be charted as zeros.
 */
export function hasAnalytics(brief: ApiSessionBrief): boolean {
  return brief.rom_deg != null && brief.repetitions != null && brief.repetitions > 0;
}

function note(brief: ApiSessionBrief, index: number, total: number): string {
  const parts: string[] = [];
  if (index === 0) parts.push("Baseline session.");
  else if (index === total - 1) parts.push("Most recent recorded session.");
  if (brief.mode === "SIMULATED") parts.push("Recorded from a simulated sensor stream.");
  if (brief.coverage_pct != null && brief.coverage_pct < 70) {
    parts.push("One side dropped out partway through; interpret with care.");
  }
  return parts.join(" ") || "Recorded session.";
}

/**
 * Adapt the analysable sessions into the workspace's `Session` shape.
 *
 * Sessions with no usable signal are excluded and reported separately, so the
 * interface can say "one session recorded no usable signal" instead of
 * drawing a misleading zero.
 */
export function adaptSessions(briefs: ApiSessionBrief[]): {
  sessions: Session[];
  skipped: ApiSessionBrief[];
} {
  const usable = briefs.filter(hasAnalytics);
  const skipped = briefs.filter((b) => !hasAnalytics(b));
  const first = parseUtc(usable[0]?.started_at ?? null);

  // When several sessions land on the same calendar day, "Day 1" repeated is
  // useless. Fall back to the time of day, which is the thing that actually
  // distinguishes them.
  const dayNumbers = usable.map((b) => dayIndex(first, parseUtc(b.started_at)));
  const allSameDay = dayNumbers.every((d) => d === dayNumbers[0]);

  const sessions = usable.map((brief, index) => {
    const at = parseUtc(brief.started_at);
    const day = dayNumbers[index];
    return {
      id: brief.id,
      label: `Session ${String(index + 1).padStart(2, "0")}`,
      day,
      dayLabel: allSameDay ? shortTime(at) : `Day ${day}`,
      date: shortDate(at),
      exercise: exerciseOf(brief.exercise_type),
      score: Math.round(brief.recovery_score ?? 0),
      rom: Math.round(brief.rom_deg ?? 0),
      cadence: Math.round(brief.cadence_spm ?? 0),
      reps: brief.repetitions ?? 0,
      duration: clock(brief.duration_s),
      symmetry: Math.round(brief.symmetry_index_pct ?? 0),
      coverage: Math.round(brief.coverage_pct ?? 0),
      confidence: band(brief.confidence_band),
      // Falls back to the session ROM only when per-limb peaks are absent, so
      // the bilateral view never shows a difference that was not measured.
      peakLeft: Math.round(brief.peak_angle_left_deg ?? brief.rom_deg ?? 0),
      peakRight: Math.round(brief.peak_angle_right_deg ?? brief.rom_deg ?? 0),
      note: note(brief, index, usable.length),
    } satisfies Session;
  });

  return { sessions, skipped };
}

const MILESTONE_KINDS: Milestone["kind"][] = [
  "start", "coverage", "range", "consistency", "trend", "latest",
];

export function adaptMilestones(
  raw: ApiProgress["milestones"],
  sessions: Session[],
): Milestone[] {
  const newest = sessions[sessions.length - 1];

  return (raw ?? []).flatMap((m, index) => {
    const kind = MILESTONE_KINDS.includes(m.kind as Milestone["kind"])
      ? (m.kind as Milestone["kind"])
      : index === 0
        ? "start"
        : "trend";

    // The backend scores milestones against every stored session, but this
    // list has already dropped the ones with no usable signal (a recording cut
    // short, for example). Copying such a session_id through would leave every
    // consumer's `sessions.find(...)` undefined and crash the page that
    // renders it. Resolve the session here, and drop the milestone when it
    // points at a session the user cannot actually open.
    const target =
      m.session_id == null
        ? newest
        : sessions.find((s) => s.id === m.session_id);
    if (!target) return [];

    return [
      {
        id: m.id ?? `milestone-${index}`,
        sessionId: target.id,
        title: m.title,
        detail: m.detail,
        kind,
      } satisfies Milestone,
    ];
  });
}

/** One contribution to the recovery indicator, exactly as the backend scored it. */
export type ApiContribution = {
  key: string;
  label: string;
  weight: number;
  normalized: number | null;
  value: number | null;
  contribution: number | null;
  available: boolean;
  note?: string | null;
};

/**
 * Recovery contributions from the session summary.
 *
 * Returns null when the backend did not score the session, so the caller
 * shows "not scored" rather than a breakdown that was assembled client-side.
 */
export function adaptContributions(summary: unknown): ApiContribution[] | null {
  const recovery = (summary as { recovery?: { contributions?: ApiContribution[] } } | null)?.recovery;
  if (!recovery?.contributions?.length) return null;
  return recovery.contributions;
}
