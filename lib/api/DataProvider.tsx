"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, type ApiPatient } from "./client";
import {
  adaptMilestones,
  adaptSessions,
  hasMovementAnalytics,
  type ApiProgress,
  type ApiSessionBrief,
} from "./adapters";
import {
  milestones as demoMilestones,
  sessions as demoSessions,
  type Milestone,
  type Session,
} from "@/lib/demo-data";
import { storePreference } from "@/lib/consent";

/**
 * The one place that decides what the workspace is looking at.
 *
 * The rule this file exists to enforce: **a backend failure never becomes
 * demo content.** Falling back to `demo-data` when a request fails produces an
 * interface that looks healthy while showing fiction, which is precisely how
 * a polished screen ends up reading "LIVE BACKEND" above someone else's
 * numbers. Every non-live outcome is its own visible state instead, and the
 * illustrative dataset is only ever shown because a person asked for it.
 */
export type DataMode =
  /** Still determining what is available. */
  | "loading"
  /** Real recorded data for a real patient. */
  | "live"
  /** Signed in and reachable, but nothing analysable has been recorded. */
  | "empty"
  /** Backend is up; this browser is not signed in. */
  | "unauthenticated"
  /** Backend unreachable or erroring. Never silently replaced by demo. */
  | "offline"
  /** Illustrative dataset, entered deliberately by the user. */
  | "illustrative";

/** Where the numbers on screen came from. Derived, never hand-written. */
export type DataSourceLabel =
  | "REAL"
  | "SIMULATED"
  | "SYNTHETIC_DEMONSTRATION"
  | "PUBLIC_DATASET_REPLAY"
  | "ILLUSTRATIVE"
  | "UNAVAILABLE";

const DEMO_KEY = "rehabsense-illustrative-mode";

type DataContextValue = {
  mode: DataMode;
  /** Coarse label shared by header, workspace, live view and reports. */
  sourceLabel: DataSourceLabel;
  authenticated: boolean;
  /** Every patient this account may see, for the workspace switcher. */
  patients: ApiPatient[];
  patient: ApiPatient | null;
  /** Switch the whole workspace onto another patient. */
  selectPatient: (id: number) => void;
  progress: ApiProgress | null;
  /**
   * Sessions to render. Empty unless the mode actually has data — callers
   * must not receive demo rows while the mode says something else.
   */
  sessions: Session[];
  milestones: Milestone[];
  /** Recorded sessions that produced no analysable movement. */
  skipped: ApiSessionBrief[];
  totalRepetitions: number | null;
  analyticsVersion: string | null;
  /** True when every displayed session came from a simulated sensor stream. */
  simulated: boolean;
  /** The selected record has hardware-v2 (dual IMU) movement sessions. */
  hasMovement: boolean;
  /** Completed v2 sessions of the selected record with indicators. */
  movementCount: number;
  /** Some record this account can see is synthetic demonstration data. */
  synthetic: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /** Explicit opt in/out of the illustrative dataset. */
  enterIllustrative: () => void;
  exitIllustrative: () => void;
};

const EMPTY: Session[] = [];

const DataContext = createContext<DataContextValue>({
  mode: "loading",
  sourceLabel: "UNAVAILABLE",
  authenticated: false,
  patients: [],
  patient: null,
  selectPatient: () => undefined,
  progress: null,
  sessions: EMPTY,
  milestones: [],
  skipped: [],
  totalRepetitions: null,
  analyticsVersion: null,
  simulated: false,
  hasMovement: false,
  movementCount: 0,
  synthetic: false,
  error: null,
  refresh: async () => undefined,
  enterIllustrative: () => undefined,
  exitIllustrative: () => undefined,
});

export function useData() {
  return useContext(DataContext);
}

const SELECTED_KEY = "rehabsense-selected-patient";

export function DataProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<DataMode>("loading");
  const [demo, setDemo] = useState(false);
  const [patients, setPatients] = useState<ApiPatient[]>([]);
  const [patient, setPatient] = useState<ApiPatient | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [progress, setProgress] = useState<ApiProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Demo mode is sticky per browser, but only ever set by a user action.
  useEffect(() => {
    try {
      if (localStorage.getItem(DEMO_KEY) === "1") setDemo(true);
    } catch {
      /* storage unavailable; demo simply will not persist */
    }
  }, []);

  const load = useCallback(async () => {
    setError(null);

    // One request answers everything the old probe -> /me -> roster chain
    // asked in three sequential round trips: a 401 means signed out, a
    // network or gateway failure means the API is unreachable, and anything
    // else is the roster. No short timeout either: a serverless API waking
    // from idle takes a few seconds, and that is "starting", not "offline".
    try {
      // The whole roster, so a clinician can move between records without a
      // reload. Bounded because a real clinic list is not unlimited.
      const listing = await api.patients({ limit: 100 });
      const roster = listing.items ?? [];
      setPatients(roster);

      // Honour a previously chosen record; otherwise open the first.
      let wanted: number | null = selectedId;
      if (wanted == null) {
        try {
          const stored = localStorage.getItem(SELECTED_KEY);
          wanted = stored ? Number(stored) : null;
        } catch {
          wanted = null;
        }
      }
      // Without a stored choice: a real person's record first, then the
      // first synthetic demonstration record; a public-dataset reference
      // record is never the default.
      const byId = [...roster].sort((a, b) => a.id - b.id);
      const chosen =
        roster.find((p) => p.id === wanted) ??
        byId.find((p) => !p.provenance) ??
        byId.find((p) => p.provenance === "SYNTHETIC_DEMONSTRATION") ??
        roster[0] ??
        null;
      setPatient(chosen);

      if (!chosen) {
        setProgress(null);
        setMode("empty");
        return;
      }

      const loaded = (await api.progress(chosen.id)) as unknown as ApiProgress;
      setProgress(loaded);
      const usable = adaptSessions(loaded.sessions ?? []).sessions;
      const movement = (loaded.sessions ?? []).filter(hasMovementAnalytics);
      setMode(usable.length > 0 || movement.length > 0 ? "live" : "empty");
    } catch (cause) {
      // A failure here is a failure, not an empty account. Saying "no data"
      // would hide a broken endpoint behind a plausible-looking screen.
      setPatients([]);
      setPatient(null);
      setProgress(null);
      if (cause instanceof ApiError && cause.status === 401) {
        setMode("unauthenticated");
        return;
      }
      setMode("offline");
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The RehabSense API is not responding.",
      );
    }
    // selectedId must be a dependency: with an empty array this callback
    // captures the first render's value forever, and switching patients
    // silently reloads the same record.
  }, [selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Move the entire workspace onto another record. */
  const selectPatient = useCallback((id: number) => {
    setSelectedId(id);
    try {
      storePreference(SELECTED_KEY, String(id));
    } catch {
      /* selection simply will not persist */
    }
  }, []);

  const enterIllustrative = useCallback(() => {
    setDemo(true);
    try {
      storePreference(DEMO_KEY, "1");
    } catch {
      /* not persisted */
    }
  }, []);

  const exitIllustrative = useCallback(() => {
    setDemo(false);
    try {
      localStorage.removeItem(DEMO_KEY);
    } catch {
      /* not persisted */
    }
    void load();
  }, [load]);

  const value = useMemo<DataContextValue>(() => {
    const adapted = progress ? adaptSessions(progress.sessions ?? []) : null;
    const liveRows = adapted?.sessions ?? EMPTY;

    // Demo is an override the user chose; it never activates on failure.
    const effectiveMode: DataMode = demo ? "illustrative" : mode;
    const usingDemo = effectiveMode === "illustrative";
    const hasLive = effectiveMode === "live" && liveRows.length > 0;

    const sessions = usingDemo ? demoSessions : hasLive ? liveRows : EMPTY;
    const simulated =
      hasLive && (progress?.sessions ?? []).every((s) => s.mode === "SIMULATED");
    const movementCount = usingDemo
      ? 0
      : (progress?.sessions ?? []).filter(hasMovementAnalytics).length;
    const hasMovement = effectiveMode === "live" && movementCount > 0;
    const synthetic = !usingDemo && patients.some((p) => p.provenance === "SYNTHETIC_DEMONSTRATION");
    const recordProvenance = usingDemo ? null : (patient?.provenance ?? null);

    const sourceLabel: DataSourceLabel = usingDemo
      ? "ILLUSTRATIVE"
      : recordProvenance === "SYNTHETIC_DEMONSTRATION" && (hasLive || hasMovement)
        ? "SYNTHETIC_DEMONSTRATION"
        : recordProvenance === "PUBLIC_DATASET_REPLAY" && (hasLive || hasMovement)
          ? "PUBLIC_DATASET_REPLAY"
          : hasLive
            ? simulated
              ? "SIMULATED"
              : "REAL"
            : hasMovement
              ? "REAL"
              : "UNAVAILABLE";

    return {
      mode: effectiveMode,
      sourceLabel,
      authenticated: mode !== "unauthenticated" && mode !== "offline" && mode !== "loading",
      patients: usingDemo ? [] : patients,
      patient: usingDemo ? null : patient,
      selectPatient,
      progress: usingDemo ? null : progress,
      sessions,
      milestones: usingDemo
        ? demoMilestones
        : hasLive
          ? adaptMilestones(progress?.milestones ?? [], liveRows)
          : [],
      skipped: usingDemo ? [] : (adapted?.skipped ?? []),
      totalRepetitions: usingDemo ? null : (progress?.total_repetitions ?? null),
      analyticsVersion: usingDemo ? null : (progress?.analytics_version ?? null),
      simulated,
      hasMovement,
      movementCount,
      synthetic,
      error,
      refresh: load,
      enterIllustrative,
      exitIllustrative,
    };
  }, [mode, demo, patients, patient, selectPatient, progress, error, load,
      enterIllustrative, exitIllustrative]);

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}
