"use client";

import { useState } from "react";
import { Play, Pause, Square, Plus, LoaderCircle, TriangleAlert } from "lucide-react";
import {
  clock,
  clockTime,
  humanDuration,
  type FocusBlock,
  type TodayPayload,
} from "@/lib/api/focus";
import { exerciseLabels, type ExerciseType } from "@/lib/demo-data";

/**
 * TODAY'S RECOVERY FOCUS
 *
 * The dial shows engaged time against the plan. Every number displayed is the
 * backend's; the component projects the running second only so the digits
 * move, and reconciles against the server on every read.
 */

const EXERCISES: ExerciseType[] = [
  "WALK", "SQUAT", "SIT_TO_STAND", "STEP_UP", "SINGLE_LEG_BALANCE",
];

const STATUS_COPY: Record<string, string> = {
  READY: "NOT STARTED",
  ACTIVE: "ACTIVE",
  PAUSED: "PAUSED",
  COMPLETED: "COMPLETED",
  CANCELLED: "CANCELLED",
  INTERRUPTED: "INTERRUPTED",
};

export function FocusPanel({
  today,
  block,
  engagedS,
  remainingS,
  completionPct,
  busy,
  onCreate,
  onStart,
  onPause,
  onResume,
  onComplete,
  onCancel,
}: {
  today: TodayPayload | null;
  block: FocusBlock | null;
  engagedS: number;
  remainingS: number;
  completionPct: number;
  busy: boolean;
  onCreate: (input: { target_duration_s: number; exercise_type: string }) => void;
  onStart: (id: number) => void;
  onPause: (id: number) => void;
  onResume: (id: number) => void;
  onComplete: (id: number) => void;
  onCancel: (id: number) => void;
}) {
  const presets = today?.presets_s ?? [300, 600, 900, 1200, 1500, 1800, 2700, 3600];
  const [target, setTarget] = useState(1800);
  const [custom, setCustom] = useState("");
  const [exercise, setExercise] = useState<ExerciseType>("WALK");

  const planned = today?.blocks ?? [];
  const nextReady = planned.find((b) => b.status === "READY") ?? null;
  const current = block ?? nextReady;
  const threshold = today?.adherence_threshold_pct ?? 80;

  // The ring is a fraction of the plan, clamped for drawing only; the label
  // still reports the true percentage when a patient exceeds their target.
  const ringPct = Math.min(100, completionPct);
  const CIRC = 2 * Math.PI * 78;

  const customSeconds = (() => {
    const value = Number.parseInt(custom, 10);
    return Number.isFinite(value) && value > 0 ? value * 60 : null;
  })();

  return (
    <section className="fx-panel">
      <header className="fx-head">
        <span className="eyebrow">TODAY&apos;S RECOVERY FOCUS</span>
        <p className="fine-print">
          A day counts towards your streak when at least {threshold}% of the minutes you
          planned were actually worked.
        </p>
      </header>

      <div className="fx-body">
        {/* ---- the dial ---- */}
        <div className="fx-dial">
          <svg viewBox="0 0 180 180" role="img"
               aria-label={`${Math.round(completionPct)} percent of today's target`}>
            <circle cx="90" cy="90" r="78" className="fx-ring-track" />
            <circle
              cx="90" cy="90" r="78"
              className={`fx-ring-value ${current?.status === "PAUSED" ? "is-paused" : ""}`}
              strokeDasharray={`${(ringPct / 100) * CIRC} ${CIRC}`}
              transform="rotate(-90 90 90)"
            />
          </svg>
          <div className="fx-dial-inner">
            {current ? (
              <>
                <strong className="fx-clock tabular">{clock(engagedS)}</strong>
                <span className="fx-of mono">
                  / {clock(current.target_duration_s)}
                </span>
                <span className={`fx-status st-${current.status.toLowerCase()}`}>
                  {STATUS_COPY[current.status] ?? current.status}
                </span>
              </>
            ) : (
              <>
                <strong className="fx-clock tabular">--:--</strong>
                <span className="fx-of mono">NO TARGET SET</span>
              </>
            )}
          </div>
        </div>

        {/* ---- plan / controls ---- */}
        <div className="fx-controls">
          {!current && (
            <div className="fx-plan">
              <span className="eyebrow">SET TODAY&apos;S TARGET</span>
              <div className="fx-presets" role="group" aria-label="Target duration">
                {presets.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={target === s && !customSeconds ? "is-active" : ""}
                    aria-pressed={target === s && !customSeconds}
                    onClick={() => { setTarget(s); setCustom(""); }}
                  >
                    {humanDuration(s)}
                  </button>
                ))}
              </div>

              <label className="fx-custom">
                <span className="mono">CUSTOM (MINUTES)</span>
                <input
                  type="number" min={1} max={360} inputMode="numeric"
                  value={custom} placeholder="e.g. 90"
                  onChange={(e) => setCustom(e.target.value)}
                />
              </label>

              <label className="fx-exercise">
                <span className="mono">EXERCISE</span>
                <select value={exercise} onChange={(e) => setExercise(e.target.value as ExerciseType)}>
                  {EXERCISES.map((x) => (
                    <option key={x} value={x}>{exerciseLabels[x]}</option>
                  ))}
                </select>
              </label>

              <button
                type="button" className="button full-width" disabled={busy}
                onClick={() => onCreate({
                  target_duration_s: customSeconds ?? target,
                  exercise_type: exercise,
                })}
              >
                {busy ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}
                Set target · {humanDuration(customSeconds ?? target)}
              </button>
            </div>
          )}

          {current && (
            <div className="fx-live">
              <dl className="fx-facts">
                <div>
                  <dt className="mono">TARGET</dt>
                  <dd>{humanDuration(current.target_duration_s)}</dd>
                </div>
                <div>
                  <dt className="mono">EXERCISE</dt>
                  <dd>{exerciseLabels[current.exercise_type as ExerciseType] ?? current.exercise_type}</dd>
                </div>
                <div>
                  <dt className="mono">REMAINING</dt>
                  <dd className="tabular">{clock(remainingS)}</dd>
                </div>
                <div>
                  <dt className="mono">COMPLETION</dt>
                  <dd>{Math.round(completionPct)}%</dd>
                </div>
                {current.scheduled_for && (
                  <div>
                    <dt className="mono">SCHEDULED</dt>
                    <dd>{new Date(current.scheduled_for).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</dd>
                  </div>
                )}
                <div>
                  <dt className="mono">MOVEMENT RECORDED</dt>
                  <dd className="tabular">{clock(current.active_movement_s)}</dd>
                </div>
              </dl>

              {current.interruptions > 0 && (
                <p className="fine-print fx-note">
                  {current.interruptions} interruption{current.interruptions > 1 ? "s" : ""} ·{" "}
                  {clock(current.paused_s)} paused, which does not count towards the target.
                </p>
              )}

              <div className="fx-actions">
                {current.status === "READY" && (
                  <button type="button" className="button" disabled={busy}
                          onClick={() => onStart(current.id)}>
                    <Play size={15} /> Start session
                  </button>
                )}
                {current.status === "ACTIVE" && (
                  <>
                    <button type="button" className="button button-outline" disabled={busy}
                            onClick={() => onPause(current.id)}>
                      <Pause size={15} /> Pause
                    </button>
                    <button type="button" className="button" disabled={busy}
                            onClick={() => onComplete(current.id)}>
                      <Square size={15} /> End session
                    </button>
                  </>
                )}
                {current.status === "PAUSED" && (
                  <>
                    <button type="button" className="button" disabled={busy}
                            onClick={() => onResume(current.id)}>
                      <Play size={15} /> Resume
                    </button>
                    <button type="button" className="button button-outline" disabled={busy}
                            onClick={() => onComplete(current.id)}>
                      <Square size={15} /> End session
                    </button>
                  </>
                )}
                {(current.status === "READY" || current.status === "PAUSED") && (
                  <button type="button" className="fx-cancel" disabled={busy}
                          onClick={() => onCancel(current.id)}>
                    Cancel
                  </button>
                )}
              </div>

              {current.status === "INTERRUPTED" && (
                <p className="fine-print fx-warn" role="note">
                  <TriangleAlert size={13} aria-hidden="true" />
                  This block was left open and closed automatically. It is recorded as
                  interrupted rather than completed.
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ---- other blocks today (§26) ---- */}
      {planned.length > 1 && (
        <div className="fx-others">
          <span className="eyebrow">OTHER BLOCKS TODAY</span>
          <ul>
            {planned.filter((b) => b.id !== current?.id).map((b) => (
              <li key={b.id}>
                <span className="mono">
                  {b.started_at
                    ? new Date(b.started_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
                    : "not started"}
                </span>
                <strong>{exerciseLabels[b.exercise_type as ExerciseType] ?? b.exercise_type}</strong>
                <span>{clock(b.engaged_s)} / {humanDuration(b.target_duration_s)}</span>
                <em className={`fx-chip st-${b.status.toLowerCase()}`}>{STATUS_COPY[b.status]}</em>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export { clockTime };
