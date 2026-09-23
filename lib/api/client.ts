/**
 * Typed client for the RehabSense backend.
 *
 * Every figure the workspace displays comes from here. The frontend does not
 * recompute ROM, symmetry, recovery or comparisons — the backend owns those,
 * so the dashboard, receipt and report cannot drift apart.
 *
 * When the backend is unreachable, callers fall back to the illustrative demo
 * dataset and the UI says so explicitly rather than implying live data.
 */

/**
 * REST goes through this app's own origin, which Next proxies to the backend.
 * Same-origin is what lets the session ride an HttpOnly cookie the browser
 * attaches automatically, so no credential is ever held in JavaScript.
 */
export const API_BASE = "";

/**
 * WebSockets cannot be proxied by Next's rewrites, so the live socket goes
 * straight to the backend and authorises itself with a short-lived ticket
 * from `/api/auth/ws-ticket` instead of the cookie.
 */
export const WS_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const { headers, ...rest } = init;

  const response = await fetch(`${API_BASE}/api${path}`, {
    ...rest,
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  });

  if (response.status === 204) return undefined as T;

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body as { code?: string; message?: string } | null;
    throw new ApiError(
      response.status,
      error?.code ?? "UNKNOWN",
      error?.message ?? `Request failed (${response.status}).`,
    );
  }
  return body as T;
}

/** Is the backend reachable? Used to choose live data over the demo set. */
export async function probeBackend(timeoutMs = 1500): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const response = await fetch(`${API_BASE}/api/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    clearTimeout(timer);
    return response.ok;
  } catch {
    return false;
  }
}

/* ------------------------------------------------------------------ *
 * Response shapes, mirroring the backend schemas.
 * ------------------------------------------------------------------ */

export type Role = "PATIENT" | "PHYSIOTHERAPIST" | "TECHNICIAN" | "ADMIN";

export type ApiUser = {
  id: number;
  email: string;
  name: string;
  preferred_name: string | null;
  role: Role;
  timezone: string;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: ApiUser;
};

export type ApiPatient = {
  id: number;
  name: string;
  operated_leg: "LEFT" | "RIGHT";
  age?: number | null;
  surgery_date?: string | null;
  /** Present only for an assigned clinician; the server omits it otherwise. */
  notes?: string | null;
};

export type Contribution = {
  key: string;
  label: string;
  weight: number;
  normalized: number | null;
  value: number | null;
  contribution: number;
  available: boolean;
  note: string;
};

export type ApiConfidence = {
  value: number;
  percent: number;
  band: "Higher" | "Moderate" | "Lower";
  coverage: number;
  bilateral_coverage: number;
  signal_quality: number;
  explanation: string;
};

export type ApiSessionSummary = {
  rom_deg: number | null;
  cadence_spm: number | null;
  symmetry_index_pct: number | null;
  recovery_score: number | null;
  repetitions: number;
  repetitions_left?: number;
  repetitions_right?: number;
  duration_s: number | null;
  recovery?: { value: number; contributions: Contribution[]; disclaimer: string };
  confidence?: ApiConfidence;
  analytics_version?: string;
};

export type ApiSession = {
  id: number;
  patient_id: number;
  exercise_type: string;
  status: "ACTIVE" | "COMPLETED" | "CANCELLED";
  mode: "LIVE" | "SIMULATED" | "UNKNOWN";
  started_at: string;
  ended_at: string | null;
  summary: ApiSessionSummary | null;
  confidence: ApiConfidence | null;
  analytics_version?: string | null;
};

export type SessionBrief = {
  id: number;
  started_at: string | null;
  day_label: string | null;
  exercise_type: string;
  rom_deg: number | null;
  symmetry_index_pct: number | null;
  cadence_spm: number | null;
  recovery_score: number | null;
  repetitions: number | null;
  confidence: number | null;
  confidence_band: string | null;
  mode: string;
};

export type ApiProgress = {
  patient_id: number;
  session_count: number;
  period_days?: number;
  sessions: SessionBrief[];
  baseline: SessionBrief | null;
  latest: SessionBrief | null;
  trends: Record<string, { slope: number | null; direction: string; n: number }>;
  milestones: { kind: string; session_id: number; title: string; detail: string }[];
  responsible_use: string;
};

export type ApiComparison = {
  baseline: SessionBrief;
  current: SessionBrief;
  deltas: Record<
    string,
    { label: string; unit: string; from: number | null; to: number | null;
      change: number | null; direction: string }
  >;
  summary: string[];
  elapsed_days: number;
  session_count: number;
};

export type ApiReplay = {
  session_id: number;
  duration_s: number;
  exercise_type: string;
  frames: {
    t: number;
    left_knee_angle_deg: number | null;
    right_knee_angle_deg: number | null;
    rom_running_deg: number | null;
    symmetry_index_pct: number | null;
    recovery_score: number | null;
    confidence: number | null;
  }[];
  repetitions: { t: number; leg: string; rep_index: number; rom_deg: number; quality_score: number | null }[];
  events: { t: number; severity: string; message: string }[];
};

export type ApiDevice = {
  id: number;
  device_id: string;
  kind: "HARDWARE" | "SIMULATOR";
  simulated: boolean;
  leg: string | null;
  firmware_version: string | null;
  status: "ONLINE" | "OFFLINE" | "UNKNOWN";
  last_seen: string | null;
  sensors: { type: string; location: string; capability: string; status: string }[];
};

export type ApiExercise = {
  id: number;
  key: string;
  name: string;
  description: string;
  category: string;
  movement_type: string;
  supported_metrics: string[];
  phases: string[];
  cue: string | null;
};

/* ------------------------------------------------------------------ *
 * Endpoints
 * ------------------------------------------------------------------ */

export const api = {
  health: () => apiFetch<{ status: string }>("/health", { auth: false }),

  // Sign-in, sign-up and sign-out live in `lib/auth.ts`: they are the cookie
  // session flow, and keeping them in one place stops a second, divergent
  // notion of "who is signed in" from appearing here.
  me: () => apiFetch<ApiUser>("/me"),

  /** A short-lived ticket authorising one live-session WebSocket. */
  liveTicket: (sessionId: number) =>
    apiFetch<{ ticket: string; session_id: number; expires_in: number }>("/auth/ws-ticket", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),

  patients: (params: { search?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.search) query.set("search", params.search);
    if (params.limit) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return apiFetch<{ items: ApiPatient[]; total: number }>(`/patients${suffix}`);
  },

  patient: (id: number) => apiFetch<ApiPatient>(`/patients/${id}`),

  createPatient: (input: {
    name: string;
    operated_leg: "LEFT" | "RIGHT";
    age?: number | null;
    notes?: string | null;
  }) => apiFetch<ApiPatient>("/patients", { method: "POST", body: JSON.stringify(input) }),

  /**
   * Development-only: generate a populated workspace by streaming real
   * sessions through the simulator. Unavailable when the backend runs with
   * DEBUG off, where it answers 404.
   */
  generateDemoData: (patients = 3) =>
    apiFetch<{
      patient_count: number;
      sessions: number;
      reps: number;
      metrics: number;
      risks: number;
      elapsed_s: number;
      failures: { session_id: number; scenario: string; stderr: string }[];
    }>("/dev/demo-data", { method: "POST", body: JSON.stringify({ patients }) }),
  overview: (id: number) => apiFetch<Record<string, unknown>>(`/patients/${id}/overview`),
  progress: (id: number) => apiFetch<ApiProgress>(`/patients/${id}/progress`),
  timeline: (id: number) => apiFetch<ApiProgress>(`/patients/${id}/timeline`),
  passport: (id: number) => apiFetch<Record<string, unknown>>(`/patients/${id}/passport`),

  compare: (id: number, opts: { baseline?: number; current?: number } = {}) => {
    const query = new URLSearchParams();
    if (opts.baseline) query.set("baseline_session_id", String(opts.baseline));
    if (opts.current) query.set("current_session_id", String(opts.current));
    const suffix = query.toString() ? `?${query}` : "";
    return apiFetch<ApiComparison>(`/patients/${id}/progress/compare${suffix}`);
  },

  sessions: (patientId?: number) =>
    apiFetch<{ items: ApiSession[]; total: number }>(
      `/sessions${patientId ? `?patient_id=${patientId}` : ""}`,
    ),

  session: (id: number) => apiFetch<ApiSession>(`/sessions/${id}`),

  /**
   * Ask the server to run the sensor simulator into this session.
   *
   * The simulator connects to the same `/ws/ingest` socket physical hardware
   * uses, so this is a sensor source rather than a shortcut around ingestion.
   */
  startSimulatedStream: (
    id: number,
    options: { scenario?: string; duration_s?: number; seed?: number } = {},
  ) =>
    apiFetch<{ started: boolean; session_id: number; scenario: string; source: string }>(
      `/sessions/${id}/simulate`,
      { method: "POST", body: JSON.stringify(options) },
    ),

  stopSimulatedStream: (id: number) =>
    apiFetch<void>(`/sessions/${id}/simulate`, { method: "DELETE" }),

  createSession: (patientId: number, exercise: string, idempotencyKey?: string) =>
    apiFetch<ApiSession>("/sessions", {
      method: "POST",
      body: JSON.stringify({
        patient_id: patientId,
        exercise_type: exercise,
        idempotency_key: idempotencyKey,
      }),
    }),

  endSession: (id: number, reportedPain?: number) =>
    apiFetch<ApiSession>(`/sessions/${id}/end`, {
      method: "POST",
      body: JSON.stringify({ reported_pain: reportedPain ?? null }),
    }),

  replay: (id: number) => apiFetch<ApiReplay>(`/sessions/${id}/replay`),
  sessionReport: (id: number) => apiFetch<Record<string, unknown>>(`/sessions/${id}/report`),
  devices: () => apiFetch<{ items: ApiDevice[] }>("/devices"),
  exercises: () => apiFetch<{ items: ApiExercise[] }>("/exercises"),
  notifications: () =>
    apiFetch<{ items: unknown[]; total: number; unread: number }>("/notifications"),
};

/** WebSocket URL for the live session feed. */
/**
 * The live-session socket URL, including its authorisation ticket.
 *
 * This one call goes directly to the backend rather than through the Next
 * proxy, because rewrites do not proxy WebSocket upgrades. A browser cannot
 * set an Authorization header on a WebSocket, so the socket carries a
 * short-lived ticket that is valid only for this session id.
 */
export function liveSocketUrl(sessionId: number, ticket: string): string {
  const base = WS_BASE.replace(/^http/, "ws");
  return `${base}/ws/live/${sessionId}?ticket=${encodeURIComponent(ticket)}`;
}
