"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { MovementFingerprint } from "@/components/workspace/MovementFingerprint";
import { RecoveryJourney } from "@/components/workspace/RecoveryJourney";
import { MovementCore } from "@/components/three/MovementCore";
import { BiomechanicsStage } from "@/components/workspace/BiomechanicsStage";
import { useAnimatedCycle } from "@/components/workspace/useAnimatedCycle";
import {
  contributions,
  exerciseLabels,
  nextFocus,
  scoreWeights,
  whatChanged,
  whatMatters,
} from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { useSessionDetail } from "@/lib/api/useSessionDetail";

export default function OverviewPage() {
  const { session, setSession, role } = useWorkspace();
  const { sessions, mode, patient } = useData();
  const cycle = useAnimatedCycle(3.4);

  const recorded = mode === "live";
  const baseline = sessions[0] ?? session;

  // The composition of the recovery indicator is the backend's, not ours:
  // recomputing the weighting here would eventually disagree with the stored
  // score and with the report generated from it.
  const { scoring } = useSessionDetail(session.id, recorded);
  const factors = scoring
    ? scoring.contributions
        .filter((c) => c.available)
        .map((c) => ({
          key: c.key,
          label: c.label,
          weight: c.weight,
          value: Math.round((c.normalized ?? 0) * 100),
          color: scoreWeights.find((w) => w.key === c.key)?.color ?? "var(--cyan)",
          note: c.note ?? null,
        }))
    : contributions(session).map((f) => ({ ...f, note: null }));

  const changed = whatChanged(baseline, session);
  const matters = whatMatters(session);
  const focus = nextFocus(session);
  const wave = Math.pow(Math.sin(cycle * Math.PI), 2);

  return (
    <>
      <WorkspaceHeader
        eyebrow="RECOVERY ENVIRONMENT"
        title={role === "patient" ? "Where your movement stands today." : "Record overview."}
        lede={
          role === "patient"
            ? "The latest recorded session, in the context of everything before it."
            : "Latest session with baseline comparison, contribution breakdown and signal state."
        }
        stats={[
          { label: "INDICATOR", value: `${session.score}/100` },
          { label: "KNEE ROM", value: `${session.rom}°`, tone: "violet" },
          { label: "SYMMETRY", value: `${session.symmetry}%`, tone: "teal" },
          { label: "COVERAGE", value: `${session.coverage}%`, tone: session.coverage < 70 ? "amber" : "cyan" },
        ]}
        actions={
          <Link className="button button-small" href="/workspace/live">
            Open live lab<ArrowUpRight size={14} />
          </Link>
        }
      />

      {/* Hero row: the body, the signature, the reading. */}
      <div className="ov-hero">
        <section className="ov-body">
          <span className="eyebrow">CURRENT MOVEMENT · {exerciseLabels[session.exercise].toUpperCase()}</span>
          <BiomechanicsStage
            state={{
              left: 8 + wave * (session.peakLeft - 8),
              right: 8 + wave * (session.peakRight - 8),
              phase: cycle,
              active: true,
              degradedRight: session.coverage < 70,
            }}
          />
          <p className="fine-print">
            Conceptual reconstruction from {session.label.toLowerCase()}. Estimated angles, not
            a recording of the patient.
          </p>
        </section>

        <section className="ov-signature">
          <span className="eyebrow">MOVEMENT FINGERPRINT</span>
          <MovementFingerprint session={session} compare={baseline} size={300} />
        </section>

        <section className="ov-read">
          <div className="ov-block">
            <span className="eyebrow">WHAT CHANGED</span>
            <ul>
              {changed.map((line) => <li key={line}>{line}</li>)}
            </ul>
          </div>
          <div className="ov-block ov-matters">
            <span className="eyebrow">WHAT MATTERS</span>
            <strong>{matters.heading}</strong>
            <p>{matters.body}</p>
          </div>
          <div className="ov-block ov-focus">
            <span className="eyebrow">WHAT TO REVIEW</span>
            <dl>
              <div><dt className="mono">FOCUS</dt><dd>{focus.area}</dd></div>
              <div><dt className="mono">OBSERVED</dt><dd>{focus.observed}</dd></div>
              <div><dt className="mono">DISCUSS</dt><dd>{focus.discuss}</dd></div>
            </dl>
          </div>
        </section>
      </div>

      {/* Contribution strip */}
      <section className="ov-contrib">
        <span className="eyebrow">
          INDICATOR COMPOSITION
          {scoring?.analyticsVersion ? ` · ANALYTICS ${scoring.analyticsVersion.toUpperCase()}` : ""}
        </span>
        <div className="ov-contrib-row">
          {factors.map((f) => (
            <div key={f.key} className="ov-contrib-item">
              <span className="ov-contrib-label">{f.label}</span>
              <div className="ov-contrib-bar" aria-hidden="true">
                <i style={{ width: `${f.value}%`, background: f.color }} />
              </div>
              <span className="ov-contrib-value">
                {f.value}
                <em className="mono">×{f.weight.toFixed(2)}</em>
              </span>
              {f.note && <span className="ov-contrib-note">{f.note}</span>}
            </div>
          ))}
        </div>
      </section>

      <RecoveryJourney session={session} onSelect={setSession} />
      {/* Movement Core: this record's own bilateral peaks, in 3D. The sensor
          constellation lives on Devices, where the hardware path belongs. */}
      <section className="mc-panel">
        <div className="mc-head">
          <span className="eyebrow">MOVEMENT CORE · {session.label.toUpperCase()}</span>
          <h3>Both limbs, at the range this session reached.</h3>
          <p className="fine-print">
            Peak flexion of {session.peakLeft}° on the left and {session.peakRight}° on the right.
            The operated limb is highlighted. Estimated indicators, not a recording of the patient.
          </p>
        </div>
        <MovementCore
          mode="compare"
          height={360}
          input={{
            left: session.peakLeft,
            right: session.peakRight,
            baselineLeft: baseline?.peakLeft ?? session.peakLeft,
            baselineRight: baseline?.peakRight ?? session.peakRight,
            confidence: session.coverage / 100,
            operated: patient?.operated_leg ?? null,
            active: true,
          }}
        />
        <div className="mc-legend">
          <span><i className="mc-dot left" /> Left limb</span>
          <span><i className="mc-dot right" /> Right limb</span>
          <span><i className="mc-dot ghost" /> {baseline?.label ?? "Baseline"} (ghost)</span>
        </div>
      </section>
    </>
  );
}
