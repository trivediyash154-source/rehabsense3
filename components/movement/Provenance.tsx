"use client";

import { useEffect, useState } from "react";
import { FlaskConical, X } from "lucide-react";
import type { Provenance } from "@/lib/api/movement";

/**
 * Where a record's data came from, stated on every surface that shows it.
 * The wording is fixed here so no page can soften it.
 */
export const PROVENANCE_BADGE: Record<string, { label: string; tone: string; title: string }> = {
  SYNTHETIC_DEMONSTRATION: {
    label: "SYNTHETIC DEMO",
    tone: "synthetic",
    title: "Synthetic demonstration data: generated movement streamed through the real pipeline. Not patient data, not clinical evidence.",
  },
  PUBLIC_DATASET_REPLAY: {
    label: "PUBLIC DATASET",
    tone: "replay",
    title: "Public dataset replay: public recordings re-sent through the device pipeline. Not RehabSense hardware data.",
  },
  SIMULATED: {
    label: "SIMULATOR",
    tone: "simulated",
    title: "Simulated sensor stream from the RehabSense simulator. Not physical hardware data.",
  },
  PHYSICAL_REGISTERED: {
    label: "REAL HARDWARE",
    tone: "physical",
    title: "Registered RehabSense device, authenticated with its own key.",
  },
  PHYSICAL_UNVERIFIED: {
    label: "UNVERIFIED DEVICE",
    tone: "unverified",
    title: "Not declared simulated, but not a registered device authenticated with its own key.",
  },
};

export function ProvenanceBadge({
  value,
  compact = false,
}: {
  value: Provenance | string | null | undefined;
  compact?: boolean;
}) {
  if (!value) return null;
  const meta = PROVENANCE_BADGE[value] ?? { label: value.replace(/_/g, " "), tone: "unverified", title: value };
  return (
    <span className={`mv-prov mv-prov-${meta.tone}${compact ? " is-compact" : ""}`} title={meta.title}>
      <i aria-hidden="true" />
      {meta.label}
    </span>
  );
}

export function ProvenanceLegend() {
  return (
    <ul className="mv-prov-legend" aria-label="Data provenance categories">
      {(["PHYSICAL_REGISTERED", "PUBLIC_DATASET_REPLAY", "SYNTHETIC_DEMONSTRATION", "SIMULATED", "PHYSICAL_UNVERIFIED"] as const).map(
        (p) => (
          <li key={p}>
            <ProvenanceBadge value={p} />
            <span>{PROVENANCE_BADGE[p].title}</span>
          </li>
        ),
      )}
    </ul>
  );
}

/** The fixed research notice that accompanies every analytic view. */
export function ResearchNote({ synthetic, children }: { synthetic?: boolean; children?: React.ReactNode }) {
  return (
    <p className="mv-research-note">
      {synthetic && <strong>Synthetic demonstration data — not clinical evidence. </strong>}
      {children ?? "Research indicators from a prototype pipeline; not clinically validated. RehabSense is a research prototype and not a medical device."}
    </p>
  );
}

const BANNER_KEY = "rehabsense-demo-banner-collapsed";

/**
 * Shown in the workspace shell whenever the visible data includes the
 * synthetic demonstration cohort. Collapsible to a chip, never removable
 * while that data is on screen.
 */
export function DemoBanner() {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try {
      setCollapsed(sessionStorage.getItem(BANNER_KEY) === "1");
    } catch {
      /* storage unavailable: stays expanded */
    }
  }, []);
  function toggle(next: boolean) {
    setCollapsed(next);
    try {
      sessionStorage.setItem(BANNER_KEY, next ? "1" : "0");
    } catch {
      /* not persisted */
    }
  }
  if (collapsed) {
    return (
      <button type="button" className="mv-demo-chip" onClick={() => toggle(false)} title="Show what this environment is">
        <FlaskConical size={13} aria-hidden="true" />
        <span className="mono">SYNTHETIC DEMONSTRATION ENVIRONMENT</span>
      </button>
    );
  }
  return (
    <div className="mv-demo-banner" role="note">
      <FlaskConical size={16} aria-hidden="true" />
      <div>
        <strong className="mono">SYNTHETIC DEMONSTRATION ENVIRONMENT</strong>
        <p>
          Data shown here is generated/replayed for research and product demonstration. It is not
          real patient data and does not represent clinical validation.
        </p>
      </div>
      <button type="button" onClick={() => toggle(true)} aria-label="Collapse the demonstration notice">
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
