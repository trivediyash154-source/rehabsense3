"use client";

import { useState, type CSSProperties } from "react";
import { Flag, TrendingUp, ShieldAlert, CircleDot } from "lucide-react";
import {
  exerciseLabels,
  type Session,
} from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { plot } from "@/lib/format";

const kindIcon = {
  start: Flag,
  coverage: CircleDot,
  range: TrendingUp,
  consistency: CircleDot,
  trend: ShieldAlert,
  latest: TrendingUp,
} as const;

/**
 * RECOVERY JOURNEY
 *
 * The session history as a travelled path rather than a chart. Each stop
 * carries its own trace, and the path between stops is drawn from the actual
 * indicator values, so the line's shape *is* the progress — including the
 * dip, which a smoothed trend line would hide.
 */
export function RecoveryJourney({
  session,
  onSelect,
}: {
  session: Session;
  onSelect: (session: Session) => void;
}) {
  const { sessions, milestones } = useData();
  const [hover, setHover] = useState<number | null>(null);
  const width = 900;
  const height = 260;
  const padX = 60;
  const padY = 44;

  // A patient can legitimately have one recorded session; dividing by
  // (length - 1) would place it at NaN and blank the whole chart.
  const span = Math.max(1, sessions.length - 1);
  const x = (i: number) => padX + (i / span) * (width - padX * 2);
  const y = (score: number) => height - padY - ((score - 50) / 45) * (height - padY * 2);

  const path = sessions.map((s, i) => `${i === 0 ? "M" : "L"}${x(i)} ${y(plot(s.score))}`).join(" ");
  const area = `${path} L${x(sessions.length - 1)} ${height - padY} L${x(0)} ${height - padY} Z`;
  const activeIndex = sessions.indexOf(session);

  return (
    <section className="journey" aria-labelledby="rj-title">
      <header className="rj-head">
        <div>
          <span className="eyebrow">RECOVERY JOURNEY</span>
          <h3 id="rj-title">Every session, on one path.</h3>
        </div>
        <p className="fine-print">
          Selecting a stop moves the whole workspace into that session.
        </p>
      </header>

      <div className="rj-stage">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Recovery indicator across ${sessions.length} sessions: ${sessions.map((s) => `${s.dayLabel} ${s.score}`).join(", ")}. Illustrative values.`}>
          <defs>
            <linearGradient id="rj-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--cyan)" stopOpacity="0.26" />
              <stop offset="100%" stopColor="var(--cyan)" stopOpacity="0" />
            </linearGradient>
          </defs>

          {[60, 70, 80].map((v) => (
            <g key={v}>
              <line x1={padX} x2={width - padX} y1={y(v)} y2={y(v)} className="rj-grid" />
              <text x={padX - 12} y={y(v) + 4} className="rj-axis" textAnchor="end">{v}</text>
            </g>
          ))}

          <path d={area} fill="url(#rj-fill)" className="rj-area" />
          <path d={path} className="rj-path" />

          {/* Each stop carries the session's own limb trace as a micro-glyph. */}
          {sessions.map((s, i) => {
            const active = i === activeIndex;
            const on = hover === i;
            const milestone = milestones.find((m) => m.sessionId === s.id);
            const Icon = milestone ? kindIcon[milestone.kind] : CircleDot;
            return (
              <g
                key={s.id}
                className={`rj-stop ${active ? "is-active" : ""} ${on ? "is-hover" : ""}`}
                transform={`translate(${x(i)} ${y(plot(s.score))})`}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect(s)}
                role="button"
                tabIndex={0}
                aria-pressed={active}
                aria-label={`${s.label}, ${s.dayLabel}, indicator ${s.score}, ${exerciseLabels[s.exercise]}`}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(s); }
                }}
              >
                <circle r="26" className="rj-hit" />
                <circle r="16" className="rj-halo" />
                <circle r="7" className="rj-node" />
                <text y="-30" className="rj-score">{s.score}</text>
                <text y="34" className="rj-day">{s.dayLabel}</text>
                {(on || active) && (
                  <g className="rj-flyout" transform="translate(0 -96)">
                    <rect x="-84" y="-42" width="168" height="72" rx="9" className="rj-flyout-bg" />
                    <text x="0" y="-22" className="rj-flyout-title">{exerciseLabels[s.exercise]}</text>
                    <text x="0" y="-6" className="rj-flyout-line">ROM {s.rom}° · LSI {s.symmetry}%</text>
                    <text x="0" y="10" className="rj-flyout-line">{s.reps} reps · coverage {s.coverage}%</text>
                    <text x="0" y="24" className="rj-flyout-note">{s.confidence.toUpperCase()} CONFIDENCE</text>
                  </g>
                )}
                <foreignObject x="-9" y="-9" width="18" height="18" className="rj-icon">
                  <span>
                    <Icon size={11} />
                  </span>
                </foreignObject>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Milestone rail: progress events, not medical achievements. */}
      <ol className="rj-milestones">
        {milestones.map((m) => {
          // Never assert here: a milestone whose session is missing must
          // disappear quietly rather than take the whole panel down.
          const target = sessions.find((s) => s.id === m.sessionId);
          if (!target) return null;
          const Icon = kindIcon[m.kind];
          const active = target.id === session.id;
          return (
            <li key={m.id} style={{ "--i": milestones.indexOf(m) } as CSSProperties}>
              <button
                type="button"
                className={active ? "is-active" : ""}
                onClick={() => onSelect(target)}
                aria-pressed={active}
              >
                <span className={`rj-ms-icon kind-${m.kind}`}>
                  <Icon size={13} aria-hidden="true" />
                </span>
                <span className="rj-ms-body">
                  <strong>{m.title}</strong>
                  <small>{m.detail}</small>
                  <em className="mono">{target.dayLabel}</em>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
