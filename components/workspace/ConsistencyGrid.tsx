"use client";

import { useState } from "react";
import { consistencyDays, exerciseLabels, type Session } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";

/**
 * MOVEMENT CONSISTENCY
 *
 * A 28-day field where recorded sessions are lit by their indicator. No
 * streaks, no badges, no gamification — recording a session is not an
 * achievement, and missing one is not a failure. It simply shows the shape
 * of activity so a clinician can see whether the data is evenly spread.
 */
export function ConsistencyGrid({ onSelect }: { onSelect: (session: Session) => void }) {
  const { sessions } = useData();
  const [hover, setHover] = useState<number | null>(null);
  const recorded = consistencyDays.filter((d) => d.sessionId).length;
  const hovered = hover !== null ? consistencyDays[hover] : null;
  const hoveredSession = hovered?.sessionId
    ? sessions.find((s) => s.id === hovered.sessionId)
    : null;

  return (
    <section className="consistency" aria-labelledby="cg-title">
      <header>
        <span className="eyebrow">MOVEMENT CONSISTENCY</span>
        <h3 id="cg-title">Where the data actually came from.</h3>
      </header>

      <div className="cg-grid" role="img" aria-label={`${recorded} sessions recorded across 28 days. Days without a session are unlit.`}>
        {consistencyDays.map((day, i) => (
          <button
            key={day.day}
            type="button"
            className={`cg-cell ${day.sessionId ? "has-session" : ""}`}
            style={{ "--intensity": day.intensity } as React.CSSProperties}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
            onClick={() => {
              const s = sessions.find((x) => x.id === day.sessionId);
              if (s) onSelect(s);
            }}
            disabled={!day.sessionId}
            aria-label={
              day.sessionId
                ? `Day ${day.day}: session recorded`
                : `Day ${day.day}: no session`
            }
          >
            <span />
          </button>
        ))}
      </div>

      <div className="cg-foot" aria-live="polite">
        {hoveredSession ? (
          <p>
            <strong>{hoveredSession.label}</strong> · {exerciseLabels[hoveredSession.exercise]} ·
            indicator {hoveredSession.score} · coverage {hoveredSession.coverage}%
          </p>
        ) : hovered ? (
          <p className="muted-line">Day {hovered.day} — no session recorded.</p>
        ) : (
          <p className="muted-line">
            {recorded} sessions across 28 days. Gaps are expected; this is not an adherence score.
          </p>
        )}
      </div>
    </section>
  );
}
