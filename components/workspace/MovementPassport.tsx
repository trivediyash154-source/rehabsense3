"use client";

import { MovementFingerprint } from "./MovementFingerprint";
import {
  exerciseLabels,
} from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { plot } from "@/lib/format";

/**
 * MOVEMENT PASSPORT
 *
 * The cumulative artifact: who this record belongs to, where it started,
 * where it is now, and the shape of the movement across the whole period.
 * Not a certificate — nothing is awarded — and not a profile table. It reads
 * as an identity document for a body of recorded movement.
 */
export function MovementPassport() {
  const { sessions, milestones, totalRepetitions, patient } = useData();
  const baseline = sessions[0];
  const latest = sessions[sessions.length - 1];

  // The backend counts repetitions across every session, including any this
  // view does not chart; prefer its total over a sum of what is on screen.
  const totalReps = totalRepetitions ?? sessions.reduce((n, s) => n + s.reps, 0);
  const span = latest && baseline ? latest.day - baseline.day : 0;
  const trend = sessions.map((s) => s.score);

  return (
    <article className="passport">
      <div className="passport-band" aria-hidden="true" />

      <header className="passport-head">
        <div>
          <span className="mono">REHABSENSE · MOVEMENT PASSPORT</span>
          <h2>A record of how this body has been moving.</h2>
          <p className="fine-print">
            {patient
              ? `${patient.name} · recorded in this workspace`
              : "Demo record · no patient identity is connected to this workspace."}
          </p>
        </div>
        <div className="passport-seal" aria-hidden="true">
          <svg viewBox="0 0 84 84">
            <circle cx="42" cy="42" r="38" className="seal-ring" />
            <circle cx="42" cy="42" r="30" className="seal-ring seal-inner" />
            <path d="M42 16 L42 40 M42 44 L42 68" className="seal-axis" />
            <circle cx="42" cy="42" r="6" className="seal-core" />
            <text x="42" y="78" className="seal-text" textAnchor="middle">RS · PROTOTYPE</text>
          </svg>
        </div>
      </header>

      <dl className="passport-identity">
        <div><dt className="mono">RECORD</dt><dd>Demo patient</dd></div>
        <div><dt className="mono">OPERATED LIMB</dt><dd>Left (illustrative)</dd></div>
        <div><dt className="mono">PERIOD</dt><dd>{span} days</dd></div>
        <div><dt className="mono">SESSIONS</dt><dd>{sessions.length}</dd></div>
        <div><dt className="mono">REPETITIONS</dt><dd>{totalReps}</dd></div>
        <div><dt className="mono">EXERCISES</dt><dd>{new Set(sessions.map((s) => s.exercise)).size} types</dd></div>
      </dl>

      <div className="passport-body">
        <section className="passport-shape">
          <span className="eyebrow">MOVEMENT SIGNATURE</span>
          <MovementFingerprint session={latest} compare={baseline} size={280} />
          <p className="fine-print">
            Solid shape: {latest.label}. Ghost: {baseline.label}. The signature is a shape, not
            a score — two sessions with the same indicator can look entirely different.
          </p>
        </section>

        <section className="passport-story">
          <span className="eyebrow">BASELINE → CURRENT</span>
          <div className="passport-slope">
            {[
              ["Knee ROM", baseline.rom, latest.rom, "°"],
              ["Symmetry", baseline.symmetry, latest.symmetry, "%"],
              ["Cadence", baseline.cadence, latest.cadence, ""],
              ["Indicator", baseline.score, latest.score, ""],
            ].map(([label, from, to, unit]) => {
              const f = Number(from);
              const t = Number(to);
              const up = t >= f;
              return (
                <div key={String(label)} className={`slope ${up ? "is-up" : "is-down"}`}>
                  <span className="slope-label">{label}</span>
                  <svg viewBox="0 0 80 34" aria-hidden="true">
                    <line x1="6" y1={30 - (f / 135) * 26} x2="74" y2={30 - (t / 135) * 26} className="slope-line" />
                    <circle cx="6" cy={30 - (f / 135) * 26} r="3" className="slope-a" />
                    <circle cx="74" cy={30 - (t / 135) * 26} r="3.6" className="slope-b" />
                  </svg>
                  <span className="slope-values">
                    <em>{f}{String(unit)}</em>
                    <strong>{t}{String(unit)}</strong>
                  </span>
                </div>
              );
            })}
          </div>

          <span className="eyebrow">TRAJECTORY</span>
          <svg viewBox="0 0 300 70" className="passport-trend" aria-label={`Indicator trajectory: ${trend.join(", ")}`}>
            <path
              className="pp-trend-line"
              d={trend
                .map((v, i) => `${i === 0 ? "M" : "L"}${(i / Math.max(1, trend.length - 1)) * 288 + 6} ${64 - ((plot(v) - 50) / 40) * 56}`)
                .join(" ")}
            />
            {trend.map((v, i) => (
              <circle
                key={i}
                cx={(i / Math.max(1, trend.length - 1)) * 288 + 6}
                cy={64 - ((plot(v) - 50) / 40) * 56}
                r="3.2"
                className="pp-trend-dot"
              />
            ))}
          </svg>

          <span className="eyebrow">PROGRESS EVENTS</span>
          <ul className="passport-events">
            {milestones.map((m) => {
              const s = sessions.find((x) => x.id === m.sessionId);
              if (!s) return null;
              return (
                <li key={m.id}>
                  <span className="mono">{s.dayLabel}</span>
                  <span>{m.title}</span>
                  <em>{exerciseLabels[s.exercise]}</em>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <footer className="passport-foot">
        <span className="mono">RESEARCH PROTOTYPE · ESTIMATED INDICATORS · NOT A MEDICAL DEVICE</span>
      </footer>
    </article>
  );
}
