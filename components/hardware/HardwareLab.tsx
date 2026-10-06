"use client";

import { useEffect, useMemo, useState } from "react";
import { Cpu, Play, Radio, Square, TriangleAlert } from "lucide-react";
import { api, WS_BASE } from "@/lib/api/client";
import { useData } from "@/lib/api/DataProvider";
import { useAuth } from "@/components/auth/AuthProvider";
import {
  HW_SCENARIOS,
  hardwareApi,
  useHardwareLive,
  type Activity,
  type Bilateral,
  type FrameRow,
  type HwCalibration,
  type HwConnection,
  type HwLiveState,
  type MlStatusBlock,
  type Mqi,
  type SessionAnalysis,
  type SessionLabel,
  type ValidationReport,
} from "@/lib/api/hardware";

/**
 * HARDWARE LAB — one ESP32, a LEFT and a RIGHT MPU6050, N force channels.
 *
 * Renders what the backend reports over `hw_*` live events and the analysis
 * endpoint. It computes no metric. Its one job beyond layout is refusing to
 * show a number when the backend says the number should not be trusted:
 * waiting for data, an IMU missing, calibration incomplete, low confidence,
 * or no model loaded each get their own explicit state.
 */

const EXERCISES: { key: string; label: string }[] = [
  { key: "SQUAT", label: "Squat" },
  { key: "WALK", label: "Walking" },
  { key: "SIT_TO_STAND", label: "Sit to stand" },
  { key: "STEP_UP", label: "Step up" },
  { key: "KNEE_EXTENSION", label: "Knee extension" },
  { key: "SINGLE_LEG_BALANCE", label: "Single-leg balance" },
];

const SESSION_KEY = "rehabsense-hw-session";

function pct(v: number | null | undefined, digits = 0) {
  return v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
}

function fmt(v: number | null | undefined, digits = 1, unit = "") {
  return v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(digits)}${unit}`;
}

/* ------------------------------------------------------------------ */

export function HardwareLab() {
  const { patient, refresh } = useData();
  const { user } = useAuth();
  const isClinician = user?.role === "PHYSIOTHERAPIST" || user?.role === "ADMIN";

  const [exercise, setExercise] = useState("SQUAT");
  const [scenario, setScenario] = useState<string>("ASYMMETRIC");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<SessionAnalysis | null>(null);
  const [ended, setEnded] = useState(false);
  const [research, setResearch] = useState(false);
  const [subjectCode, setSubjectCode] = useState("");
  const [task, setTask] = useState("");

  // Reattach to an in-progress hardware session after navigation or reload.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      const id = raw ? Number(raw) : NaN;
      if (Number.isFinite(id)) {
        hardwareApi
          .analysis(id)
          .then((a) => {
            if (a.status === "ACTIVE") setSessionId(id);
            else localStorage.removeItem(SESSION_KEY);
          })
          .catch(() => localStorage.removeItem(SESSION_KEY));
      }
    } catch {
      /* storage unavailable: nothing to restore */
    }
  }, []);

  const live = useHardwareLive(ended ? null : sessionId);

  const create = async (simulate: boolean) => {
    setFailure(null);
    setBusy(true);
    setAnalysis(null);
    setEnded(false);
    try {
      let target = patient;
      if (!target) {
        target = await api.createPatient({
          name: "New patient record",
          operated_leg: "LEFT",
          notes: "Created from the hardware lab. Rename this record in Patients.",
        });
        await refresh();
      }
      let id: number;
      if (research) {
        // Research recording: raw data is the product; needs consent.
        id = (await hardwareApi.startResearch({
          patient_id: target.id, exercise_type: exercise, subject_code: subjectCode.trim(),
          task: task.trim() || undefined,
        })).session_id;
      } else {
        id = (await api.createSession(target.id, exercise)).id;
      }
      const s = { id };
      setSessionId(s.id);
      try {
        localStorage.setItem(SESSION_KEY, String(s.id));
      } catch {
        /* ignore */
      }
      if (simulate) await hardwareApi.simulate(s.id, scenario, 90);
    } catch (e) {
      setFailure(e instanceof Error ? e.message : "Could not start the session.");
    } finally {
      setBusy(false);
    }
  };

  const end = async () => {
    if (sessionId == null) return;
    setBusy(true);
    try {
      await hardwareApi.stopSimulator(sessionId).catch(() => undefined);
      await api.endSession(sessionId);
      setEnded(true);
      setAnalysis(await hardwareApi.analysis(sessionId));
      try {
        localStorage.removeItem(SESSION_KEY);
      } catch {
        /* ignore */
      }
      await refresh();
    } catch (e) {
      setFailure(e instanceof Error ? e.message : "Could not end the session.");
    } finally {
      setBusy(false);
    }
  };

  const running = sessionId != null && !ended;
  const provenance = live.connection?.provenance ?? null;

  return (
    <div className="hw">
      <section className="hw-bar">
        <div className={`hw-source ${provenance === "SIMULATED" || provenance === "PUBLIC_DATASET_REPLAY" ? "is-sim"
          : provenance === "PHYSICAL_REGISTERED" ? "is-live" : provenance ? "is-unverified" : ""}`}>
          <Radio size={13} aria-hidden="true" />
          <span className="mono">
            {!running
              ? "NO SESSION"
              : provenance === null
                ? `SESSION ${sessionId} · WAITING FOR DEVICE`
                : provenance === "SIMULATED"
                  ? `SIMULATED · ${live.connection?.scenario ?? "simulator"} · NOT A PERSON · NOT PHYSICAL EVIDENCE`
                  : provenance === "PUBLIC_DATASET_REPLAY"
                    ? "PUBLIC DATASET REPLAY · NOT PHYSICAL EVIDENCE"
                    : provenance === "PHYSICAL_REGISTERED"
                      ? `PHYSICAL_REGISTERED · DEVICE ${live.connection?.device_id} AUTHENTICATED`
                      : `PHYSICAL_UNVERIFIED · ${live.connection?.device_id} · NOT REGISTERED · NOT EVIDENCE`}
          </span>
        </div>

        {!running ? (
          <div className="hw-controls">
            <label>
              <span className="mono">EXERCISE</span>
              <select value={exercise} onChange={(e) => setExercise(e.target.value)}>
                {EXERCISES.map((x) => (
                  <option key={x.key} value={x.key}>{x.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="mono">SIMULATOR SCENARIO</span>
              <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
                {HW_SCENARIOS.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label className="hw-check">
              <input type="checkbox" checked={research} onChange={(e) => setResearch(e.target.checked)} />
              <span className="mono">RESEARCH RECORDING</span>
            </label>
            {research && (
              <>
                <label>
                  <span className="mono">SUBJECT CODE (NOT A NAME)</span>
                  <input value={subjectCode} onChange={(e) => setSubjectCode(e.target.value)}
                         placeholder="P01" maxLength={32} />
                </label>
                <label>
                  <span className="mono">TASK</span>
                  <input value={task} onChange={(e) => setTask(e.target.value)} placeholder="squat x10" />
                </label>
              </>
            )}
            <button type="button" className="button" disabled={busy || !isClinician || (research && subjectCode.trim().length < 2)}
                    onClick={() => void create(true)}>
              <Play size={14} aria-hidden="true" /> Start simulated device
            </button>
            <button type="button" className="button button-outline"
                    disabled={busy || !isClinician || (research && subjectCode.trim().length < 2)}
                    onClick={() => void create(false)}>
              <Cpu size={14} aria-hidden="true" /> Wait for real ESP32
            </button>
          </div>
        ) : (
          <div className="hw-controls">
            <button type="button" className="button button-outline" disabled={busy}
                    onClick={() => void end()}>
              <Square size={14} aria-hidden="true" /> End session
            </button>
            <button type="button" className="button button-outline" disabled={busy || !isClinician}
                    onClick={() => void hardwareApi.recalibrate(sessionId!).catch((e) =>
                      setFailure(e instanceof Error ? e.message : "Could not recalibrate."))}>
              Recalibrate
            </button>
            {["exercise_start", "exercise_stop", "repetition_start", "repetition_end", "artifact",
              "sensor_reposition"].map((kind) => (
              <button key={kind} type="button" className="button button-small button-outline"
                      disabled={!isClinician} title="USER marker, mapped onto device time with uncertainty"
                      onClick={() => void hardwareApi.marker(sessionId!, kind).catch(() => undefined)}>
                Mark {kind.replace("_", " ")}
              </button>
            ))}
          </div>
        )}
        {!isClinician && (
          <p className="fine-print">Starting a recording needs a clinician account.</p>
        )}
        {failure && <p className="fine-print hw-fail" role="alert">{failure}</p>}
      </section>

      {running && live.connection == null && (
        <DeviceInstructions sessionId={sessionId!} />
      )}

      {running && <AlertsBar live={live} />}

      {running && (
        <>
          <div className="hw-grid">
            <DevicePanel conn={live.connection} socket={live.socket} />
            <CalibrationPanel cal={live.calibration} />
          </div>
          <SignalsPanel live={live} />
          <AiPanel live={live} />
          <div className="hw-grid">
            <RepsPanel live={live} />
            <HealthPanel live={live} />
          </div>
          <ValidationPanel sessionId={sessionId!} poll />
        </>
      )}

      {ended && sessionId != null && <ValidationPanel sessionId={sessionId} poll={false} />}

      {ended && analysis && (
        <SessionSummary analysis={analysis} isClinician={isClinician}
                        patientId={patient?.id ?? null} />
      )}

      <ValidationNote />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function DeviceInstructions({ sessionId }: { sessionId: number }) {
  const url = `${WS_BASE}/ws/ingest/v2/${sessionId}`;
  return (
    <section className="hw-panel">
      <span className="eyebrow">WAITING FOR A DEVICE</span>
      <p>
        Session <strong>{sessionId}</strong> is open. Set <code>SESSION_ID {sessionId}</code> in the
        firmware&apos;s <code>config.h</code> (or start the simulator) and the device will stream to:
      </p>
      <p className="mono hw-url">{url}</p>
      <p className="fine-print">
        Use the computer&apos;s LAN address rather than localhost when flashing an ESP32. Nothing
        below appears until a device completes the protocol v2 handshake.
      </p>
    </section>
  );
}

function stateTone(s: string | undefined) {
  if (s === "CONNECTED") return "ok";
  if (s === "WAITING") return "wait";
  if (s === "NOT_DECLARED") return "off";
  return "bad";
}

function DevicePanel({ conn, socket }: { conn: HwConnection | null; socket: string }) {
  if (!conn) {
    return (
      <section className="hw-panel">
        <span className="eyebrow">DEVICE</span>
        <p className="hw-empty">No device has connected to this session yet.</p>
        <p className="fine-print">Dashboard feed: {socket}</p>
      </section>
    );
  }
  const status = conn.device_status ?? {};
  return (
    <section className="hw-panel">
      <span className="eyebrow">DEVICE · PROTOCOL v{conn.protocol_version}</span>
      <dl className="hw-kv">
        <div><dt>ESP32</dt><dd className={`hw-state ${conn.device_connected ? "ok" : "bad"}`}>
          {conn.device_connected ? "Connected" : "Disconnected"}</dd></div>
        {(["LEFT", "RIGHT"] as const).map((side) => (
          <div key={side}>
            <dt>{side === "LEFT" ? "Left" : "Right"} IMU</dt>
            <dd className={`hw-state ${stateTone(conn.imus[side]?.state)}`}>
              {conn.imus[side]?.state === "CONNECTED" ? "Connected"
                : conn.imus[side]?.state === "NOT_DECLARED" ? "Not fitted"
                : conn.imus[side]?.state === "FROZEN" ? "Frozen readings"
                : conn.imus[side]?.state === "WAITING" ? "Waiting"
                : `${side === "LEFT" ? "Left" : "Right"} IMU disconnected`}
              {conn.imus[side]?.placement ? ` · ${conn.imus[side].placement}` : ""}
            </dd>
          </div>
        ))}
        <div><dt>Force sensors</dt><dd>
          {conn.force_channels.length === 0 ? "None declared"
            : conn.force_channels.map((f) => `${f.id} (${f.side ?? "—"}, ${f.unit})`).join(", ")}
        </dd></div>
        <div><dt>Sampling rate</dt><dd>
          {fmt(conn.measured_rate_hz, 1, " Hz")} measured · {conn.declared_rate_hz} Hz declared
        </dd></div>
        <div><dt>Firmware</dt><dd className="mono">{conn.firmware_version}</dd></div>
        <div><dt>Battery</dt><dd>
          {status.battery_pct != null ? `${status.battery_pct.toFixed(0)}%`
            : status.battery_v != null ? `${status.battery_v.toFixed(2)} V` : "Not reported"}
        </dd></div>
        {status.wifi_rssi_dbm != null && (
          <div><dt>Wi-Fi</dt><dd>{status.wifi_rssi_dbm} dBm</dd></div>
        )}
      </dl>
    </section>
  );
}

function AlertsBar({ live }: { live: HwLiveState }) {
  const alerts = live.ml?.alerts ?? live.connection?.alerts ?? [];
  if (alerts.length === 0) return null;
  return (
    <section className="hw-panel hw-alerts" role="alert">
      {alerts.map((a, i) => (
        <p key={i} className="hw-state bad">
          <TriangleAlert size={13} aria-hidden="true" /> <span className="mono">{a.code}</span>
          {a.channel ? ` ${a.channel}` : ""} · {a.reason.replace(/_/g, " ").toLowerCase()}
        </p>
      ))}
      <p className="fine-print">
        Unavailable sensors are reported, never filled in: no value from one side is ever used
        for the other.
      </p>
    </section>
  );
}

const CAL_STEPS = [
  "Device connected", "Sensor health check", "Neutral position", "Collect samples",
  "Estimate per-sensor offsets", "Validate quality", "Store calibration",
];

/** The five calibration states the UI must distinguish. */
function calState(cal: HwCalibration | null): { text: string; tone: string } {
  if (!cal || cal.phase === "PENDING") return { text: "Calibration required", tone: "wait" };
  if (!cal.complete) return { text: "Calibrating", tone: "wait" };
  if (cal.phase === "FAILED" || cal.status === "FAIL") return { text: "Calibration failed", tone: "bad" };
  if (cal.stale_reason) return { text: "Calibration stale", tone: "wait" };
  return { text: "Calibration passed", tone: "ok" };
}

function CalibrationPanel({ cal }: { cal: HwCalibration | null }) {
  return (
    <section className="hw-panel">
      <span className="eyebrow">CALIBRATION{cal ? ` #${cal.sequence}` : ""}</span>
      <p className={`hw-state ${calState(cal).tone}`} role="status">{calState(cal).text}</p>
      {!cal ? (
        <p className="hw-empty">Calibration required — starts when the device streams.</p>
      ) : (
        <>
          <ol className="hw-steps">
            {CAL_STEPS.map((label, i) => (
              <li key={label} className={i + 1 < cal.step || cal.complete ? "done" : i + 1 === cal.step ? "now" : ""}>
                {label}
              </li>
            ))}
          </ol>
          {cal.stale_reason && <p className="hw-state wait">Stale: {cal.stale_reason}</p>}
          {!cal.complete ? (
            <>
              <p className="hw-instruction">{cal.instruction}</p>
              <div className="hw-progress" aria-label="Calibration progress">
                <i style={{ width: `${Math.round(cal.progress * 100)}%` }} />
              </div>
              {Object.keys(cal.health ?? {}).length > 0 && (
                <dl className="hw-kv">
                  {Object.entries(cal.health).map(([side, h]) => (
                    <div key={side}>
                      <dt>{side} health</dt>
                      <dd className={`hw-state ${h.ok ? "ok" : "bad"}`}>
                        {h.ok ? `ok · |g| ${h.gravity_norm_g} g` : `${side}_IMU_UNAVAILABLE · ${h.reason}`}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              {cal.health_attempts > 1 && cal.phase === "HEALTH_CHECK" && (
                <p className="hw-state bad">No usable IMU yet — health check attempt {cal.health_attempts}.</p>
              )}
            </>
          ) : (
            <>
              <p className={`hw-state ${cal.status === "PASS" ? "ok" : cal.status === "WARN" ? "wait" : "bad"}`}>
                {cal.phase === "FAILED" ? `Calibration failed${cal.failure_reason ? `: ${cal.failure_reason}` : ""}` : `Calibration ${cal.status}`}
                {cal.quality != null && ` · quality ${pct(cal.quality)}`}
              </p>
              <ol className="hw-checks">
                {cal.checks?.map((c) => (
                  <li key={c.key} className={`chk-${c.status.toLowerCase()}`}>
                    <span className="mono">{c.status}</span>
                    <strong>{c.key.replace(/_/g, " ")}</strong>
                    <em>{c.message}</em>
                  </li>
                ))}
              </ol>
            </>
          )}
        </>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */

function Trace({ rows, columns, keys, labels, unit, title }: {
  rows: FrameRow[]; columns: string[]; keys: string[]; labels: string[]; unit: string; title: string;
}) {
  const idx = keys.map((k) => columns.indexOf(k));
  const t = rows.map((r) => r[0] as number);
  const vals = idx.flatMap((i) => (i < 0 ? [] : rows.map((r) => r[i]).filter((v): v is number => v != null)));
  const missing = idx.map((i) => i < 0 || rows.length === 0 || rows.slice(-10).every((r) => r[i] == null));
  if (rows.length < 2 || vals.length === 0) {
    return (
      <figure className="hw-trace">
        <figcaption className="mono">{title}</figcaption>
        <p className="hw-empty">Waiting for sufficient sensor data…</p>
      </figure>
    );
  }
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const t0 = t[0];
  const t1 = t[t.length - 1] || t0 + 1;
  const X = (v: number) => ((v - t0) / Math.max(1e-6, t1 - t0)) * 300;
  const Y = (v: number) => 78 - ((v - lo) / (hi - lo)) * 74;
  return (
    <figure className="hw-trace">
      <figcaption className="mono">
        {title} <span>{fmt(lo, 2)}–{fmt(hi, 2)} {unit}</span>
      </figcaption>
      <svg viewBox="0 0 300 80" preserveAspectRatio="none" role="img"
           aria-label={`${title}, last ${Math.round(t1 - t0)} seconds`}>
        {idx.map((col, k) => {
          if (col < 0) return null;
          let d = "";
          let pen = false;
          rows.forEach((r, j) => {
            const v = r[col];
            if (v == null) { pen = false; return; }
            d += `${pen ? "L" : "M"}${X(t[j]).toFixed(1)} ${Y(v).toFixed(1)} `;
            pen = true;
          });
          return <path key={keys[k]} d={d} className={`hw-line s${k}`} />;
        })}
      </svg>
      <div className="hw-legend">
        {labels.map((l, k) => (
          <span key={l} className={`s${k} ${missing[k] ? "is-missing" : ""}`}>
            {l}{missing[k] ? " — no data" : ""}
          </span>
        ))}
      </div>
    </figure>
  );
}

function SignalsPanel({ live }: { live: HwLiveState }) {
  const cols = live.frameColumns;
  const forceKeys = cols.filter((c) => c.startsWith("force_"));
  return (
    <section className="hw-panel">
      <span className="eyebrow">LIVE SENSORS · LAST 10 s · CALIBRATED</span>
      <div className="hw-traces">
        <Trace rows={live.frames} columns={cols} keys={["left_acc_g", "right_acc_g"]}
               labels={["Left |a|", "Right |a|"]} unit="g" title="ACCELERATION" />
        <Trace rows={live.frames} columns={cols} keys={["left_gyro_dps", "right_gyro_dps"]}
               labels={["Left |ω|", "Right |ω|"]} unit="°/s" title="ANGULAR VELOCITY" />
        <Trace rows={live.frames} columns={cols} keys={["left_tilt_deg", "right_tilt_deg"]}
               labels={["Left tilt", "Right tilt"]} unit="°" title="SEGMENT TILT FROM NEUTRAL" />
        {forceKeys.length > 0 ? (
          <Trace rows={live.frames} columns={cols} keys={forceKeys}
                 labels={forceKeys.map((k) => k.replace("force_", ""))} unit="adc_norm"
                 title="FORCE (LOAD PROXY)" />
        ) : (
          <figure className="hw-trace"><figcaption className="mono">FORCE</figcaption>
            <p className="hw-empty">No force sensor declared by this device.</p></figure>
        )}
      </div>
      <p className="fine-print">
        Tilt is one segment&apos;s rotation from its calibrated neutral pose, not a joint angle — a
        knee angle needs two IMUs on the same leg. Force is a normalised FSR reading, not newtons.
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ */

function ActivityCard({ a, calibrating }: { a: Activity | null; calibrating: boolean }) {
  let body;
  if (calibrating) body = <p className="hw-empty">Calibration required before classification.</p>;
  else if (!a) body = <p className="hw-empty">Waiting for sufficient sensor data…</p>;
  else if (a.status === "MODEL_UNAVAILABLE")
    body = <p className="hw-empty">No activity model is loaded on the server.{a.reason ? ` (${a.reason})` : ""}</p>;
  else if (a.status === "INSUFFICIENT_DATA") body = <p className="hw-empty">{a.message}</p>;
  else if (a.status === "LOW_CONFIDENCE")
    body = (
      <>
        <p className="hw-state wait">Low-confidence prediction</p>
        <p className="fine-print">
          Top candidate {a.candidate} at {pct(a.confidence)} — below the model&apos;s threshold,
          so no activity is reported.
        </p>
      </>
    );
  else
    body = (
      <>
        <strong className="hw-big">{a.activity?.replace(/_/g, " ")}</strong>
        <p>confidence {pct(a.confidence)}</p>
      </>
    );
  return (
    <div className="hw-card">
      <span className="mono">ACTIVITY</span>
      {body}
      {a?.domain && (
        <p className="fine-print">
          {a.model} · trained on {a.domain.trained_on}. {a.domain.note}
          {!a.domain.placement_match && " Sensor placement is not confirmed to match the training data."}
        </p>
      )}
    </div>
  );
}

function AsymmetryCard({ b }: { b: Bilateral | null }) {
  return (
    <div className="hw-card">
      <span className="mono">BILATERAL ASYMMETRY · RESEARCH METRIC</span>
      {!b ? <p className="hw-empty">Waiting for sufficient sensor data…</p>
        : b.status === "SINGLE_SIDE" ? <p className="hw-empty">Both IMUs are required — one side is not reporting.</p>
        : b.status === "NO_MOVEMENT" ? <p className="hw-empty">Neither side is moving.</p>
        : b.asymmetry_score == null ? <p className="hw-empty">{b.message ?? "Not enough data."}</p>
        : (
          <>
            <strong className="hw-big">{b.asymmetry_score.toFixed(2)}</strong>
            <p>0 = sides identical · confidence {pct(b.confidence)}
              {b.confidence < 0.5 && " · low confidence"}</p>
            <ul className="hw-components">
              {Object.entries(b.components).map(([k, v]) => (
                <li key={k}><span>{k.replace(/_/g, " ")}</span><span>{v == null ? "—" : v.toFixed(2)}</span></li>
              ))}
            </ul>
          </>
        )}
    </div>
  );
}

function MqiCard({ q }: { q: Mqi | null }) {
  return (
    <div className="hw-card">
      <span className="mono">MQI · RESEARCH METRIC — NOT CLINICALLY VALIDATED</span>
      {!q || q.mqi == null ? (
        <p className="hw-empty">{q?.message ?? "Appears after three repetitions."}</p>
      ) : (
        <>
          <strong className="hw-big">{q.mqi.toFixed(0)}</strong>
          <p>confidence {pct(q.confidence)}{q.status === "LOW_CONFIDENCE" && " · low confidence"}</p>
          <ul className="hw-components">
            {Object.entries(q.components).map(([k, v]) => (
              <li key={k}><span>{k.replace(/_/g, " ")}</span><span>{v.toFixed(2)}</span></li>
            ))}
            {q.unavailable.map((k) => (
              <li key={k} className="is-missing"><span>{k.replace(/_/g, " ")}</span><span>n/a</span></li>
            ))}
          </ul>
          <p className="fine-print">{q.label}. Equal weights across available components; MQIs
            from different component sets are not comparable.</p>
        </>
      )}
    </div>
  );
}

function AiPanel({ live }: { live: HwLiveState }) {
  const ml = live.ml;
  const calibrating = !live.calibration?.complete;
  const phases = ml?.phase?.by_side ?? {};
  const fm = ml?.force_motion?.channels ?? null;
  return (
    <section className="hw-panel">
      <span className="eyebrow">ANALYSIS · UPDATED EVERY WINDOW</span>
      {ml?.calibration_required && (
        <p className="hw-state bad"><TriangleAlert size={13} aria-hidden="true" /> Calibration
          failed — results below are not reliable. End the session and recalibrate.</p>
      )}
      <div className="hw-cards">
        <ActivityCard a={ml?.activity ?? null} calibrating={calibrating} />
        <AsymmetryCard b={ml?.bilateral ?? null} />
        <MqiCard q={ml?.movement_quality ?? null} />
        <div className="hw-card">
          <span className="mono">MOVEMENT PHASE · HEURISTIC</span>
          {Object.keys(phases).length === 0 ? (
            <p className="hw-empty">Phases appear once repetitions are detected.</p>
          ) : (
            <dl className="hw-kv">
              {Object.entries(phases).map(([side, p]) => (
                <div key={side}><dt>{side}</dt><dd>{p ?? "—"}</dd></div>
              ))}
            </dl>
          )}
        </div>
        <div className="hw-card">
          <span className="mono">FORCE / MOTION</span>
          {!fm ? <p className="hw-empty">No force channels, or not enough data yet.</p> : (
            <dl className="hw-kv">
              {Object.entries(fm).map(([id, c]) => (
                <div key={id}>
                  <dt>{id}</dt>
                  <dd>
                    {c.status !== "OK" ? c.status.toLowerCase().replace(/_/g, " ")
                      : `peak ${fmt(c.peak, 2)} · r ${fmt(c.motion_correlation, 2)} · lag ${fmt(c.lag_s, 2, " s")}`}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
      <p className="fine-print">
        Activity, asymmetry, phase and force/motion describe the latest window. The MQI covers
        every repetition so far, because a quality index over one or two repetitions would
        not be meaningful.
      </p>
    </section>
  );
}

function RepsPanel({ live }: { live: HwLiveState }) {
  return (
    <section className="hw-panel">
      <span className="eyebrow">REPETITIONS · {live.reps.length}</span>
      {live.reps.length === 0 ? <p className="hw-empty">None detected yet.</p> : (
        <table className="hw-table">
          <thead><tr><th>Side</th><th>#</th><th>ROM proxy</th><th>Peak ω</th><th>Duration</th><th>Force peak</th></tr></thead>
          <tbody>
            {live.reps.slice(0, 12).map((r) => (
              <tr key={`${r.side}-${r.rep_index}`}>
                <td>{r.side}</td><td>{r.rep_index}</td><td>{fmt(r.rom_proxy_deg, 0, "°")}</td>
                <td>{fmt(r.peak_velocity_dps, 0, "°/s")}</td><td>{fmt(r.duration_s, 2, " s")}</td>
                <td>{fmt(r.force_peak, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function HealthPanel({ live }: { live: HwLiveState }) {
  const h = live.health;
  const d = live.deliveryMs;
  const sorted = [...d].sort((a, b) => a - b);
  const p50 = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
  return (
    <section className="hw-panel">
      <span className="eyebrow">SAMPLING & STREAM HEALTH — MEASURED, UNROUNDED</span>
      {!h ? <p className="hw-empty">Waiting for sufficient sensor data…</p> : (
        <dl className="hw-kv">
          <div><dt>Requested rate</dt><dd>{h.declared_rate_hz} Hz</dd></div>
          <div><dt>Observed rate (median interval)</dt><dd>{fmt(h.measured_rate_hz, 3, " Hz")}</dd></div>
          <div><dt>Effective rate (incl. losses)</dt><dd>{fmt(h.effective_rate_hz, 3, " Hz")}</dd></div>
          <div><dt>Left IMU availability</dt><dd>{pct(h.left_available_ratio, 2)}</dd></div>
          <div><dt>Right IMU availability</dt><dd>{pct(h.right_available_ratio, 2)}</dd></div>
          {(h.force_available_ratio ?? []).map((r, i) => (
            <div key={i}><dt>Force channel {i + 1} availability</dt><dd>{pct(r, 2)}</dd></div>
          ))}
          <div><dt>Saturated / impossible</dt><dd>
            L {h.saturated_samples?.LEFT ?? 0}/{h.out_of_range_samples?.LEFT ?? 0} ·
            R {h.saturated_samples?.RIGHT ?? 0}/{h.out_of_range_samples?.RIGHT ?? 0}</dd></div>
          <div><dt>Sample loss</dt><dd>{pct(h.loss_ratio, 2)} · {h.missing_samples} samples in {h.gaps} gaps</dd></div>
          <div><dt>Duplicates / out of order</dt><dd>{h.duplicates} / {h.out_of_order}</dd></div>
          <div><dt>Rate check</dt><dd className={h.rate_ok === false ? "hw-state bad" : ""}>
            {h.rate_ok === false ? "differs from requested by > 5%" : h.rate_ok ? "within 5%" : "—"}</dd></div>
          <div><dt>Jitter</dt><dd>{fmt(h.jitter_ms, 2, " ms")}</dd></div>
          <div><dt>Clock drift</dt><dd>{h.clock_drift_ppm == null ? "needs ≥ 30 s" : `${h.clock_drift_ppm} ppm`}</dd></div>
          <div><dt>Sensor → server (relative)</dt><dd>p50 {fmt(h.relative_latency_ms.p50, 0, " ms")} · p95 {fmt(h.relative_latency_ms.p95, 0, " ms")}</dd></div>
          {Object.entries(h.latency).map(([k, v]) => (
            <div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>p50 {v.p50_ms} ms · p95 {v.p95_ms} ms</dd></div>
          ))}
          <div><dt>Server → browser</dt><dd>{p50 == null ? "—" : `~${Math.round(p50)} ms`}</dd></div>
        </dl>
      )}
      <p className="fine-print">
        Measured, not estimated. Sensor→server is relative to the fastest packet seen (absolute
        latency needs synchronised clocks); server→browser assumes this computer&apos;s clock
        matches the server&apos;s.
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ */

function SessionSummary({ analysis, isClinician, patientId }: {
  analysis: SessionAnalysis; isClinician: boolean; patientId: number | null;
}) {
  const s = analysis.summary;
  const [labels, setLabels] = useState<SessionLabel[]>([]);
  const [draft, setDraft] = useState({ t_start: "", t_end: "", side: "", movement_phase: "",
                                        repetition_index: "", quality_rating: "" });
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!isClinician) return;
    hardwareApi.labels(analysis.session_id).then((r) => setLabels(r.items)).catch(() => undefined);
  }, [analysis.session_id, isClinician]);

  const addLabel = async () => {
    setNote(null);
    try {
      const created = await hardwareApi.addLabel(analysis.session_id, {
        t_start: Number(draft.t_start), t_end: Number(draft.t_end),
        side: draft.side || null, movement_phase: draft.movement_phase || null,
        repetition_index: draft.repetition_index ? Number(draft.repetition_index) : null,
        quality_rating: draft.quality_rating ? Number(draft.quality_rating) : null,
        exercise_type: analysis.exercise_type,
      });
      setLabels((l) => [...l, created]);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Could not save the label.");
    }
  };

  const setBaseline = async () => {
    if (patientId == null) return;
    setNote(null);
    try {
      await hardwareApi.setBaseline(patientId, [analysis.session_id]);
      setNote("Saved as this patient's personal baseline for this exercise.");
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Could not set the baseline.");
    }
  };

  if (!s) {
    return (
      <section className="hw-panel">
        <span className="eyebrow">SESSION {analysis.session_id}</span>
        <p className="hw-empty">This session holds no hardware (protocol v2) data.</p>
      </section>
    );
  }
  const totalActivity = Object.values(s.activity.seconds_by_activity).reduce((a, b) => a + b, 0);
  return (
    <section className="hw-panel hw-summary">
      <span className="eyebrow">SESSION {analysis.session_id} SUMMARY · {analysis.mode}</span>
      <div className="hw-cards">
        <div className="hw-card">
          <span className="mono">DURATION</span>
          <strong className="hw-big">{fmt(s.duration_s, 0, " s")}</strong>
          <p>{s.repetitions} {s.repetition_kind === "GAIT_CYCLE" ? "gait cycles" : "repetitions"}</p>
        </div>
        <div className="hw-card">
          <span className="mono">ACTIVITIES</span>
          {totalActivity === 0 ? (
            <p className="hw-empty">
              {s.activity.model ? "No window reached the confidence threshold." : "No model was loaded."}
            </p>
          ) : (
            <ul className="hw-components">
              {Object.entries(s.activity.seconds_by_activity).map(([k, v]) => (
                <li key={k}><span>{k.replace(/_/g, " ")}</span><span>{v.toFixed(0)} s</span></li>
              ))}
            </ul>
          )}
          <p className="fine-print">{s.activity.low_confidence_windows} of {s.activity.windows} windows low-confidence</p>
        </div>
        <AsymmetryCard b={s.bilateral} />
        <MqiCard q={s.movement_quality} />
      </div>

      {Object.keys(s.repetition_summary).length > 0 && (
        <table className="hw-table">
          <thead><tr><th>Side</th><th>Count</th><th>ROM proxy</th><th>Peak ω</th><th>Duration</th><th>SPARC</th></tr></thead>
          <tbody>
            {Object.entries(s.repetition_summary).map(([side, r]) => (
              <tr key={side}><td>{side}</td><td>{r.count}</td><td>{fmt(r.rom_proxy_deg_mean, 1, "°")}</td>
                <td>{fmt(r.peak_velocity_dps_mean, 0, "°/s")}</td><td>{fmt(r.duration_s_mean, 2, " s")}</td>
                <td>{fmt(r.sparc_median, 2)}</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {s.force_motion?.status === "OK" && (
        <div className="hw-card">
          <span className="mono">FORCE / MOTION</span>
          <ul className="hw-components">
            {Object.entries(s.force_motion.by_side).map(([side, f]) => (
              <li key={side}><span>{side}</span><span>{f.description ?? "—"} · consistency {fmt(f.force_consistency, 2)}</span></li>
            ))}
          </ul>
          <p className="fine-print">{s.force_motion.unit_note}</p>
        </div>
      )}

      <div className="hw-card">
        <span className="mono">CHANGE FROM PERSONAL BASELINE</span>
        {analysis.baseline_comparison ? (
          <ul className="hw-components">
            {Object.entries(analysis.baseline_comparison.metrics).map(([k, m]) => (
              <li key={k}>
                <span>{k.replace(/_/g, " ")}</span>
                <span>{fmt(m.baseline, 2)} → {fmt(m.current, 2)} ({m.change_pct == null ? "n/a" : `${m.change_pct > 0 ? "+" : ""}${m.change_pct}%`}, {m.direction})</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="hw-empty">No personal baseline is set for this exercise.</p>
        )}
        {isClinician && analysis.mode !== "SIMULATED" && (
          <button type="button" className="button button-small button-outline" onClick={() => void setBaseline()}>
            Use this session as the baseline
          </button>
        )}
        {analysis.mode === "SIMULATED" && (
          <p className="fine-print">Simulated sessions cannot become a patient&apos;s baseline.</p>
        )}
        <p className="fine-print">A change is a difference in a measured indicator, not a clinical judgement.</p>
      </div>

      {isClinician && (
        <div className="hw-card">
          <span className="mono">THERAPIST LABELS · TRAINING DATA</span>
          <p className="fine-print">
            Label what you observed. Labels on real recordings, with consent, become RehabSense
            training data; simulated sessions are never exported for training.
          </p>
          <div className="hw-label-form">
            <input placeholder="start s" value={draft.t_start} onChange={(e) => setDraft({ ...draft, t_start: e.target.value })} />
            <input placeholder="end s" value={draft.t_end} onChange={(e) => setDraft({ ...draft, t_end: e.target.value })} />
            <select value={draft.side} onChange={(e) => setDraft({ ...draft, side: e.target.value })}>
              <option value="">side —</option><option>LEFT</option><option>RIGHT</option>
            </select>
            <select value={draft.movement_phase} onChange={(e) => setDraft({ ...draft, movement_phase: e.target.value })}>
              <option value="">phase —</option>
              {["rest", "initiation", "movement", "peak", "return"].map((p) => <option key={p}>{p}</option>)}
            </select>
            <input placeholder="rep #" value={draft.repetition_index} onChange={(e) => setDraft({ ...draft, repetition_index: e.target.value })} />
            <select value={draft.quality_rating} onChange={(e) => setDraft({ ...draft, quality_rating: e.target.value })}>
              <option value="">quality —</option>{[1, 2, 3, 4, 5].map((q) => <option key={q}>{q}</option>)}
            </select>
            <button type="button" className="button button-small" onClick={() => void addLabel()}>Add label</button>
          </div>
          {labels.length > 0 && (
            <ul className="hw-components">
              {labels.map((l) => (
                <li key={l.id}><span>{l.t_start}–{l.t_end} s · HUMAN {l.tier}</span>
                  <span>{[l.side, l.movement_phase, l.repetition_index && `rep ${l.repetition_index}`,
                    l.quality_rating && `quality ${l.quality_rating}/5`].filter(Boolean).join(" · ")}</span></li>
              ))}
            </ul>
          )}
        </div>
      )}
      {isClinician && (
        <div className="hw-card">
          <span className="mono">RESEARCH EXPORT</span>
          <p className="fine-print">
            Raw samples (NaN where a sensor was unavailable, gaps where samples were lost),
            metadata, calibration, events, human labels and model predictions as separate files,
            with SHA-256 manifest.
          </p>
          <a className="button button-small button-outline" href={hardwareApi.exportUrl(analysis.session_id)}>
            Download export (.zip)
          </a>
        </div>
      )}
      {note && <p className="fine-print" role="status">{note}</p>}
      <p className="fine-print">{s.disclaimer}</p>
    </section>
  );
}

function ValidationPanel({ sessionId, poll }: { sessionId: number; poll: boolean }) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      hardwareApi.validation(sessionId).then((r) => alive && setReport(r)).catch(() => undefined);
    load();
    if (!poll) return () => { alive = false; };
    const timer = window.setInterval(load, 5000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [sessionId, poll]);
  return (
    <section className="hw-panel">
      <span className="eyebrow">DATA VALIDATION · HARDWARE-DATA CHECKS</span>
      {!report ? <p className="hw-empty">Waiting for sufficient sensor data…</p> : (
        <>
          <p className={`hw-state ${report.verdict === "USABLE" ? "ok" : report.verdict === "NOT_USABLE" ? "bad" : "wait"}`}>
            {report.verdict.replace(/_/g, " ")} · {report.evidence_level}
          </p>
          <ol className="hw-checks">
            {report.checks.map((c) => (
              <li key={c.key} className={`chk-${c.status.toLowerCase()}`}>
                <span className="mono">{c.status}</span>
                <strong>{c.key.replace(/_/g, " ")}</strong>
                <em>{c.message}</em>
              </li>
            ))}
          </ol>
          <p className="fine-print">{report.scope}</p>
        </>
      )}
    </section>
  );
}

const ML_STATUS_ROWS: [keyof MlStatusBlock, string][] = [
  ["MODEL_IMPLEMENTED", "Model implemented"],
  ["PUBLIC_DATASET_VALIDATED", "Public dataset validated"],
  ["REAL_REHABSENSE_HARDWARE_VALIDATED", "Real RehabSense hardware validated"],
  ["HUMAN_LABELED_PHYSICAL_DATA", "Human-labelled physical recordings"],
  ["CLINICAL_VALIDATION", "Clinical validation"],
];

function ValidationNote() {
  const [models, setModels] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [block, setBlock] = useState<MlStatusBlock | null>(null);
  useEffect(() => {
    hardwareApi
      .models()
      .then((m) => {
        setModels(m.loaded);
        setBlock(m.status_block);
      })
      .catch(() => {
        setModels(null);
        setBlock(null);
      });
  }, []);
  const rows = useMemo(() => Object.entries(models ?? {}), [models]);
  return (
    <section className="hw-panel hw-validation">
      <span className="eyebrow">ML STATUS</span>
      <dl className="hw-kv">
        {ML_STATUS_ROWS.map(([key, label]) => {
          const v = block?.[key];
          const good = v === "YES" || (typeof v === "number" && v > 0);
          return (
            <div key={key}><dt>{label}</dt>
              <dd className={`hw-state ${v === undefined ? "" : good ? "ok" : "bad"}`}>
                {v === undefined ? "unknown (backend unreachable)" : String(v)}
              </dd></div>
          );
        })}
        <div><dt>Simulator performance</dt><dd>Pipeline checks on synthetic data only (ml/reports)</dd></div>
        {rows.map(([kind, m]) => (
          <div key={kind}><dt>Model · {kind.replace("_", " ")}</dt>
            <dd className="mono">{m.loaded === false ? `not loaded` : `${m.name}/${m.version}`}</dd></div>
        ))}
      </dl>
      <p className="fine-print">
        Research prototype. Not a medical device. Nothing on this page is a diagnosis.
      </p>
    </section>
  );
}
