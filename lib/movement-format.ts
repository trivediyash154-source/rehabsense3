/**
 * Display helpers for hardware-v2 movement data. Formatting only: no value is
 * computed or adjusted here.
 */

export const EXERCISE_LABEL: Record<string, string> = {
  WALK: "Walking",
  SQUAT: "Squat",
  SIT_TO_STAND: "Sit-to-stand",
  STEP_UP: "Step-up",
  KNEE_EXTENSION: "Knee extension",
  SINGLE_LEG_BALANCE: "Single-leg balance",
};

export const ACTIVITY_LABEL: Record<string, string> = {
  other_exercise: "Other exercise",
  stairs_up: "Stairs up",
  stairs_down: "Stairs down",
  walking: "Walking",
  standing: "Standing",
  sitting: "Sitting",
  lying: "Lying",
  cycling: "Cycling",
  running: "Running",
};

export const STATUS_LABEL: Record<string, string> = {
  IMPROVING: "Improving",
  STABLE: "Stable",
  NEEDS_ATTENTION: "Needs attention",
  COMPLETED: "Completed",
};

export const TREND_ARROW: Record<string, string> = {
  improving: "↗",
  worsening: "↘",
  flat: "→",
  insufficient: "·",
};

export function exerciseLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return EXERCISE_LABEL[value] ?? value.replace(/_/g, " ").toLowerCase();
}

export function activityLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return ACTIVITY_LABEL[value] ?? value.replace(/_/g, " ");
}

/** Parse an API timestamp (UTC, with or without a trailing Z). */
export function parseTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalised = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) || !value.includes("T") ? value : `${value}Z`;
  const at = new Date(normalised);
  return Number.isNaN(at.getTime()) ? null : at;
}

export function shortDate(value: string | null | undefined): string {
  const at = parseTime(value);
  return at ? at.toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "—";
}

export function longDate(value: string | null | undefined): string {
  const at = parseTime(value);
  return at ? at.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—";
}

export function dateTime(value: string | null | undefined): string {
  const at = parseTime(value);
  return at
    ? at.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";
}

/** "3 days ago", "today". */
export function relativeDay(value: string | null | undefined, now: Date = new Date()): string {
  const at = parseTime(value);
  if (!at) return "—";
  const days = Math.floor(
    (new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() -
      new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime()) /
      86_400_000,
  );
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function num(value: number | null | undefined, digits = 1, suffix = ""): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}${suffix}`;
}

export function signed(value: number | null | undefined, digits = 1, suffix = ""): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

export function clock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function compact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}k`;
  return value.toLocaleString();
}

/** Share of the largest entries, as label / seconds / fraction rows. */
export function shares(seconds: Record<string, number> | null | undefined, top = 6) {
  const entries = Object.entries(seconds ?? {}).filter(([, v]) => v > 0);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  return entries
    .sort((a, b) => b[1] - a[1])
    .slice(0, top)
    .map(([key, value]) => ({ key, label: activityLabel(key), value, share: total ? value / total : 0 }));
}
