"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiFetch, liveSocketUrl } from "./client";

/**
 * Hardware v2: one ESP32 with a LEFT and a RIGHT MPU6050 plus force channels.
 *
 * Every number on the hardware page comes from these calls or from `hw_*`
 * events on the live socket. The page computes no metric itself; it only
 * decides *whether* a number may be shown (status, confidence, calibration).
 */

export type InferenceStatus =
  | "OK"
  | "LOW_CONFIDENCE"
  | "INSUFFICIENT_DATA"
  | "MODEL_UNAVAILABLE";

export type ImuState =
  | "CONNECTED"
  | "DISCONNECTED"
  | "FROZEN"
  | "WAITING"
  | "NOT_DECLARED";

export type SensorAlert = { code: string; side?: string; channel?: string; reason: string };

export type HwConnection = {
  protocol_version: number;
  device_id: string;
  firmware_version: string;
  simulated: boolean;
  provenance: "SIMULATED" | "PUBLIC_DATASET_REPLAY" | "PHYSICAL_UNVERIFIED" | "PHYSICAL_REGISTERED";
  alerts: SensorAlert[];
  scenario: string | null;
  session_mode: "LIVE" | "SIMULATED" | "UNVERIFIED";
  device_connected: boolean;
  imus: Record<"LEFT" | "RIGHT", { state: ImuState; placement: string | null; available_ratio: number }>;
  force_channels: { id: string; side: string | null; unit: string }[];
  declared_rate_hz: number;
  measured_rate_hz: number | null;
  device_status: { battery_pct?: number; battery_v?: number; wifi_rssi_dbm?: number };
};

export type CalibrationCheck = {
  key: string;
  status: "PASS" | "WARN" | "FAIL" | "SKIPPED";
  message: string;
  detail: Record<string, unknown>;
};

export type HwCalibration = {
  sequence: number;
  step: number;
  phase: "PENDING" | "HEALTH_CHECK" | "STILL" | "MOVEMENT" | "COMPLETE" | "FAILED";
  health: Record<string, { ok: boolean; reason?: string; available?: number; gravity_norm_g?: number }>;
  health_attempts: number;
  stale_reason: string | null;
  failure_reason?: string | null;
  progress: number;
  instruction: string;
  complete: boolean;
  status?: "PASS" | "WARN" | "FAIL";
  quality?: number;
  checks?: CalibrationCheck[];
};

export type HwStreamHealth = {
  declared_rate_hz: number;
  measured_rate_hz: number | null;
  effective_rate_hz: number | null;
  force_available_ratio: number[];
  samples_received: number;
  missing_samples: number;
  saturated_samples: Record<string, number>;
  out_of_range_samples: Record<string, number>;
  rate_ok: boolean | null;
  jitter_ms: number | null;
  clock_drift_ppm: number | null;
  loss_ratio: number;
  duplicates: number;
  out_of_order: number;
  gaps: number;
  left_available_ratio: number;
  right_available_ratio: number;
  left_frozen: boolean;
  right_frozen: boolean;
  stream_quality: number;
  relative_latency_ms: { p50: number | null; p95: number | null; note: string };
  latency: Record<string, { p50_ms: number; p95_ms: number; max_ms: number; n: number }>;
};

export type Activity = {
  status: InferenceStatus;
  activity: string | null;
  candidate?: string;
  confidence: number | null;
  margin?: number;
  probabilities?: Record<string, number>;
  model?: string;
  message?: string | null;
  reason?: string | null;
  domain?: {
    trained_on: string | null;
    placement_match: boolean;
    hardware_validated: boolean;
    note: string;
  };
};

export type Bilateral = {
  status: "OK" | "SINGLE_SIDE" | "INSUFFICIENT_DATA" | "NO_MOVEMENT";
  asymmetry_score: number | null;
  confidence: number;
  label?: string;
  mode?: string;
  message?: string;
  components: Record<string, number | null>;
  larger_side?: Record<string, string | null>;
};

export type ForceMotion = {
  channels: Record<string, {
    status: string;
    unit?: string;
    mean?: number;
    peak?: number;
    motion_correlation?: number | null;
    lag_s?: number | null;
  }>;
};

export type MlUpdate = {
  t_start: number;
  t_end: number;
  activity: Activity;
  phase: { method: string; by_side: Record<string, string | null> };
  bilateral: Bilateral;
  force_motion: ForceMotion | null;
  imu_available: Record<"LEFT" | "RIGHT", boolean>;
  alerts: SensorAlert[];
  calibration: { sequence: number; status: string; valid: boolean; stale_reason: string | null };
  calibration_required: boolean;
  movement_quality: Mqi | null;
};

export type HwRep = {
  side: "LEFT" | "RIGHT";
  rep_index: number;
  kind: "repetition" | "gait_cycle";
  t_start: number;
  t_end: number;
  duration_s: number;
  rom_proxy_deg: number;
  peak_velocity_dps: number;
  smoothness_sparc: number | null;
  force_peak: number | null;
};

export type Mqi = {
  status: "OK" | "LOW_CONFIDENCE" | "INSUFFICIENT_DATA";
  mqi: number | null;
  confidence: number;
  label: string;
  components: Record<string, number>;
  unavailable: string[];
  message?: string;
};

export type HwSummary = {
  protocol_version: 2;
  duration_s: number;
  session_mode: string;
  repetitions: number;
  repetition_summary: Record<string, {
    count: number; rom_proxy_deg_mean: number; peak_velocity_dps_mean: number;
    duration_s_mean: number; sparc_median: number | null;
  }>;
  repetition_kind: string;
  activity: {
    model: string | null;
    seconds_by_activity: Record<string, number>;
    windows: number;
    low_confidence_windows: number;
    unavailable_reason: string | null;
  };
  bilateral: Bilateral;
  force_motion: {
    status: string;
    unit_note: string | null;
    by_side: Record<string, { force_peak_mean: number; force_consistency: number | null;
                              description: string | null }>;
    force_symmetry: { normalised_difference: number } | null;
  };
  movement_quality: Mqi;
  latency?: Record<string, { p50_ms: number; p95_ms: number } | null>;
  validation: Record<string, string>;
  disclaimer: string;
};

export type BaselineComparison = {
  label: string;
  note: string;
  metrics: Record<string, {
    baseline: number; current: number; change: number; change_pct: number | null;
    direction: "higher" | "lower" | "similar"; unit: string;
  }>;
};

export type SessionAnalysis = {
  session_id: number;
  status: string;
  mode: string;
  protocol_version: number | null;
  exercise_type: string;
  live: boolean;
  summary: HwSummary | null;
  repetitions: HwRep[];
  activity_segments: { status: string; activity: string | null; t_start: number; t_end: number;
                       windows: number; mean_confidence: number | null }[];
  baseline_comparison: BaselineComparison | null;
};

export type SessionLabel = {
  id: number;
  tier: "GOLD" | "SILVER";
  confirmed: boolean;
  t_start: number;
  t_end: number;
  exercise_type: string | null;
  repetition_index: number | null;
  side: string | null;
  movement_phase: string | null;
  quality_rating: number | null;
  notes: string | null;
};

export const HW_SCENARIOS = [
  "SYMMETRIC", "ASYMMETRIC", "SEVERE_ASYMMETRY", "RIGHT_IMU_DROPOUT", "RIGHT_IMU_MISSING",
  "NOISY", "PACKET_LOSS", "DUPLICATES", "CLOCK_DRIFT", "RATE_MISMATCH", "FROZEN_LEFT", "NO_FORCE",
] as const;

export type ValidationReport = {
  verdict: "USABLE" | "USABLE_WITH_WARNINGS" | "NOT_USABLE";
  data_source: "SIMULATED" | "PUBLIC_DATASET_REPLAY" | "PHYSICAL_UNVERIFIED" | "PHYSICAL_REGISTERED";
  counts_as_hardware_evidence: boolean;
  evidence_level: string;
  scope: string;
  live: boolean;
  checks: { key: string; status: "PASS" | "WARN" | "FAIL" | "SKIPPED"; message: string }[];
};

export const hardwareApi = {
  startResearch: (input: { patient_id: number; exercise_type: string; subject_code: string;
                           task?: string; conditions?: string }) =>
    apiFetch<{ session_id: number; ingest_path: string; note: string }>("/research/recordings", {
      method: "POST", body: JSON.stringify(input),
    }),
  marker: (sessionId: number, kind: string, note?: string) =>
    apiFetch<{ id: number; label: string; t_session: number | null; t_uncertainty_s: number | null }>(
      `/sessions/${sessionId}/markers`, {
        method: "POST", body: JSON.stringify({ label: kind, kind, note }),
      }),
  exportUrl: (sessionId: number) => `/api/sessions/${sessionId}/export.zip`,
  integrity: (sessionId: number) =>
    apiFetch<{ recording_id: string; provenance: string; integrity_status: string;
               integrity: { checks: { key: string; status: string; detail: string }[] } }>(
      `/sessions/${sessionId}/recording-integrity`),
  recalibrate: (sessionId: number) =>
    apiFetch<{ recalibrating: boolean }>(`/sessions/${sessionId}/recalibrate`, { method: "POST" }),
  validation: (sessionId: number) =>
    apiFetch<ValidationReport>(`/sessions/${sessionId}/validation`),
  simulate: (sessionId: number, scenario: string, durationS = 90) =>
    apiFetch<{ started: boolean }>(`/sessions/${sessionId}/simulate-hardware`, {
      method: "POST",
      body: JSON.stringify({ scenario, duration_s: durationS }),
    }),
  analysis: (sessionId: number) => apiFetch<SessionAnalysis>(`/sessions/${sessionId}/analysis`),
  labels: (sessionId: number) =>
    apiFetch<{ items: SessionLabel[] }>(`/sessions/${sessionId}/labels`),
  addLabel: (sessionId: number, label: Partial<SessionLabel>) =>
    apiFetch<SessionLabel>(`/sessions/${sessionId}/labels`, {
      method: "POST",
      body: JSON.stringify(label),
    }),
  baseline: (patientId: number, exercise: string) =>
    apiFetch<{
      baseline: { id: number; metrics: Record<string, number>; source_session_ids: number[];
                  created_at: string } | null;
      comparison: BaselineComparison | null;
      current_session_id: number | null;
    }>(`/patients/${patientId}/baseline?exercise_type=${encodeURIComponent(exercise)}`),
  setBaseline: (patientId: number, sessionIds: number[]) =>
    apiFetch(`/patients/${patientId}/baseline`, {
      method: "POST",
      body: JSON.stringify({ session_ids: sessionIds }),
    }),
  models: () =>
    apiFetch<{
      status_block: MlStatusBlock;
      loaded: Record<string, Record<string, unknown>>;
      validation_note: string;
    }>("/ml/models"),
  stopSimulator: (sessionId: number) => api.stopSimulatedStream(sessionId),
};

/* ------------------------------------------------------------------ *
 * Live hardware feed
 * ------------------------------------------------------------------ */

/** Derived server-side from the loaded bundles' metadata and the database. */
export type MlStatusBlock = {
  MODEL_IMPLEMENTED: "YES" | "NO";
  PUBLIC_DATASET_VALIDATED: "YES" | "NO";
  REAL_REHABSENSE_HARDWARE_VALIDATED: "YES" | "NO";
  HUMAN_LABELED_PHYSICAL_DATA: number;
  CLINICAL_VALIDATION: "YES" | "NO";
};

export type FrameRow = (number | null)[];

export type HwLiveState = {
  socket: "connecting" | "open" | "reconnecting" | "closed";
  connection: HwConnection | null;
  calibration: HwCalibration | null;
  health: HwStreamHealth | null;
  ml: MlUpdate | null;
  reps: HwRep[];
  frameColumns: string[];
  frames: FrameRow[];
  lastSeq: number;
  /** Server-stamp to browser-receipt delay, ms. Assumes synchronised clocks. */
  deliveryMs: number[];
};

const EMPTY: HwLiveState = {
  socket: "closed",
  connection: null,
  calibration: null,
  health: null,
  ml: null,
  reps: [],
  frameColumns: [],
  frames: [],
  lastSeq: 0,
  deliveryMs: [],
};

/** Ten seconds of the decimated 25 Hz stream. */
const MAX_FRAMES = 250;

export function useHardwareLive(sessionId: number | null) {
  const [state, setState] = useState<HwLiveState>(EMPTY);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const closedRef = useRef(false);
  const connectRef = useRef<() => void>(() => undefined);

  const scheduleReconnect = useCallback(() => {
    if (closedRef.current) return;
    attemptRef.current += 1;
    const delay = Math.min(15000, 1000 * 2 ** (attemptRef.current - 1));
    setState((s) => ({ ...s, socket: "reconnecting" }));
    timerRef.current = window.setTimeout(() => connectRef.current(), delay);
  }, []);

  const connect = useCallback(async () => {
    if (sessionId == null) return;
    closedRef.current = false;
    let ticket: string;
    try {
      ticket = (await api.liveTicket(sessionId)).ticket;
    } catch {
      if (!closedRef.current) setState((s) => ({ ...s, socket: "closed" }));
      return;
    }
    if (closedRef.current) return;
    const socket = new WebSocket(liveSocketUrl(sessionId, ticket));
    socketRef.current = socket;
    socket.onopen = () => {
      attemptRef.current = 0;
      setState((s) => ({ ...s, socket: "open" }));
    };
    socket.onmessage = (event) => {
      let msg: { type: string; seq?: number; ts?: string } & Record<string, unknown>;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!msg.type?.startsWith("hw_")) return;
      setState((s) => {
        const seq = typeof msg.seq === "number" ? msg.seq : 0;
        if (seq > 0 && seq <= s.lastSeq) return s;
        const next: HwLiveState = { ...s, lastSeq: seq > 0 ? seq : s.lastSeq };
        if (typeof msg.ts === "string") {
          const d = Date.now() - Date.parse(msg.ts);
          if (Number.isFinite(d)) next.deliveryMs = [...s.deliveryMs.slice(-49), d];
        }
        switch (msg.type) {
          case "hw_connection":
            next.connection = msg as unknown as HwConnection;
            break;
          case "hw_calibration":
            next.calibration = msg as unknown as HwCalibration;
            break;
          case "hw_stream_health":
            next.health = msg as unknown as HwStreamHealth;
            break;
          case "hw_ml_update":
            next.ml = msg as unknown as MlUpdate;
            break;
          case "hw_rep":
            next.reps = [msg as unknown as HwRep, ...s.reps].slice(0, 80);
            break;
          case "hw_sensor_frame": {
            const rows = (msg.rows as FrameRow[]) ?? [];
            next.frameColumns = (msg.columns as string[]) ?? s.frameColumns;
            next.frames = [...s.frames, ...rows].slice(-MAX_FRAMES);
            break;
          }
          default:
            break;
        }
        return next;
      });
    };
    socket.onclose = () => {
      if (!closedRef.current) scheduleReconnect();
    };
    socket.onerror = () => socket.close();
  }, [sessionId, scheduleReconnect]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (sessionId == null) {
      setState(EMPTY);
      return;
    }
    setState({ ...EMPTY, socket: "connecting" });
    connect();
    return () => {
      closedRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
      attemptRef.current = 0;
    };
  }, [sessionId, connect]);

  return state;
}
