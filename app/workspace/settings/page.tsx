"use client";

import { useEffect, useState } from "react";
import { LogOut, RotateCcw, Download } from "lucide-react";
import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { SettingsSection, SettingsRow, Toggle } from "@/components/workspace/SettingsRow";
import { useTheme } from "@/components/ui/Providers";
import { useSceneStatus } from "@/components/three/SceneContext";
import { useAuth } from "@/components/auth/AuthProvider";
import { useData } from "@/lib/api/DataProvider";
import { themeLabels } from "@/lib/theme";
import { storePreference, type PreferenceKey } from "@/lib/consent";

/**
 * Settings.
 *
 * A conventional settings page: grouped sections, one row per option, the
 * control beside the sentence that explains it. Preferences that live only in
 * this browser say so, so nobody expects them to follow their account.
 */

const DENSITY_KEY = "rehabsense-density";
const DATEFMT_KEY = "rehabsense-datefmt";
const UNITS_KEY = "rehabsense-units";

function useStored(key: PreferenceKey, fallback: string) {
  const [value, setValue] = useState(fallback);
  useEffect(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored) setValue(stored);
    } catch {
      /* storage unavailable; the default stands */
    }
  }, [key]);
  const update = (next: string) => {
    setValue(next);
    try {
      storePreference(key, next);
    } catch {
      /* not persisted */
    }
  };
  return [value, update] as const;
}

export default function SettingsPage() {
  const { theme, preference, setPreference } = useTheme();
  const { lite, setLite, glActive, reducedMotion, tier } = useSceneStatus();
  const { role, setRole, canSwitch } = useWorkspace();
  const { user, signOut } = useAuth();
  const { patient, patients, mode, exitIllustrative } = useData();

  const [density, setDensity] = useStored(DENSITY_KEY, "comfortable");
  const [dateFmt, setDateFmt] = useStored(DATEFMT_KEY, "auto");
  const [units, setUnits] = useStored(UNITS_KEY, "metric");

  return (
    <>
      <WorkspaceHeader
        eyebrow="SETTINGS"
        title="Settings"
        lede="Account, appearance and workspace preferences. Options marked as browser-only are stored on this device and do not follow your account."
        stats={[
          { label: "SIGNED IN", value: user?.email?.split("@")[0] ?? "—" },
          { label: "THEME", value: themeLabels[theme], tone: "violet" },
          { label: "RENDERING", value: glActive ? "Full 3D" : "Lite", tone: "teal" },
        ]}
      />

      <div className="set-page">
        {/* ---------------- Account ---------------- */}
        <SettingsSection title="Account" note="Details from your RehabSense account.">
          <SettingsRow
            label="Name"
            description="Shown in the workspace and on reports you prepare."
            control={<span className="set-value">{user?.preferred_name || user?.name || "—"}</span>}
          />
          <SettingsRow
            label="Email"
            description="Used to sign in."
            control={<span className="set-value">{user?.email ?? "—"}</span>}
          />
          <SettingsRow
            label="Role"
            description="Set by your account, and enforced by the server on every request."
            control={<span className="set-badge">{user?.role ?? "—"}</span>}
          />
          <SettingsRow
            label="Timezone"
            description="Used to decide which calendar day a session belongs to."
            control={<span className="set-value">{user?.timezone ?? "UTC"}</span>}
          />
          <SettingsRow
            label="Sign out"
            description="Ends this session everywhere, including other devices."
            control={
              <button type="button" className="button button-outline button-small"
                      onClick={() => void signOut()}>
                <LogOut size={14} aria-hidden="true" /> Sign out
              </button>
            }
          />
        </SettingsSection>

        {/* ---------------- Appearance ---------------- */}
        <SettingsSection title="Appearance" note="Stored in this browser only.">
          <SettingsRow
            label="Theme"
            htmlFor="set-theme"
            description="Night Lab is the dark theme; Clinical Daylight is the light one."
            control={
              <select id="set-theme" value={preference}
                      onChange={(e) => setPreference(e.target.value as typeof preference)}>
                <option value="system">Follow system</option>
                <option value="dark">Night Lab (dark)</option>
                <option value="light">Clinical Daylight (light)</option>
              </select>
            }
          />
          <SettingsRow
            label="Density"
            htmlFor="set-density"
            description="How much spacing the workspace uses between panels."
            control={
              <select id="set-density" value={density} onChange={(e) => setDensity(e.target.value)}>
                <option value="comfortable">Comfortable</option>
                <option value="compact">Compact</option>
              </select>
            }
          />
          <SettingsRow
            label="Date format"
            htmlFor="set-date"
            description="Auto follows your device's regional setting."
            control={
              <select id="set-date" value={dateFmt} onChange={(e) => setDateFmt(e.target.value)}>
                <option value="auto">Automatic</option>
                <option value="dmy">31 Dec 2026</option>
                <option value="mdy">Dec 31, 2026</option>
                <option value="iso">2026-12-31</option>
              </select>
            }
          />
          <SettingsRow
            label="Units"
            htmlFor="set-units"
            description="Angles are always degrees; this affects distance and weight where shown."
            control={
              <select id="set-units" value={units} onChange={(e) => setUnits(e.target.value)}>
                <option value="metric">Metric</option>
                <option value="imperial">Imperial</option>
              </select>
            }
          />
        </SettingsSection>

        {/* ---------------- Motion & rendering ---------------- */}
        <SettingsSection
          title="Motion and rendering"
          note="How the movement visualisations are drawn on this device."
        >
          <SettingsRow
            label="Lite visuals"
            htmlFor="set-lite"
            description={
              glActive
                ? "Turn this on to replace the 3D scenes with lighter 2D equivalents. Every figure stays the same."
                : "Currently on, either by choice or because this device reported no usable WebGL."
            }
            control={
              <Toggle id="set-lite" label="Lite visuals" checked={lite} onChange={setLite} />
            }
          />
          <SettingsRow
            label="Reduced motion"
            description="Followed automatically from your system accessibility setting."
            control={
              <span className="set-badge">{reducedMotion ? "On (system)" : "Off"}</span>
            }
          />
          <SettingsRow
            label="Graphics capability"
            description="Detected once when the workspace opens; it decides how much the scenes attempt."
            control={
              <span className="set-value">
                {glActive ? `WebGL available · ${tier === "high" ? "high" : "low"} power` : "No WebGL"}
              </span>
            }
          />
        </SettingsSection>

        {/* ---------------- Workspace ---------------- */}
        <SettingsSection title="Workspace" note="What this account opens onto.">
          <SettingsRow
            label="Default view"
            htmlFor="set-role"
            description={
              canSwitch
                ? "Clinician view adds the patient roster. Patient view shows one record."
                : "Your account holds a patient role, so only the patient view is available."
            }
            control={
              <select id="set-role" value={role} disabled={!canSwitch}
                      onChange={(e) => setRole(e.target.value as typeof role)}>
                <option value="patient">Patient view</option>
                <option value="physio">Clinician view</option>
              </select>
            }
          />
          <SettingsRow
            label="Active record"
            description="The patient the workspace is currently showing."
            control={<span className="set-value">{patient?.name ?? "None selected"}</span>}
          />
          <SettingsRow
            label="Records visible to you"
            description="Enforced server-side; you can only see records assigned to your account."
            control={<span className="set-value">{patients.length}</span>}
          />
        </SettingsSection>

        {/* ---------------- Data ---------------- */}
        <SettingsSection
          title="Data and privacy"
          note="What this workspace is showing, and where it came from."
        >
          <SettingsRow
            label="Data source"
            description="Recorded data comes from your account. Illustrative mode is a separate, clearly-labelled mode."
            control={
              <span className={`set-badge src-${mode}`}>
                {mode === "live" ? "Recorded data"
                  : mode === "illustrative" ? "Illustrative demo"
                  : mode === "empty" ? "No sessions yet"
                  : mode === "offline" ? "API unavailable" : "Checking"}
              </span>
            }
          />
          {mode === "illustrative" && (
            <SettingsRow
              label="Leave illustrative mode"
              description="Return to the data recorded by your own account."
              control={
                <button type="button" className="button button-outline button-small"
                        onClick={exitIllustrative}>
                  <RotateCcw size={14} aria-hidden="true" /> Use recorded data
                </button>
              }
            />
          )}
          <SettingsRow
            label="Export session data"
            description="Session exports are prepared per session from the Reports page."
            control={
              <a className="button button-outline button-small" href="/workspace/reports">
                <Download size={14} aria-hidden="true" /> Go to reports
              </a>
            }
          />
          <SettingsRow
            label="Responsible use"
            description="Every figure in RehabSense is an estimated decision-support indicator. It is not a diagnosis, a clearance criterion or a clinical measurement."
            control={<span className="set-badge">Research prototype</span>}
          />
        </SettingsSection>
      </div>
    </>
  );
}
