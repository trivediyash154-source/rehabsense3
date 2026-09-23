"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Pause, Rewind, FastForward, SkipBack, SkipForward, TriangleAlert } from "lucide-react";
import { BiomechanicsStage, type LimbState } from "./BiomechanicsStage";
import {
  durationSeconds,
  formatClock,
  repEvents,
  riskEvents,
  type Session,
} from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { useReplay } from "@/lib/api/useReplay";

const SPEEDS = [1, 4, 8, 16];

/**
 * MOVEMENT REPLAY
 *
 * Flight-data replay for a recorded session: transport controls, a timeline
 * carrying every repetition and flag at its own timestamp, and metrics that
 * accumulate as the playhead advances rather than showing the final totals up
 * front. Jumping to a repetition moves the limbs to that moment.
 */
export function MovementReplay({ session }: { session: Session }) {
  const { mode } = useData();
  // Recorded repetitions come from the segmentation stage. In illustrative
  // mode the demo generators stand in, and the mode label says so.
  const recorded = useReplay(session.id, mode === "live");
  const illustrative = mode === "illustrative";

  // Never zero: `time / span` would be 0/0 = NaN, and every derived angle,
  // arc and transform downstream would inherit it and break the SVG.
  const rawSpan = illustrative || !recorded.loaded
    ? durationSeconds(session)
    : recorded.durationSeconds;
  const span = Number.isFinite(rawSpan) && rawSpan > 0 ? rawSpan : 1;
  const reps = illustrative ? repEvents(session) : recorded.reps;
  const flags = illustrative ? riskEvents(session) : recorded.risks;

  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  // Sessions run 14–19 minutes; 1× would show nothing for the first half
  // minute, so replay opens at a rate where events actually arrive.
  const [speed, setSpeed] = useState(8);
  const raf = useRef(0);
  const last = useRef(0);

  /** Move the playhead, clamped into the session and never to NaN. */
  const seek = useCallback(
    (to: number) => setTime(Number.isFinite(to) ? Math.min(span, Math.max(0, to)) : 0),
    [span],
  );

  useEffect(() => {
    setTime(0);
    setPlaying(false);
  }, [session]);

  useEffect(() => {
    if (!playing) return;
    last.current = performance.now();
    const step = (now: number) => {
      const dt = ((now - last.current) / 1000) * speed;
      last.current = now;
      setTime((t) => {
        const next = t + dt;
        if (next >= span) {
          setPlaying(false);
          return span;
        }
        return next;
      });
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [playing, speed, span]);

  // Limb state is derived from the playhead, so scrubbing and playing agree.
  // reps can legitimately be 0 for a session that recorded no cycles.
  const cycles = Math.max(1, session.reps);
  const progress = Math.min(1, Math.max(0, time / span));
  const cycle = progress * cycles;
  const phase = cycle % 1;
  const envelope = 0.55 + 0.45 * progress;
  const stateNow: LimbState = {
    left: 8 + Math.pow(Math.sin(phase * Math.PI), 2) * (session.peakLeft - 8) * envelope,
    right: 8 + Math.pow(Math.sin((((cycle - 0.06) % 1) + 1) % 1 * Math.PI), 2) * (session.peakRight - 8) * envelope,
    phase,
    active: playing,
    degradedRight: session.coverage < 70 && time > span * 0.42,
  };

  const passed = reps.filter((r) => r.t <= time);
  const activeFlags = flags.filter((f) => f.t <= time);
  const lastRep = passed[passed.length - 1];

  const jumpRep = useCallback(
    (delta: number) => {
      const index = passed.length - 1 + delta;
      const target = reps[Math.min(reps.length - 1, Math.max(0, index))];
      if (target) seek(target.t);
    },
    [passed.length, reps, seek],
  );

  return (
    <div className="replay">
      <div className="replay-stage">
        <BiomechanicsStage state={stateNow} />
        <div className="replay-overlay ov-tl">
          <span className="mono">PLAYHEAD</span>
          <strong className="tabular">{formatClock(time)}</strong>
          <em>of {session.duration}</em>
        </div>
        <div className="replay-overlay ov-tr">
          <span className="mono">REPETITIONS</span>
          <strong className="tabular">
            {passed.length}
            <small>/{session.reps}</small>
          </strong>
          {lastRep && <em>last {lastRep.leg.toLowerCase()} · {lastRep.rom}°</em>}
        </div>
        {activeFlags.some((f) => f.severity === "WARNING") && (
          <div className="replay-flag">
            <TriangleAlert size={14} aria-hidden="true" />
            {activeFlags.filter((f) => f.severity === "WARNING").slice(-1)[0].message}
          </div>
        )}
      </div>

      {/* transport */}
      <div className="replay-transport">
        <button type="button" onClick={() => jumpRep(-1)} aria-label="Previous repetition"><SkipBack size={15} /></button>
        <button type="button" onClick={() => setTime((t) => Math.max(0, t - 5))} aria-label="Back 5 seconds"><Rewind size={15} /></button>
        <button
          type="button"
          className="replay-play"
          onClick={() => {
            if (time >= span) setTime(0);
            setPlaying(!playing);
          }}
          aria-label={playing ? "Pause replay" : "Play replay"}
        >
          {playing ? <Pause size={17} /> : <Play size={17} />}
        </button>
        <button type="button" onClick={() => setTime((t) => Math.min(span, t + 5))} aria-label="Forward 5 seconds"><FastForward size={15} /></button>
        <button type="button" onClick={() => jumpRep(1)} aria-label="Next repetition"><SkipForward size={15} /></button>

        <div className="replay-speeds" role="group" aria-label="Playback speed">
          {SPEEDS.map((s) => (
            <button key={s} type="button" aria-pressed={speed === s} onClick={() => setSpeed(s)}>
              {s}×
            </button>
          ))}
        </div>
      </div>

      {/* timeline with events pinned at their timestamps */}
      <div className="replay-timeline">
        <label className="sr-only" htmlFor="replay-scrub">Scrub session timeline</label>
        <input
          id="replay-scrub"
          type="range"
          min={0}
          max={span}
          step={0.1}
          value={time}
          onChange={(e) => {
            setPlaying(false);
            seek(Number(e.target.value));
          }}
          style={{ "--p": `${(time / span) * 100}%` } as React.CSSProperties}
          aria-valuetext={`${formatClock(time)} of ${session.duration}, ${passed.length} repetitions elapsed`}
        />
        <div className="replay-marks" aria-hidden="true">
          {reps.map((r) => (
            <button
              key={`${r.leg}-${r.index}`}
              type="button"
              className={`mark mark-rep leg-${r.leg.toLowerCase()} ${r.t <= time ? "is-passed" : ""}`}
              style={{ left: `${(r.t / span) * 100}%` }}
              onClick={() => { setPlaying(false); seek(r.t); }}
              title={`Repetition ${r.index} · ${r.leg} · ${r.rom}°`}
            />
          ))}
          {flags.map((f, i) => (
            <button
              key={`flag-${i}`}
              type="button"
              className={`mark mark-flag sev-${f.severity.toLowerCase()}`}
              style={{ left: `${(f.t / span) * 100}%` }}
              onClick={() => { setPlaying(false); seek(f.t); }}
              title={f.message}
            />
          ))}
        </div>
        <div className="replay-scale">
          <span className="mono">00:00</span>
          <span className="mono">{session.duration}</span>
        </div>
      </div>

      <ol className="replay-log">
        {[...passed].reverse().slice(0, 6).map((r) => (
          <li key={`${r.leg}-${r.index}`}>
            <span className="mono">{formatClock(r.t)}</span>
            <span className={`leg-chip leg-${r.leg.toLowerCase()}`}>{r.leg}</span>
            <span>Repetition {r.index} · {r.rom}°</span>
            <span className="rep-quality" aria-label={`Illustrative quality ${Math.round(r.quality * 100)} percent`}>
              <i style={{ width: `${r.quality * 100}%` }} />
            </span>
          </li>
        ))}
        {passed.length === 0 && (
          <li className="replay-log-empty">Play or scrub to see repetitions as they occur.</li>
        )}
      </ol>
    </div>
  );
}
