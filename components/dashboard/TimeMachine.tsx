"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Play, Pause } from "lucide-react";
import { exerciseLabels, type Session } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { allPresent, metric, plot, score as fmtScore } from "@/lib/format";

/**
 * MOVEMENT TIME MACHINE
 *
 * A temporal scrubber over the recorded sessions. Dragging does not just
 * change a label: the limb traces, the recovery orbit, the confidence halo
 * and every metric interpolate together, so history feels like one continuous
 * movement rather than five separate rows.
 *
 * Values between sessions are interpolated for the *visualisation only* and
 * are labelled as such — no interpolated number is ever presented as a
 * recorded measurement.
 */
export function TimeMachine({
  index,
  onIndex,
  onSettle,
}: {
  index: number;
  onIndex: (value: number) => void;
  onSettle: (session: Session) => void;
}) {
  const { sessions } = useData();
  const [playing, setPlaying] = useState(false);
  const frame = useRef(0);
  const last = useRef(0);

  // Outside the workspace (the landing page and the public dashboard) there
  // is no DataProvider, so this can legitimately receive an empty list. It
  // must render nothing rather than index into it.
  const maxIndex = Math.max(0, sessions.length - 1);
  // The scrub position is owned by the parent and can outlive the list it was
  // set against -- a patient with four recorded sessions replacing a
  // five-entry demo set, for instance. Clamp before indexing so the timeline
  // never reads past the end.
  const safeIndex = Math.min(Math.max(0, index), maxIndex);
  const lower = sessions[Math.floor(safeIndex)];
  const upper = sessions[Math.min(maxIndex, Math.ceil(safeIndex))];
  const hasData = Boolean(lower && upper);
  const t = safeIndex - Math.floor(safeIndex);
  const lerp = (a: number, b: number) => a + (b - a) * t;

  const isExact = Math.abs(safeIndex - Math.round(safeIndex)) < 0.001;
  const settled = sessions[Math.round(safeIndex)];

  useEffect(() => {
    if (isExact && settled) onSettle(settled);
  }, [isExact, settled, onSettle]);

  // Playback walks the timeline at a readable pace, then stops at the end.
  useEffect(() => {
    if (!playing) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setPlaying(false);
      onIndex(maxIndex);
      return;
    }
    last.current = performance.now();
    const step = (now: number) => {
      const dt = (now - last.current) / 1000;
      last.current = now;
      const next = safeIndex + dt * 0.85;
      if (next >= maxIndex) {
        onIndex(maxIndex);
        setPlaying(false);
        return;
      }
      onIndex(next);
      frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [playing, safeIndex, maxIndex, onIndex]);

  // Nothing to travel through. Outside the workspace there is no
  // DataProvider, so an empty list is a normal state, not a failure.
  if (!hasData) {
    return (
      <section className="tm" aria-live="polite">
        <span className="eyebrow">MOVEMENT TIME MACHINE</span>
        <p className="fine-print">No recorded sessions to travel through yet.</p>
      </section>
    );
  }

  // Interpolating between sessions only makes sense where both ends have the
  // value; an unscored session is not a zero to slide towards.
  const score = allPresent(lower.score, upper.score) ? lerp(lower.score!, upper.score!) : null;
  const rom = lerp(lower.rom, upper.rom);
  const symmetry = allPresent(lower.symmetry, upper.symmetry)
    ? lerp(lower.symmetry!, upper.symmetry!)
    : null;
  const coverage = lerp(lower.coverage, upper.coverage);
  const progress = maxIndex === 0 ? 100 : (safeIndex / maxIndex) * 100;

  return (
    <section
      className="time-machine"
      aria-labelledby="tm-title"
      style={{ "--tm-progress": `${progress}%` } as CSSProperties}
    >
      <header className="tm-head">
        <div>
          <span className="eyebrow">MOVEMENT TIME MACHINE</span>
          <h3 id="tm-title">Scrub through the recovery.</h3>
        </div>
        <button
          type="button"
          className="tm-play"
          onClick={() => {
            if (safeIndex >= maxIndex) onIndex(0);
            setPlaying(!playing);
          }}
          aria-pressed={playing}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
          {playing ? "Pause" : "Play timeline"}
        </button>
      </header>

      {/* The temporal field: traces stack back in space as they age. */}
      <div className="tm-field">
        <div className="tm-depth">
          {sessions.map((s, i) => {
            const distance = safeIndex - i;
            const behind = distance > 0;
            const abs = Math.abs(distance);
            return (
              <svg
                key={s.id}
                className={`tm-trace ${abs < 0.5 ? "is-current" : behind ? "is-past" : "is-future"}`}
                viewBox="0 0 320 110"
                preserveAspectRatio="none"
                aria-hidden="true"
                style={
                  {
                    "--d": abs,
                    opacity: Math.max(0, 1 - abs * 0.34),
                    transform: `translate3d(${-distance * 16}px, ${distance * 7}px, 0) scale(${1 - abs * 0.045})`,
                    zIndex: 10 - Math.round(abs * 2),
                  } as CSSProperties
                }
              >
                <path
                  className="tm-path tm-path-left"
                  d={tracePath(s.peakLeft)}
                />
                <path
                  className="tm-path tm-path-right"
                  d={tracePath(s.peakRight, 6)}
                />
              </svg>
            );
          })}
        </div>

        {/* Recovery orbit responds continuously to the scrub position. */}
        <div className="tm-orbit" aria-hidden="true">
          <svg viewBox="0 0 160 160">
            <circle cx="80" cy="80" r="62" className="tm-orbit-track" />
            <circle
              cx="80"
              cy="80"
              r="62"
              className="tm-orbit-value"
              transform="rotate(-90 80 80)"
              strokeDasharray={`${(plot(score) / 100) * 389.5} 389.5`}
            />
            {/* Confidence halo: thinner and dimmer when coverage drops. */}
            <circle
              cx="80"
              cy="80"
              r="74"
              className="tm-halo"
              style={{ opacity: 0.15 + (coverage / 100) * 0.55, strokeWidth: 1 + (coverage / 100) * 3 }}
            />
          </svg>
          <div className="tm-orbit-readout">
            <strong>{fmtScore(score, "")}</strong>
            <span className="mono">INDICATOR</span>
          </div>
        </div>
      </div>

      {/* Interpolated readouts, explicitly marked when between sessions. */}
      <div className="tm-metrics" aria-live="polite">
        <div>
          <span>Knee ROM</span>
          <strong>
            {Math.round(rom)}
            <small>°</small>
          </strong>
        </div>
        <div>
          <span>Symmetry</span>
          <strong>
            {metric(symmetry)}
            <small>%</small>
          </strong>
        </div>
        <div>
          <span>Coverage</span>
          <strong>
            {Math.round(coverage)}
            <small>%</small>
          </strong>
        </div>
        <div className="tm-state">
          <span>{isExact ? "Recorded session" : "Between sessions"}</span>
          <strong>
            {isExact ? settled.label : `${lower.label} → ${upper.label}`}
          </strong>
          {!isExact && <em className="mono">INTERPOLATED FOR DISPLAY</em>}
        </div>
      </div>

      <label className="sr-only" htmlFor="tm-scrub">
        Scrub through recorded sessions
      </label>
      <input
        id="tm-scrub"
        className="tm-scrub"
        type="range"
        min={0}
        max={maxIndex}
        step={0.01}
        value={safeIndex}
        onChange={(event) => {
          setPlaying(false);
          onIndex(Number(event.target.value));
        }}
        aria-valuetext={
          isExact
            ? `${settled.label}, ${settled.dayLabel}, ${exerciseLabels[settled.exercise]}`
            : `Between ${lower.label} and ${upper.label}`
        }
      />

      <ol className="tm-ticks">
        {sessions.map((s, i) => (
          <li key={s.id}>
            <button
              type="button"
              className={Math.round(safeIndex) === i ? "is-active" : ""}
              onClick={() => {
                setPlaying(false);
                onIndex(i);
              }}
              aria-current={Math.round(safeIndex) === i ? "true" : undefined}
            >
              <span className="tm-node" aria-hidden="true" />
              <span className="tm-tick-label">
                {s.dayLabel}
                <small>{exerciseLabels[s.exercise]}</small>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** A single limb's flexion trace across one normalized cycle. */
function tracePath(peak: number, yShift = 0) {
  const points = 40;
  const coords = Array.from({ length: points + 1 }, (_, i) => {
    const t = i / points;
    const v = Math.pow(Math.sin(t * Math.PI), 2) * peak;
    const x = t * 320;
    const y = 104 - (v / 135) * 96 + yShift;
    return `${x.toFixed(1)} ${y.toFixed(1)}`;
  });
  return `M${coords.join(" L")}`;
}
