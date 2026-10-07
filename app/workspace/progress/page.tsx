"use client";

import { useState } from "react";
import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { RecoveryJourney } from "@/components/workspace/RecoveryJourney";
import { ConsistencyGrid } from "@/components/workspace/ConsistencyGrid";
import { MovementFingerprint } from "@/components/workspace/MovementFingerprint";
import { TimeMachine } from "@/components/dashboard/TimeMachine";
import { BilateralMirror } from "@/components/dashboard/BilateralMirror";
import { whatChanged } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { NO_VALUE, allPresent } from "@/lib/format";
import { PatientMovementView } from "@/components/movement/PatientMovementView";

export default function ProgressPage() {
  const { hasMovement, patient } = useData();
  // Hardware-v2 records: movement quality, asymmetry and activity over time.
  if (hasMovement && patient) return <PatientMovementView patientId={patient.id} variant="progress" />;
  return <KneeAngleProgress />;
}

function KneeAngleProgress() {
  const { sessions } = useData();
  const baseline = sessions[0];
  const { session, setSession } = useWorkspace();
  const [scrub, setScrub] = useState(sessions.indexOf(session));
  const changed = whatChanged(baseline, session);

  return (
    <>
      <WorkspaceHeader
        eyebrow="RECOVERY JOURNEY"
        title="Progress is a shape, not a number."
        lede="Move through the recorded period and watch every view follow — the traces, the signature, the comparison and the metrics."
        stats={[
          { label: "PERIOD", value: `${sessions.length} sessions` },
          { label: "BASELINE", value: `${baseline.score}/100`, tone: "violet" },
          { label: "CURRENT", value: `${session.score}/100`, tone: "teal" },
          {
            label: "CHANGE",
            // Only a comparison when both ends were actually scored.
            value: allPresent(session.score, baseline?.score)
              ? `${session.score! - baseline.score! >= 0 ? "+" : ""}${session.score! - baseline.score!}`
              : NO_VALUE,
            tone: "amber",
          },
        ]}
      />

      <RecoveryJourney
        session={session}
        onSelect={(s) => {
          setSession(s);
          setScrub(sessions.indexOf(s));
        }}
      />

      <TimeMachine
        index={scrub}
        onIndex={setScrub}
        onSettle={setSession}
      />

      <div className="pg-split">
        <section className="pg-signature">
          <span className="eyebrow">SIGNATURE VS BASELINE</span>
          <MovementFingerprint session={session} compare={baseline} size={320} />
        </section>
        <section className="pg-changed">
          <span className="eyebrow">WHAT CHANGED</span>
          <ul>
            {changed.map((l) => <li key={l}>{l}</li>)}
          </ul>
          <span className="fine-print">Compared with {baseline.label} ({baseline.dayLabel}).</span>
        </section>
      </div>

      <BilateralMirror current={session} />
      <ConsistencyGrid onSelect={setSession} />
    </>
  );
}
