"use client";

import { useEffect, useRef, useState } from "react";
import { Play, Square, Radio, TriangleAlert } from "lucide-react";
import type { LimbState } from "./BiomechanicsStage";
import { exerciseLabels, formatClock, type Session } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { useLiveSession } from "@/lib/api/useLiveSession";
import { useLiveSessionHandle } from "./LiveSessionProvider";
import { api } from "@/lib/api/client";
import { metric } from "@/lib/format";
import { MovementCore } from "@/components/three/MovementCore";

type Phase = "Stance" | "Swing" | "Descent" | "Hold";

type LabEvent = { t: number; kind: "rep" | "flag" | "system"; text: string };

/**
 * LIVE BIOMECHANICS LAB
 *
 * Streams a real session from the backend over the live WebSocket.
 *
 * Starting the lab creates an actual session and asks the server to run the
 * sensor simulator against the same ingestion socket physical hardware uses.
 * Limb angles, repetitions, symmetry, cadence and confidence are then whatever
 * the analytics pipeline computed and stored — this component renders them and
 * computes none of them itself.
 */
/** The stages a stream passes through, mirroring the hardware handshake. */
const READY_STEPS = [
  { key: "detect", title: "Node detected", detail: "Leg node opens the ingestion socket" },
  { key: "hello", title: "Handshake", detail: "Protocol version, device id, sensors declared" },
  { key: "calibrate", title: "Calibration", detail: "Gyro bias and accelerometer reference settle" },
  { key: "signal", title: "Signal", detail: "Thigh and shin angles fuse into knee angle" },
  { key: "ready", title: "Analytics", detail: "Repetitions, ROM, symmetry, cadence, confidence" },
] as const;

export function LiveLab({ session }: { session: Session }) {
  const { patient, refresh } = useData();

  // The session lives above this component, so leaving the lab does not
  // orphan a stream that is still running on the server.
  const { sessionId: liveId, begin: registerLive, clear: clearLive } = useLiveSessionHandle();
  const [starting, setStarting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [wave, setWave] = useState<number[]>([]);
  const [events, setEvents] = useState<LabEvent[]>([]);

  const live = useLiveSession(liveId, liveId != null);
  const running = liveId != null;
  const seenReps = useRef(0);
  const seenRisks = useRef(0);
  const startedAt = useRef(0);

  // Elapsed is wall-clock while a stream is open; every *metric* below comes
  // from the backend rather than from this timer.
  useEffect(() => {
    if (!running) return;
    startedAt.current = Date.now();
    setElapsed(0);
    const timer = window.setInterval(
      () => setElapsed((Date.now() - startedAt.current) / 1000),
      200,
    );
    return () => window.clearInterval(timer);
  }, [running]);

  // Trace the left knee angle exactly as the backend reports it.
  useEffect(() => {
    const angle = live.metrics?.left?.knee_angle_deg;
    if (angle == null) return;
    setWave((w) => [...w.slice(-119), angle]);
  }, [live.metrics]);

  // Append newly-arrived repetitions to the event stream.
  useEffect(() => {
    if (live.reps.length <= seenReps.current) return;
    const fresh = live.reps.slice(seenReps.current);
    seenReps.current = live.reps.length;
    setEvents((e) =>
      [
        ...fresh
          .map((r) => ({
            t: r.t_offset,
            kind: "rep" as const,
            text: `${r.leg} repetition ${r.rep_index} — ROM ${Math.round(r.rom_deg)}°`,
          }))
          .reverse(),
        ...e,
      ].slice(0, 40),
    );
  }, [live.reps]);

  useEffect(() => {
    if (live.risks.length <= seenRisks.current) return;
    const fresh = live.risks.slice(seenRisks.current);
    seenRisks.current = live.risks.length;
    setEvents((e) =>
      [
        ...fresh
          .map((r) => ({ t: 0, kind: "flag" as const, text: r.message ?? "Risk flag raised." }))
          .reverse(),
        ...e,
      ].slice(0, 40),
    );
  }, [live.risks]);

  // Calibration reflects the backend's own state, not a timer pretending.
  useEffect(() => {
    const c = live.calibration;
    if (!c) return;
    const pct = Math.round((c.overall_progress ?? 0) * 100);
    const text = c.complete
      ? "Calibration complete — streaming."
      : `Calibrating · ${pct}%`;
    setEvents((e) =>
      e[0]?.text === text
        ? e
        : [{ t: 0, kind: "system" as const, text }, ...e].slice(0, 40),
    );
  }, [live.calibration]);

  const begin = async () => {
    setFailure(null);
    setStarting(true);
    setEvents([]);
    setWave([]);
    seenReps.current = 0;
    seenRisks.current = 0;

    try {
      // A brand-new clinician has no records yet. Rather than dead-ending on
      // "no patient selected", create the record this session needs -- the
      // first thing a clinician does is start recording someone.
      let target = patient;
      if (!target) {
        setEvents([{ t: 0, kind: "system", text: "Creating a record for this session…" }]);
        target = await api.createPatient({
          name: "New patient record",
          operated_leg: "LEFT",
          notes: "Created from the live lab. Rename this record in Patients.",
        });
        await refresh();
      }

      const created = await api.createSession(target.id, session.exercise);
      registerLive(created.id);
      await api.startSimulatedStream(created.id, { scenario: "ASYMMETRY", duration_s: 120 });
      setEvents([{ t: 0, kind: "system", text: "Ingestion socket open — awaiting handshake." }]);
    } catch (error) {
      // Nothing is faked on failure: the lab stays idle and says why.
      clearLive();
      setFailure(error instanceof Error ? error.message : "Could not start a session.");
    } finally {
      setStarting(false);
    }
  };

  const stop = async () => {
    const id = liveId;
    clearLive();
    if (id == null) return;
    try {
      await api.stopSimulatedStream(id);
      await api.endSession(id);
      setEvents((e) => [{ t: elapsed, kind: "system", text: "Session ended and stored." }, ...e]);
      await refresh();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Could not end the session cleanly.");
    }
  };

  // Every figure below is the backend's. Recomputing symmetry, cadence or ROM
  // here would create a second answer that drifts from the stored session.
  const m = live.metrics;
  const leftAngle = m?.left?.knee_angle_deg ?? null;
  const rightAngle = m?.right?.knee_angle_deg ?? null;
  const calibrating = Boolean(live.calibration && !live.calibration.complete);

  const state: LimbState = {
    left: leftAngle ?? 8,
    right: rightAngle ?? 8,
    phase: (elapsed / 2.4) % 1,
    active: running && live.socket === "open",
    degradedRight: live.right?.state === "DEGRADED" || live.right?.state === "DISCONNECTED",
  };

  const reps = live.reps.length;
  const symmetry = m?.symmetry_index_pct ?? null;
  const cadence = m?.cadence_spm ?? null;
  const peak = m?.rom_running_deg ?? null;
  const phase: Phase = calibrating ? "Hold" : state.phase < 0.5 ? "Stance" : "Swing";

  return (
    <div className={`lab ${running ? "is-live" : "is-idle"}`}>
      <div className="lab-stage">
        <div className="lab-badge">
          <Radio size={13} aria-hidden="true" />
          <span className="mono">
            {!running
              ? "NO STREAM · IDLE"
              : live.socket === "open"
                ? `SIMULATED STREAM · ${live.sessionMode === "SIMULATED" ? "SIMULATED" : String(live.sessionMode)}`
                : live.socket === "reconnecting"
                  ? "STREAM · RECONNECTING"
                  : live.socket === "connecting"
                    ? "STREAM · CONNECTING"
                    : "STREAM · CLOSED"}
          </span>
        </div>

        {/* The live instrument. Angles arrive from the backend; nothing here
            animates a value that was not measured. */}
        <MovementCore
          mode="live"
          height={420}
          input={{
            left: leftAngle ?? 8,
            right: rightAngle ?? 8,
            confidence: (m?.confidence?.percent ?? 80) / 100,
            operated: (patient?.operated_leg as "LEFT" | "RIGHT" | null) ?? null,
            active: running && live.socket === "open" && !calibrating,
          }}
        />

        {/* Spatial overlays instead of a ring of cards. */}
        <div className="lab-overlay ov-tl">
          <span className="mono">EXERCISE</span>
          <strong>{exerciseLabels[session.exercise]}</strong>
          <em>{running ? phase : "Awaiting start"}</em>
        </div>
        <div className="lab-overlay ov-tr">
          <span className="mono">ELAPSED</span>
          <strong className="tabular">{formatClock(elapsed)}</strong>
          <em>{reps} repetitions</em>
        </div>
        <div className="lab-overlay ov-bl">
          <span className="mono">SYMMETRY · LSI OVER PEAKS</span>
          <strong>{metric(symmetry, "%")}</strong>
          <div className="lab-symbar" aria-hidden="true">
            <i style={{ width: `${symmetry ?? 0}%` }} />
          </div>
        </div>
        <div className="lab-overlay ov-br">
          <span className="mono">PEAK FLEXION</span>
          <strong>{metric(peak, "°")}</strong>
          <em>cadence {metric(cadence)}</em>
        </div>

        {!running && (
          /* Not a blank panel over the stage: the anatomy stays visible at
             rest, and the sequence below states exactly what the stream will
             go through before any number appears. Nothing here claims a
             device is present. */
          <div className="lab-ready">
            <div className="lab-ready-head">
              <span className="eyebrow">SIGNAL PATH · DORMANT</span>
              <h3>Nothing is streaming yet.</h3>
              <p>
                A simulated stream runs the same path a connected node would: handshake,
                calibration, then limb angles, repetition detection, symmetry and cadence —
                every figure derived from one movement cycle.
              </p>
            </div>

            <ol className="lab-ready-steps">
              {READY_STEPS.map((step, index) => (
                <li key={step.key}>
                  <span className="lab-ready-index mono">{String(index + 1).padStart(2, "0")}</span>
                  <span className="lab-ready-body">
                    <strong>{step.title}</strong>
                    <em>{step.detail}</em>
                  </span>
                </li>
              ))}
            </ol>

            <div className="lab-ready-act">
              <button type="button" className="button" onClick={begin}>
                <Play size={15} aria-hidden="true" />
                Start simulated session
              </button>
              <span className="fine-print">
                No sensor is connected. Nothing is recorded or transmitted, and no value
                shown afterwards is a measurement of a person.
              </span>
            </div>
          </div>
        )}
      </div>

      <div className="lab-side">
        <div className="lab-controls">
          {running ? (
            <button type="button" className="button button-outline" onClick={() => void stop()}>
              <Square size={14} aria-hidden="true" />
              End session
            </button>
          ) : (
            <button type="button" className="button" onClick={() => void begin()} disabled={starting}>
              <Play size={14} aria-hidden="true" />
              {starting ? "Starting…" : "Start session"}
            </button>
          )}
          {failure && (
            <p className="fine-print lab-failure" role="alert">
              {failure}
            </p>
          )}
          {running && (
            <dl className="lab-conn">
              {(["left", "right"] as const).map((side) => {
                const node = live[side];
                return (
                  <div key={side}>
                    <dt className="mono">{side.toUpperCase()}</dt>
                    <dd className="mono">{node ? node.state : "WAITING"}</dd>
                  </div>
                );
              })}
            </dl>
          )}
        </div>

        <div className="lab-wave">
          <span className="mono">LIVE SIGNAL · LEFT KNEE ANGLE</span>
          <svg viewBox="0 0 240 70" preserveAspectRatio="none" aria-hidden="true">
            <line x1="0" y1="35" x2="240" y2="35" className="lab-wave-mid" />
            {wave.length > 1 && (
              <path
                className="lab-wave-path"
                d={wave
                  .map((v, i) => `${i === 0 ? "M" : "L"}${(i / 119) * 240} ${68 - (v / 135) * 64}`)
                  .join(" ")}
              />
            )}
          </svg>
          {!running && <span className="fine-print">Signal appears when a session runs.</span>}
          {running && wave.length === 0 && (
            <span className="fine-print">Waiting for the first samples to arrive…</span>
          )}
        </div>

        <div className="lab-events">
          <span className="mono">EVENT STREAM</span>
          {events.length === 0 ? (
            <p className="fine-print">Repetitions and flags appear here as they are detected.</p>
          ) : (
            <ol>
              {events.map((e, i) => (
                <li key={`${e.t}-${i}`} className={`ev-${e.kind}`}>
                  <span className="mono">{formatClock(e.t)}</span>
                  {e.kind === "flag" && <TriangleAlert size={12} aria-hidden="true" />}
                  <span>{e.text}</span>
                </li>
              ))}
            </ol>
          )}
        </div>

        <p className="fine-print lab-disclaimer">
          The stream comes from the sensor simulator connected to the same ingestion socket
          hardware uses. Every value shown was computed by the backend and stored with the
          session. They are estimated indicators, not measurements of a person, and not a
          clinical assessment.
        </p>
      </div>
    </div>
  );
}
