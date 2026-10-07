"use client";

/**
 * Hardware-v2 movement analytics: typed calls and a small loader hook.
 *
 * Every number these return was stored by the pipeline (or is a plain
 * aggregate of stored values computed once on the server). Nothing here
 * computes, smooths or fills in an indicator.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiFetch, ApiError } from "./client";

export type Provenance =
  | "SYNTHETIC_DEMONSTRATION"
  | "PUBLIC_DATASET_REPLAY"
  | "SIMULATED"
  | "PHYSICAL_REGISTERED"
  | "PHYSICAL_UNVERIFIED";

export type MovementStatus = "IMPROVING" | "STABLE" | "NEEDS_ATTENTION" | "COMPLETED";
export type TrendWord = "improving" | "worsening" | "flat" | "insufficient";

export type Labels = {
  provenance: string | null;
  research: string;
  prototype: string;
  provenance_detail: string | null;
};

export type MovementSession = {
  id: number;
  patient_id: number;
  patient_name?: string | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  exercise_type: string;
  status: string;
  provenance: Provenance;
  mqi: number | null;
  mqi_status: string | null;
  mqi_confidence: number | null;
  mqi_components: Record<string, number>;
  asymmetry_score: number | null;
  asymmetry_pct: number | null;
  asymmetry_status: string | null;
  asymmetry_confidence: number | null;
  repetitions: number | null;
  repetition_kind: string | null;
  reps_left: number | null;
  reps_right: number | null;
  rom_left_deg: number | null;
  rom_right_deg: number | null;
  rom_difference_deg: number | null;
  rep_duration_left_s: number | null;
  rep_duration_right_s: number | null;
  sparc_left: number | null;
  sparc_right: number | null;
  peak_velocity_left_dps: number | null;
  peak_velocity_right_dps: number | null;
  activity_top: string | null;
  activity_seconds: Record<string, number>;
  activity_windows: number | null;
  low_confidence_windows: number | null;
  model: string | null;
  model_unavailable_reason: string | null;
  confidence_pct: number | null;
  confidence_band: string | null;
  bilateral_coverage: number | null;
  calibration_status: string | null;
  calibration_quality: number | null;
  packet_loss_pct: number | null;
  samples: number | null;
  reported_pain: number | null;
  generated: boolean;
  programme_day: number | null;
};

export type PatientBrief = {
  id: number;
  name: string;
  preferred_name: string | null;
  age: number | null;
  operated_leg: "LEFT" | "RIGHT";
  program: string | null;
  program_days: number | null;
  planned_sessions: number | null;
  recovery_start: string | null;
  provenance: Provenance | null;
};

export type SessionRef = { id: number; mqi: number; started_at: string; exercise_type: string } | null;

export type MovementSummary = {
  programme: string | null;
  programme_days: number | null;
  planned_sessions: number | null;
  start_date: string | null;
  programme_end: string | null;
  programme_ended: boolean;
  duration_days: number;
  sessions_completed: number;
  expected_sessions_to_date: number | null;
  adherence_pct: number | null;
  initial_mqi: number | null;
  current_mqi: number | null;
  mqi_change: number | null;
  improvement_pct: number | null;
  initial_asymmetry_pct: number | null;
  current_asymmetry_pct: number | null;
  asymmetry_change_pct: number | null;
  mqi_slope_per_week: number | null;
  asymmetry_slope_per_week: number | null;
  mqi_trend: TrendWord;
  asymmetry_trend: TrendWord;
  best_session: SessionRef;
  worst_session: SessionRef;
  consistency_sd: number | null;
  sessions_per_week: number | null;
  mean_repetitions: number | null;
  mean_duration_s: number | null;
  mean_confidence_pct: number | null;
  activity_seconds: Record<string, number>;
  exercises: Record<string, number>;
  provenance: Provenance | null;
  provenance_counts: Record<string, number>;
  models: string[];
  last_session_at: string | null;
  last_activity: string | null;
  status: MovementStatus;
  status_reasons: string[];
};

export type StatusRule = Record<string, string>;

export type PatientMovement = {
  patient: PatientBrief;
  summary: MovementSummary;
  sessions: MovementSession[];
  status_rule: StatusRule;
  labels: Labels;
};

export type RosterEntry = PatientBrief & {
  sessions_completed: number;
  last_session_at: string | null;
  current_mqi: number | null;
  initial_mqi: number | null;
  mqi_change: number | null;
  mqi_trend: TrendWord;
  current_asymmetry_pct: number | null;
  asymmetry_trend: TrendWord;
  status: MovementStatus;
  status_reasons: string[];
  last_activity: string | null;
  adherence_pct: number | null;
  programme_ended: boolean;
  series: { id: number; started_at: string; mqi: number | null; asymmetry_pct: number | null }[];
};

export type Roster = {
  items: RosterEntry[];
  references: RosterEntry[];
  status_rule: StatusRule;
  synthetic: boolean;
};

export type Overview = {
  generated_at: string;
  kpis: {
    active_patients: number;
    patients: number;
    sessions_this_week: number;
    total_sessions: number;
    sessions_completed: number;
    average_mqi: number | null;
    average_asymmetry_pct: number | null;
    average_mqi_change: number | null;
    improving: number;
    stable: number;
    needs_attention: number;
    completed: number;
    exercises_performed: number;
    model_inferences: number;
    total_repetitions: number;
  };
  exercise_counts: Record<string, number>;
  weekly_trend: { week: string; mean_mqi: number | null; mean_asymmetry_pct: number | null; sessions: number }[];
  recent_sessions: MovementSession[];
  needs_attention: {
    patient_id: number;
    name: string;
    reasons: string[];
    current_mqi: number | null;
    current_asymmetry_pct: number | null;
  }[];
  patients: (PatientBrief & {
    status: MovementStatus;
    current_mqi: number | null;
    mqi_change: number | null;
    series: (number | null)[];
  })[];
  provenance: { sessions: Record<string, number>; records: Record<string, number>; all_sessions: number };
  synthetic: boolean;
  labels: Labels;
  status_rule: StatusRule;
};

export type ExerciseAnalytics = {
  items: {
    exercise_type: string;
    sessions: number;
    patients: number;
    patient_names: string[];
    average_repetitions: number | null;
    average_mqi: number | null;
    average_asymmetry_pct: number | null;
    average_duration_s: number | null;
    average_rep_duration_s: number | null;
    mqi_slope_per_session: number | null;
    trend: TrendWord;
    model_activity_seconds: Record<string, number>;
    series: { started_at: string; mqi: number | null; patient_id: number }[];
  }[];
  note: string;
  labels: Labels;
};

export type InferenceCounts = {
  total: number;
  by_status: Record<string, number>;
  by_activity: Record<string, number>;
  by_model: Record<string, number>;
};

export type Research = {
  generated_at: string;
  dataset: {
    sessions: number;
    sessions_by_provenance: Record<string, number>;
    records_by_provenance: Record<string, number>;
    patients: number;
    samples: number;
    chunks: number;
    activities: string[];
    exercises: Record<string, number>;
    model_versions: string[];
    physical_sessions: number;
  };
  model: InferenceCounts & {
    by_provenance: Record<string, InferenceCounts>;
    confidence_histogram: { from: number; to: number; count: number }[];
    mean_confidence: number | null;
    replay_agreement: {
      windows_scored: number;
      agreement_pct: number | null;
      low_confidence_pct: number | null;
      confusion: Record<string, Record<string, number>>;
      scope: string;
    };
    note: string;
  };
  movement: {
    mqi_histogram: { from: number; to: number; count: number }[];
    asymmetry_histogram: { from: number; to: number; count: number }[];
    mean_mqi: number | null;
    mean_asymmetry_pct: number | null;
    mqi_sd_by_patient: Record<string, number | null>;
    rep_duration_by_exercise: Record<string, number | null>;
    left_right_rom_difference_deg: number | null;
    points: {
      id: number;
      patient_id: number;
      mqi: number | null;
      asymmetry_pct: number | null;
      exercise_type: string;
      rom_left_deg: number | null;
      rom_right_deg: number | null;
    }[];
    components_mean: Record<string, number | null>;
  };
  longitudinal: {
    records: {
      patient_id: number;
      name: string;
      provenance: Provenance | null;
      status: MovementStatus;
      mqi_trend: TrendWord;
      asymmetry_trend: TrendWord;
      mqi_slope_per_week: number | null;
      asymmetry_slope_per_week: number | null;
      initial_mqi: number | null;
      current_mqi: number | null;
      adherence_pct: number | null;
      sessions: number;
      consistency_sd: number | null;
      series: { day: number | null; started_at: string; mqi: number | null; asymmetry_pct: number | null }[];
    }[];
    trajectories: Record<string, number>;
    mean_adherence_pct: number | null;
  };
  labels: Labels;
  validation: Record<string, string>;
};

export type Generation = {
  provenance?: string;
  label?: string;
  generator?: string;
  synthetic_generator_version?: string;
  seed?: number;
  session_seed?: number;
  source_dataset?: string;
  dataset_subject?: string;
  model_version?: string | null;
  pipeline_version?: string;
  generation_timestamp?: string;
  trajectory?: string;
  programme_day?: number;
  programme_days?: number;
  latent_impairment?: number;
  inputs?: {
    left: Record<string, number>;
    right: Record<string, number>;
    packet_loss: number;
    movement_s: number;
    reported_pain: number;
  };
  segments?: { activity_code: string; label: string; dataset_segment: number; t_start: number; t_end: number }[];
  stream?: { packets_sent: number; packets_dropped: number; samples_generated: number };
  note?: string;
};

export type SessionAnalysis = {
  session_id: number;
  patient_id: number;
  status: string;
  mode: string;
  protocol_version: number | null;
  exercise_type: string;
  live: boolean;
  started_at: string | null;
  ended_at: string | null;
  calibration_state: string;
  provenance: Provenance;
  generation: Generation | null;
  summary: Record<string, unknown> | null;
  repetitions: {
    side: "LEFT" | "RIGHT";
    kind: string;
    rep_index: number;
    t_start: number;
    t_peak: number;
    t_end: number;
    rom_proxy_deg: number;
    peak_velocity_dps: number | null;
    smoothness_sparc: number | null;
    force_peak: number | null;
  }[];
  activity_segments: {
    t_start: number;
    t_end: number;
    activity: string | null;
    status: string;
    windows: number;
    mean_confidence: number | null;
  }[];
  assessments: {
    t_start: number;
    t_end: number;
    kind: string;
    mqi: number | null;
    mqi_confidence: number | null;
    asymmetry_score: number | null;
    asymmetry_confidence: number | null;
  }[];
  session_assessment: Record<string, unknown> | null;
  validation: Record<string, string>;
};

export type SessionTrace = {
  session_id: number;
  rate_hz: number;
  columns: string[];
  units: Record<string, unknown> | null;
  rows: (number | null)[][];
  truncated: boolean;
  provenance: Provenance;
  exercise_type: string;
};

export type ActivityWindows = {
  session_id: number;
  segments: SessionAnalysis["activity_segments"];
  windows: {
    t_start: number;
    t_end: number;
    status: string;
    activity: string | null;
    candidate: string | null;
    confidence: number | null;
    model: string | null;
  }[];
};

export type ReportItem = {
  id: number;
  patient_id: number;
  session_id: number | null;
  kind: string;
  status: string;
  generated_at: string | null;
  analytics_version: string | null;
  report_version: string;
  patient_name: string | null;
  provenance: Provenance | null;
  title: string | null;
  sessions: number | null;
  period_days: number | null;
  status_label: MovementStatus | null;
  pdf: boolean;
};

export type DeviceItem = {
  id: number;
  device_id: string;
  kind: string;
  provenance: Provenance | null;
  recordings_by_provenance: Record<string, number>;
  simulated: boolean;
  verified_hardware: boolean;
  revoked: boolean;
  firmware_version: string | null;
  protocol_version: number | null;
  status: string;
  last_seen: string | null;
  sample_rate_hz: number | null;
  battery_level: number | null;
  sensors: { type: string; location: string; capability: string; status: string; last_seen: string | null }[];
};

export type LiveDevices = {
  physical_online: { device_id: string; last_seen: string | null; firmware_version: string | null; sample_rate_hz: number | null }[];
  checked_at: string;
};

export type MlModels = {
  status_block: {
    MODEL_IMPLEMENTED: string;
    PUBLIC_DATASET_VALIDATED: string;
    REAL_REHABSENSE_HARDWARE_VALIDATED: string;
    HUMAN_LABELED_PHYSICAL_DATA: number;
    CLINICAL_VALIDATION: string;
  };
  loaded: Record<string, Record<string, unknown>>;
  validation_note: string;
};

export const movementApi = {
  overview: () => apiFetch<Overview>("/analytics/overview"),
  roster: () => apiFetch<Roster>("/analytics/patients"),
  patient: (id: number) => apiFetch<PatientMovement>(`/analytics/patients/${id}`),
  sessions: (patientId?: number | null) =>
    apiFetch<{ items: MovementSession[]; total: number }>(
      `/analytics/sessions${patientId ? `?patient_id=${patientId}` : ""}`,
    ),
  exercises: () => apiFetch<ExerciseAnalytics>("/analytics/exercises"),
  research: () => apiFetch<Research>("/analytics/research"),
  analysis: (sessionId: number) => apiFetch<SessionAnalysis>(`/sessions/${sessionId}/analysis`),
  trace: (sessionId: number) => apiFetch<SessionTrace>(`/sessions/${sessionId}/trace`),
  activity: (sessionId: number) => apiFetch<ActivityWindows>(`/sessions/${sessionId}/activity`),
  reports: (patientId?: number | null) =>
    apiFetch<{ items: ReportItem[]; total: number }>(`/reports${patientId ? `?patient_id=${patientId}` : ""}`),
  createReport: (patientId: number) =>
    apiFetch<{ id: number; status: string }>("/reports", {
      method: "POST",
      body: JSON.stringify({ patient_id: patientId, kind: "MOVEMENT_PROGRESS" }),
    }),
  generateReport: (reportId: number) =>
    apiFetch<{ id: number; status: string; generated_at: string }>(`/reports/${reportId}/generate`, {
      method: "POST",
    }),
  devices: () => apiFetch<{ items: DeviceItem[] }>("/devices"),
  liveDevices: () => apiFetch<LiveDevices>("/devices/live"),
  mlModels: () => apiFetch<MlModels>("/ml/models"),
};

/** Open a stored PDF in a new tab (fetched with the session cookie first). */
export async function openPdf(reportId: number): Promise<void> {
  // The tab is opened synchronously, inside the click, so popup blockers
  // allow it; the document arrives a moment later.
  const tab = window.open("", "_blank");
  try {
    const response = await fetch(`${API_BASE}/api/reports/${reportId}/pdf`, {
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) throw new ApiError(response.status, "PDF_FAILED", `PDF failed (${response.status}).`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    if (tab) tab.location.href = url;
    else window.location.assign(url);
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}

export type Loaded<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Load one resource. A failure is reported, never replaced with substitute
 * values; `enabled=false` keeps it idle (e.g. until a patient is chosen).
 */
export function useApi<T>(load: () => Promise<T>, deps: unknown[], enabled = true): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [nonce, setNonce] = useState(0);
  const loader = useRef(load);
  loader.current = load;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader
      .current()
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((cause) => {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause.message : "Request failed.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce, ...deps]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}
