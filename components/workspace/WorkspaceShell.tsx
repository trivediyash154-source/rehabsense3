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
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  CircleDot,
  Cpu,
  Dumbbell,
  FileText,
  Gauge,
  LayoutGrid,
  Users,
  Settings2,
  History,
  LogOut,
  Target,
} from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { ThemeToggle } from "@/components/ui/Providers";
import { LiteToggle } from "@/components/three/SceneContext";
import { latest, type Session } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { useAuth } from "@/components/auth/AuthProvider";
import { useLiveSessionHandle } from "./LiveSessionProvider";

/** The account's real, backend-enforced role — not the view toggle above. */
/**
 * What the header says about the figures on screen.
 *
 * The previous wording said "LIVE BACKEND · SIGNED IN" whenever the API was
 * reachable, even though the panels below were rendering the illustrative
 * dataset. Read together those implied recorded measurements. These labels
 * describe the data, not the connection.
 */
const MODE_LABEL: Record<string, string> = {
  loading: "CHECKING FOR RECORDED DATA…",
  live: "LIVE BACKEND DATA",
  empty: "NO RECORDED SESSIONS YET",
  unauthenticated: "NOT SIGNED IN",
  offline: "API UNAVAILABLE",
  illustrative: "ILLUSTRATIVE DATA · NOT RECORDED",
};

const MODE_HINT: Record<string, string> = {
  loading: "Checking whether this account has recorded sessions.",
  live: "Every figure shown was recorded by this account and returned by the API.",
  empty: "Signed in, but this patient has no analysable session yet.",
  unauthenticated: "The API is reachable but this browser has no session.",
  offline: "The API is not responding. No substitute figures are being shown.",
  illustrative: "Illustrative figures, entered deliberately. Nothing here was recorded.",
};

const ACCOUNT_ROLE_LABEL: Record<string, string> = {
  PATIENT: "PATIENT ACCOUNT",
  PHYSIOTHERAPIST: "CLINICIAN ACCOUNT",
  TECHNICIAN: "TECHNICIAN ACCOUNT",
  ADMIN: "ADMIN ACCOUNT",
};

/* ------------------------------------------------------------------ *
 * Workspace state
 * One selected session and one role, shared by every route, so moving
 * between views never loses the thing the user was looking at.
 * ------------------------------------------------------------------ */

export type Role = "patient" | "physio";

type WorkspaceValue = {
  session: Session;
  setSession: (session: Session) => void;
  role: Role;
  setRole: (role: Role) => void;
  /** Whether this account may use the clinician view. */
  canSwitch: boolean;
};

const WorkspaceContext = createContext<WorkspaceValue>({
  session: latest,
  setSession: () => undefined,
  role: "patient",
  setRole: () => undefined,
  canSwitch: false,
});

export function useWorkspace() {
  return useContext(WorkspaceContext);
}

const routes = [
  { href: "/workspace", label: "Overview", icon: LayoutGrid, hint: "Recovery environment" },
  { href: "/workspace/live", label: "Live lab", icon: Activity, hint: "Biomechanics lab" },
  { href: "/workspace/focus", label: "Focus", icon: Target, hint: "Recovery focus" },
  { href: "/workspace/progress", label: "Progress", icon: Gauge, hint: "Recovery journey" },
  { href: "/workspace/sessions", label: "Sessions", icon: History, hint: "Movement replay" },
  { href: "/workspace/reports", label: "Reports", icon: FileText, hint: "Recovery receipt" },
  { href: "/workspace/exercises", label: "Exercises", icon: Dumbbell, hint: "Exercise studio" },
  { href: "/workspace/devices", label: "Devices", icon: Cpu, hint: "Sensor constellation" },
  { href: "/workspace/patients", label: "Patients", icon: Users, hint: "Clinician command centre", physioOnly: true },
  { href: "/workspace/settings", label: "Settings", icon: Settings2, hint: "Preferences" },
];

const roleKey = "rehabsense-role";

/** Which account roles may use the clinician view at all. */
function mayActAsClinician(accountRole: string | undefined): boolean {
  return accountRole === "PHYSIOTHERAPIST" || accountRole === "ADMIN";
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { sessions: available } = useData();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [role, setRoleState] = useState<Role>("patient");

  // The selected session is derived from whatever list is currently in play,
  // so when recorded data arrives the whole workspace moves onto it instead of
  // holding a stale demo object. Defaults to the most recent session.
  const session = useMemo(
    () =>
      available.find((entry) => entry.id === selectedId) ??
      available[available.length - 1] ??
      latest,
    [available, selectedId],
  );

  const setSession = useCallback((next: Session) => setSelectedId(next.id), []);

  const canSwitch = mayActAsClinician(user?.role);

  // The view follows the account. A patient account has no clinician view to
  // return to, so the stored preference is only honoured for accounts that
  // actually hold the role -- the server would refuse the data either way,
  // but the navigation should not offer a door that does not open.
  useEffect(() => {
    if (!canSwitch) {
      setRoleState("patient");
      return;
    }
    try {
      const stored = localStorage.getItem(roleKey);
      setRoleState(stored === "patient" ? "patient" : "physio");
    } catch {
      // Storage unavailable; default to the account's own role.
      setRoleState("physio");
    }
  }, [canSwitch]);

  const setRole = useCallback(
    (next: Role) => {
      if (next === "physio" && !canSwitch) return;
      setRoleState(next);
      try {
        localStorage.setItem(roleKey, next);
      } catch {
        /* not persisted */
      }
    },
    [canSwitch],
  );

  const value = useMemo(
    () => ({ session, setSession, role, setRole, canSwitch }),
    [session, setSession, role, setRole, canSwitch],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { session, setSession, role, setRole, canSwitch } = useWorkspace();
  const { mode, sessions, patients, patient, selectPatient, skipped, simulated } = useData();
  const { user, signOut } = useAuth();
  const { sessionId: liveSessionId } = useLiveSessionHandle();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      // replace(), not push(), so Back does not return to a workspace the
      // session no longer authorises.
      router.replace("/login");
      router.refresh();
    } finally {
      setSigningOut(false);
    }
  }
  const [navOpen, setNavOpen] = useState(false);

  const visible = routes.filter((r) => !r.physioOnly || role === "physio");
  const activeIndex = visible.findIndex((r) => r.href === pathname);

  const jump = useCallback(
    (delta: number) => {
      const index = sessions.indexOf(session);
      const next = sessions[Math.min(sessions.length - 1, Math.max(0, index + delta))];
      setSession(next);
    },
    // `sessions` must be a dependency: without it the stepper closes over the
    // list from first render and stops moving once recorded data replaces it.
    [session, sessions, setSession],
  );

  return (
    <div className={`ws-shell role-${role}`}>
      {/* -------- rail -------- */}
      <aside className={`ws-rail ${navOpen ? "is-open" : ""}`}>
        <div className="ws-rail-top">
          <Logo compact />
        </div>

        <nav aria-label="Workspace">
          {/* The indicator slides between items — the spatial cue that you
              moved within one place rather than loading a new page. */}
          <span
            className="ws-indicator"
            aria-hidden="true"
            style={{
              transform: `translateY(${activeIndex * 46}px)`,
              opacity: activeIndex < 0 ? 0 : 1,
            }}
          />
          {visible.map((route) => {
            const Icon = route.icon;
            const active = pathname === route.href;
            return (
              <Link
                key={route.href}
                href={route.href}
                className={active ? "is-active" : ""}
                aria-current={active ? "page" : undefined}
                onClick={() => setNavOpen(false)}
              >
                <Icon size={16} aria-hidden="true" />
                <span className="ws-label">{route.label}</span>
                <span className="ws-hint">{route.hint}</span>
              </Link>
            );
          })}
        </nav>

        <div className="ws-rail-foot">
          {canSwitch && (
            <div className="ws-role" role="group" aria-label="Workspace role">
              <button type="button" aria-pressed={role === "patient"} onClick={() => setRole("patient")}>
                Patient
              </button>
              <button type="button" aria-pressed={role === "physio"} onClick={() => setRole("physio")}>
                Clinician
              </button>
            </div>
          )}

          {user && (
            <div className="ws-account">
              <span className="ws-account-id">
                <strong>{user.preferred_name || user.name}</strong>
                <small className="mono">{ACCOUNT_ROLE_LABEL[user.role]}</small>
              </span>
              <button
                type="button"
                className="ws-signout"
                onClick={handleSignOut}
                disabled={signingOut}
              >
                <LogOut size={14} aria-hidden="true" />
                {signingOut ? "Signing out…" : "Sign out"}
              </button>
            </div>
          )}

          <div className="ws-rail-controls">
            <ThemeToggle systemOption />
          </div>
          <LiteToggle />
        </div>
      </aside>

      {/* -------- main -------- */}
      <div className="ws-main">
        <header className="ws-topbar">
          <button
            type="button"
            className="icon-button ws-nav-toggle"
            onClick={() => setNavOpen(!navOpen)}
            aria-expanded={navOpen}
            aria-label={navOpen ? "Close workspace navigation" : "Open workspace navigation"}
          >
            <CircleDot size={18} />
          </button>

          <div className="ws-context">
            {/* Never implies live data: the source is stated outright. */}
            {/* States what these figures are. "Recorded" is only ever shown
                when every number on screen came back from the backend. */}
            <span className={`ws-source src-${mode}`} title={MODE_HINT[mode]}>
              <i aria-hidden="true" />
              <span className="mono">{MODE_LABEL[mode]}</span>
            </span>
            {patients.length > 1 && (
              <label className="ws-patient-pick">
                <span className="mono">RECORD</span>
                <select
                  value={patient?.id ?? ""}
                  onChange={(e) => selectPatient(Number(e.target.value))}
                  aria-label="Select patient record"
                >
                  {patients.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </label>
            )}
            {sessions.length > 0 && (
            <div className="ws-session-switch">
              <button type="button" onClick={() => jump(-1)} disabled={sessions.indexOf(session) === 0} aria-label="Previous session">
                ‹
              </button>
              <span>
                <strong>{session.label}</strong>
                <small>
                  {patient ? `${patient.name} · ` : ""}
                  {session.dayLabel} · {session.date}
                </small>
              </span>
              <button
                type="button"
                onClick={() => jump(1)}
                disabled={sessions.indexOf(session) === sessions.length - 1}
                aria-label="Next session"
              >
                ›
              </button>
            </div>
            )}
          </div>

          <div className="ws-status">
            {/* Describes the selected session rather than asserting a sensor
                count nothing has verified. */}
            <span className="ws-live-dot" aria-hidden="true" />
            <span className="mono">
              {sessions.length === 0
                ? "NO SESSION SELECTED"
                : `${session.reps} REPS · COVERAGE ${session.coverage}% · ${session.confidence.toUpperCase()} CONFIDENCE · ${session.date}`}
            </span>
            {liveSessionId != null && (
              /* A stream keeps running when the user leaves the lab; say so
                 and offer the way back rather than stranding it. */
              <Link href="/workspace/live" className="ws-live-chip mono">
                <span className="ws-live-pulse" aria-hidden="true" />
                SESSION {liveSessionId} STREAMING
              </Link>
            )}
            {simulated && (
              <span className="ws-status-note mono" title="Every session shown was recorded from the simulator, not from physical hardware.">
                SIMULATED SENSOR STREAM
              </span>
            )}
            {skipped.length > 0 && (
              <span className="ws-status-note mono" title="These sessions were recorded but produced no analysable movement, so they are not charted.">
                {skipped.length} SESSION{skipped.length > 1 ? "S" : ""} WITHOUT USABLE SIGNAL
              </span>
            )}
          </div>
        </header>

        <main id="main" className="ws-canvas">
          {children}
        </main>
      </div>

      {navOpen && <button className="ws-scrim" onClick={() => setNavOpen(false)} aria-label="Close navigation" />}
    </div>
  );
}

/** Shared page header so every route opens with who / what / state. */
export function WorkspaceHeader({
  eyebrow,
  title,
  lede,
  actions,
  stats,
}: {
  eyebrow: string;
  title: string;
  lede?: string;
  actions?: ReactNode;
  stats?: { label: string; value: string; tone?: "cyan" | "teal" | "amber" | "violet" }[];
}) {
  return (
    <header className="ws-head">
      <div className="ws-head-copy">
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {stats && (
        <dl className="ws-head-stats">
          {stats.map((s) => (
            <div key={s.label} className={`tone-${s.tone ?? "cyan"}`}>
              <dt className="mono">{s.label}</dt>
              <dd>{s.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {actions && <div className="ws-head-actions">{actions}</div>}
    </header>
  );
}
