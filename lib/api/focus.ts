"use client";

import { apiFetch } from "./client";

/**
 * Recovery Focus client.
 *
 * Every duration here is computed by the backend from its own event ledger.
 * Nothing in the browser counts seconds towards a stored total: the UI ticks
 * only to redraw, and re-reads the authoritative numbers from the server.
 */

export type FocusStatus =
  | "READY" | "ACTIVE" | "PAUSED" | "COMPLETED" | "CANCELLED" | "INTERRUPTED";

export type FocusBlock = {
  id: number;
  patient_id: number;
  status: FocusStatus;
  exercise_type: string;
  local_date: string;
  target_duration_s: number;
  scheduled_for: string | null;
  started_at: string | null;
  ended_at: string | null;
  notes: string | null;
  /** Wall time from start to end (or now). */
  elapsed_s: number;
  paused_s: number;
  /** Elapsed minus paused: time actually spent in a running block. */
  engaged_s: number;
  /** Time sensors were recording, summed from the linked sessions. */
  active_movement_s: number;
  remaining_s: number;
  completion_pct: number;
  interruptions: number;
  is_running: boolean;
  session_count: number;
  completed_session_count: number;
  repetitions: number;
  exercises: string[];
  exercise_count: number;
  best_rom_deg: number | null;
  mean_confidence_pct: number | null;
  session_ids: number[];
  adherence_threshold_pct: number;
  met_target: boolean;
};

export type DayEntry = {
  focus_id: number;
  status: FocusStatus;
  exercise_type: string;
  started_at: string | null;
  /** Minutes past local midnight — the timeline's x position. */
  start_minute: number | null;
  target_duration_s: number;
  engaged_s: number;
  active_movement_s: number;
  completion_pct: number;
  repetitions: number;
  session_ids: number[];
};

export type DaySummary = {
  date: string;
  state: "none" | "planned" | "partial" | "met" | "exceeded" | "future";
  planned_s: number;
  engaged_s: number;
  active_movement_s: number;
  completion_pct: number;
  block_count: number;
  completed_block_count: number;
  repetitions: number;
  exercises: string[];
  entries: DayEntry[];
};

export type Streak = {
  current_days: number;
  best_days: number;
  threshold_pct: number;
  rule: string;
};

export type FocusAnalytics = {
  planned_minutes: number;
  completed_minutes: number;
  active_movement_minutes: number;
  blocks_planned: number;
  blocks_completed: number;
  days_with_a_plan: number;
  days_worked: number;
  repetitions: number;
  goal_completion_rate_pct: number | null;
  mean_block_minutes: number | null;
  mean_start_minute: number | null;
  most_common_exercise: string | null;
  exercise_frequency: Record<string, number>;
  streak: Streak;
};

export type Reminder = {
  id: number;
  patient_id: number;
  time_of_day: string;
  weekdays: number[];
  timezone_name: string;
  target_duration_s: number;
  exercise_type: string;
  enabled: boolean;
  next_occurrence: string | null;
  /** Always NOT_CONFIGURED here: nothing is delivered to a device. */
  delivery: string;
  delivery_note: string;
};

export type TodayPayload = {
  patient_id: number;
  local_date: string;
  summary: DaySummary;
  blocks: FocusBlock[];
  active_block: FocusBlock | null;
  reminders: Reminder[];
  presets_s: number[];
  adherence_threshold_pct: number;
};

export type CalendarPayload = {
  start_date: string;
  end_date: string;
  adherence_threshold_pct: number;
  days: DaySummary[];
  analytics: FocusAnalytics;
};

/** The browser's own calendar date, so "today" matches the patient's clock. */
export function localDate(at: Date = new Date()): string {
  const y = at.getFullYear();
  const m = String(at.getMonth() + 1).padStart(2, "0");
  const d = String(at.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export const focusApi = {
  today: (patientId: number, date = localDate()) =>
    apiFetch<TodayPayload>(`/focus/today?patient_id=${patientId}&local_date=${date}`),

  calendar: (patientId: number, start: string, end: string) =>
    apiFetch<CalendarPayload>(
      `/focus/calendar?patient_id=${patientId}&start=${start}&end=${end}`,
    ),

  history: (patientId: number, period: "today" | "week" | "month" = "week") =>
    apiFetch<{ period: string; start_date: string; end_date: string; days: DaySummary[]; analytics: FocusAnalytics }>(
      `/focus/history?patient_id=${patientId}&period=${period}`,
    ),

  create: (input: {
    patient_id: number;
    target_duration_s: number;
    exercise_type: string;
    local_date?: string;
    notes?: string | null;
  }) =>
    apiFetch<FocusBlock>("/focus", {
      method: "POST",
      body: JSON.stringify({ local_date: localDate(), ...input }),
    }),

  get: (id: number) => apiFetch<FocusBlock>(`/focus/${id}`),
  start: (id: number) => apiFetch<FocusBlock>(`/focus/${id}/start`, { method: "POST" }),
  pause: (id: number) => apiFetch<FocusBlock>(`/focus/${id}/pause`, { method: "POST" }),
  resume: (id: number) => apiFetch<FocusBlock>(`/focus/${id}/resume`, { method: "POST" }),
  complete: (id: number) => apiFetch<FocusBlock>(`/focus/${id}/complete`, { method: "POST" }),
  cancel: (id: number) => apiFetch<FocusBlock>(`/focus/${id}/cancel`, { method: "POST" }),

  linkSession: (id: number, sessionId: number) =>
    apiFetch<FocusBlock>(`/focus/${id}/sessions`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),

  reminders: (patientId: number) =>
    apiFetch<{ items: Reminder[] }>(`/focus/reminders/list?patient_id=${patientId}`),

  createReminder: (input: {
    patient_id: number;
    time_of_day: string;
    weekdays: number[];
    target_duration_s: number;
    exercise_type?: string;
  }) => apiFetch<Reminder>("/focus/reminders", { method: "POST", body: JSON.stringify(input) }),

  updateReminder: (id: number, patch: Partial<Reminder>) =>
    apiFetch<Reminder>(`/focus/reminders/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  deleteReminder: (id: number) =>
    apiFetch<void>(`/focus/reminders/${id}`, { method: "DELETE" }),
};

/** mm:ss, or h:mm:ss past an hour. */
export function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** "30 min", "1 h 30 min" — for targets rather than running clocks. */
export function humanDuration(seconds: number): string {
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const rest = mins % 60;
  return rest === 0 ? `${h} h` : `${h} h ${rest} min`;
}

/** Minutes past midnight -> "6:30 PM". */
export function clockTime(minute: number): string {
  const h24 = Math.floor(minute / 60) % 24;
  const m = minute % 60;
  const suffix = h24 >= 12 ? "PM" : "AM";
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${suffix}`;
}
