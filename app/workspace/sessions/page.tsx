"use client";

import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { MovementReplay } from "@/components/workspace/MovementReplay";
import {
  exerciseLabels,
  repEvents,
  riskEvents,
  formatClock,
} from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { useReplay } from "@/lib/api/useReplay";

export default function SessionsPage() {
  const { sessions, mode } = useData();
  const { session, setSession } = useWorkspace();
  const recorded = useReplay(session.id, mode === "live");
  const illustrative = mode === "illustrative";
  const reps = illustrative ? repEvents(session) : recorded.reps;
  const flags = illustrative ? riskEvents(session) : recorded.risks;

  return (
    <>
      <WorkspaceHeader
        eyebrow="MOVEMENT REPLAY"
        title="Replay the session, not a video of it."
        lede="Every repetition and event sits at its own timestamp. Scrub, jump between repetitions, or play it back at speed."
        stats={[
          { label: "SESSION", value: session.label },
          { label: "DURATION", value: session.duration, tone: "violet" },
          { label: "REPETITIONS", value: String(session.reps), tone: "teal" },
          { label: "EVENTS", value: String(flags.length), tone: "amber" },
        ]}
      />

      <nav className="sx-picker" aria-label="Recorded sessions">
        {sessions.map((s) => (
          <button
            key={s.id}
            type="button"
            className={s.id === session.id ? "is-active" : ""}
            aria-pressed={s.id === session.id}
            onClick={() => setSession(s)}
          >
            <span className="mono">{s.dayLabel}</span>
            <strong>{s.label}</strong>
            <small>{exerciseLabels[s.exercise]}</small>
            <span className={`sx-conf conf-${s.confidence.toLowerCase()}`}>{s.confidence}</span>
          </button>
        ))}
      </nav>

      <MovementReplay session={session} />

      <div className="sx-detail">
        <section>
          <span className="eyebrow">SESSION EVENTS</span>
          <ol className="sx-events">
            {flags.map((f, i) => (
              <li key={`${f.t}-${f.severity}-${i}`} className={`sev-${f.severity.toLowerCase()}`}>
                <span className="mono">{formatClock(f.t)}</span>
                <span className="sx-sev">{f.severity}</span>
                <span>{f.message}</span>
              </li>
            ))}
          </ol>
        </section>
        <section>
          <span className="eyebrow">REPETITION LOG</span>
          <div className="sx-reps">
            {reps.map((r) => (
              // rep_index restarts per limb, so the leg has to be part of the key.
              <div key={`${r.leg}-${r.index}`} className={`sx-rep leg-${r.leg.toLowerCase()}`}>
                <span className="mono">{String(r.index).padStart(2, "0")}</span>
                <span className="sx-rep-bar" aria-hidden="true">
                  <i style={{ height: `${(r.rom / 135) * 100}%` }} />
                </span>
                <span className="sx-rep-rom">{r.rom}°</span>
              </div>
            ))}
          </div>
          <p className="fine-print">
            Illustrative repetition set derived from the session totals. Not recorded movement.
          </p>
        </section>
      </div>
    </>
  );
}
