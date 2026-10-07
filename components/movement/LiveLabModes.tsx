"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Cpu, Pause, Play, Radio, RotateCcw, Wifi } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { movementApi, useApi, type SessionAnalysis, type SessionTrace } from "@/lib/api/movement";
import { activityLabel, dateTime, exerciseLabel, num } from "@/lib/movement-format";
import { Failure, Loading, Panel } from "./Bits";
import { useChartColors } from "./Charts";
import { ProvenanceBadge } from "./Provenance";
import { forceColumn, forceLabel } from "./SessionAnalysisView";

type Mode = "replay" | "device" | "v1";
type Summary = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** The three ways the lab can be fed, kept visibly apart. */
export function LiveLabModes({ legacy }: { legacy: React.ReactNode }) {
  const params = useSearchParams();
  const [mode, setMode] = useState<Mode>((params.get("mode") as Mode) || "replay");
  return (
    <>
      <div className="mv-tabs" role="tablist" aria-label="Live lab source">
        <button type="button" role="tab" aria-selected={mode === "replay"} onClick={() => setMode("replay")}>
          <Play size={14} aria-hidden="true" /> Synthetic live replay
        </button>
        <button type="button" role="tab" aria-selected={mode === "device"} onClick={() => setMode("device")}>
          <Cpu size={14} aria-hidden="true" /> Real ESP32
        </button>
        <button type="button" role="tab" aria-selected={mode === "v1"} onClick={() => setMode("v1")}>
          <Radio size={14} aria-hidden="true" /> Two-node simulator (v1)
        </button>
      </div>
      {mode === "replay" && <SyntheticReplay initial={Number(params.get("session")) || null} />}
      {mode === "device" && <RealDevice />}
      {mode === "v1" && legacy}
    </>
  );
}

/* ------------------------------------------------------------------ *
 * A. synthetic live replay
 * ------------------------------------------------------------------ */

function SyntheticReplay({ initial }: { initial: number | null }) {
  const list = useApi(() => movementApi.sessions(), []);
  // Synthetic demonstration sessions first (newest first), then public replays.
  const options = useMemo(() => {
    const items = list.data?.items ?? [];
    return [
      ...items.filter((s) => s.provenance === "SYNTHETIC_DEMONSTRATION"),
      ...items.filter((s) => s.provenance === "PUBLIC_DATASET_REPLAY"),
    ];
  }, [list.data]);
  const [chosen, setChosen] = useState<number | null>(initial);
  const sessionId = chosen ?? options[0]?.id ?? null;

  if (list.loading && !list.data) return <Loading what="replayable sessions" />;
  if (list.error) return <Failure error={list.error} retry={list.reload} />;
  if (!options.length) {
    return (
      <Panel eyebrow="SYNTHETIC LIVE REPLAY" title="Nothing to replay yet">
        <p className="mv-empty">No synthetic or public-replay session is visible to this account.</p>
      </Panel>
    );
  }
  return (
    <>
      <Panel
        eyebrow="SYNTHETIC LIVE REPLAY"
        title="Replay a stored session in real time"
        actions={
          <label className="mv-filters">
            <span className="mono">SESSION</span>
            <select value={sessionId ?? ""} onChange={(e) => setChosen(Number(e.target.value))}>
              {options.slice(0, 120).map((s) => (
                <option key={s.id} value={s.id}>
                  #{s.id} · {s.patient_name} · {exerciseLabel(s.exercise_type)} · {dateTime(s.started_at)}
                </option>
              ))}
            </select>
          </label>
        }
        footer="Plays back what the pipeline stored for this session — its calibrated per-side frames, model windows and assessments — on the session's own clock. It is not a device stream and not hardware data."
      >
        <p className="mv-replay-note">
          <span className="mv-live-badge">SYNTHETIC LIVE REPLAY</span>
          Not real hardware. The real-device lab says <strong>WAITING FOR REAL ESP32</strong> until an
          authenticated device connects.
        </p>
      </Panel>
      {sessionId != null && <ReplayStage key={sessionId} sessionId={sessionId} />}
    </>
  );
}

function rowAt(rows: (number | null)[][], time: number): number {
  let lo = 0;
  let hi = rows.length - 1;
  if (hi < 0) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if ((rows[mid][0] ?? 0) <= time) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

function ReplayStage({ sessionId }: { sessionId: number }) {
  const analysis = useApi(() => movementApi.analysis(sessionId), [sessionId]);
  const trace = useApi(() => movementApi.trace(sessionId), [sessionId]);
  if ((analysis.loading && !analysis.data) || (trace.loading && !trace.data)) return <Loading what="the stored stream" />;
  if (analysis.error || !analysis.data) return <Failure error={analysis.error ?? "No analysis."} retry={analysis.reload} />;
  if (trace.error || !trace.data) return <Failure error={trace.error ?? "No stored trace for this session."} retry={trace.reload} />;
  return <Stage a={analysis.data} trace={trace.data} />;
}

function Stage({ a, trace }: { a: SessionAnalysis; trace: SessionTrace }) {
  const c = useChartColors();
  const s = (a.summary ?? {}) as Summary;
  const stream = s.stream ?? null;
  const cal = s.calibration ?? null;
  const rows = trace.rows;
  const col = useMemo(() => Object.fromEntries(trace.columns.map((n, i) => [n, i])) as Record<string, number>, [trace]);
  const end = rows.length ? Number(rows[rows.length - 1][0]) : 0;
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  const last = useRef<number | null>(null);

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const step = (now: number) => {
      const prev = last.current ?? now;
      last.current = now;
      setT((x) => {
        const next = x + (now - prev) / 1000;
        if (next >= end) {
          setPlaying(false);
          return end;
        }
        return next;
      });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      last.current = null;
    };
  }, [playing, end]);

  const i = rowAt(rows, t);
  const now = i >= 0 ? rows[i] : null;
  const v = (name: string) => (now && col[name] != null ? (now[col[name]] as number | null) : null);
  const recent = useMemo(() => {
    const from = rowAt(rows, Math.max(0, t - 10));
    return rows.slice(from, i + 1).map((r) => ({ t: Number(r[0]), l: r[col.left_tilt_deg] as number | null, r: r[col.right_tilt_deg] as number | null }));
  }, [rows, t, i, col]);
  const activity = a.activity_segments.find((g) => g.t_start <= t && t <= g.t_end) ?? null;
  const assessed = [...a.assessments].reverse().find((w) => w.t_end <= t + 0.01) ?? null;
  const protocol = cal?.protocol ?? {};
  const calibrationEnds = Number(protocol.health_seconds ?? 1) + Number(protocol.still_seconds ?? 3) + Number(protocol.movement_seconds ?? 5);
  const calibrating = t < calibrationEnds && !a.activity_segments.some((g) => g.t_start <= t);
  const deviceRate = Number(stream?.declared_rate_hz ?? 100);
  const firstAnalysed = a.activity_segments[0]?.t_start ?? calibrationEnds;
  const forceLeft = forceColumn(trace.columns, "left");
  const forceRight = forceColumn(trace.columns, "right");
  const forceOf = (side: "left" | "right") => {
    const name = side === "left" ? forceLeft : forceRight;
    return name ? v(name) : null;
  };
  const replayLabel = a.provenance === "PUBLIC_DATASET_REPLAY" ? "PUBLIC DATASET REPLAY" : "SYNTHETIC LIVE REPLAY";

  return (
    <section className="mv-stage" aria-live="off">
      <header className="mv-stage-head">
        <span className="mv-live-badge"><i aria-hidden="true" /> {replayLabel}</span>
        <ProvenanceBadge value={a.provenance} compact />
        <span className="mono">SESSION #{a.session_id} · {exerciseLabel(a.exercise_type).toUpperCase()}</span>
        <div className="mv-player">
          <button type="button" className="button button-small" onClick={() => {
            if (t >= end) setT(0);
            setPlaying((p) => !p);
          }}>
            {playing ? <Pause size={13} aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
            {playing ? "Pause" : "Play"}
          </button>
          <button type="button" className="button button-outline button-small" onClick={() => { setT(0); setPlaying(true); }}>
            <RotateCcw size={13} aria-hidden="true" /> Restart
          </button>
          {t < firstAnalysed && (
            <button type="button" className="button button-outline button-small" onClick={() => setT(firstAnalysed)}>
              Skip calibration
            </button>
          )}
          <Link className="mv-link" href={`/workspace/sessions/${a.session_id}`}>Full analysis</Link>
        </div>
      </header>

      <div className="mv-stage-grid">
        <div className="mv-stage-cell">
          <span className="mono">TIMESTAMP</span>
          <strong>{t.toFixed(1)} s</strong>
          <small>of {end.toFixed(1)} s · session clock</small>
        </div>
        <div className="mv-stage-cell">
          <span className="mono">INCOMING SAMPLES</span>
          <strong>{Math.round(t * deviceRate).toLocaleString()}</strong>
          <small>{i + 1} replay frames · {num(trace.rate_hz, 0)} Hz frames of a {num(deviceRate, 0)} Hz stream</small>
        </div>
        <div className="mv-stage-cell">
          <span className="mono">SAMPLE RATE</span>
          <strong>{num(stream?.measured_rate_hz ?? deviceRate, 1)} Hz</strong>
          <small>declared {num(deviceRate, 0)} Hz · as recorded</small>
        </div>
        <div className="mv-stage-cell">
          <span className="mono">PACKETS</span>
          <strong>{stream?.packets?.received ?? stream?.packets ?? "—"}</strong>
          <small>{stream ? `${num((stream.loss_ratio ?? 0) * 100, 2, "%")} lost · ${stream.gaps ?? 0} gaps (as recorded)` : "clinician-only detail"}</small>
        </div>
        <div className="mv-stage-cell">
          <span className="mono">CALIBRATION</span>
          <strong>{calibrating ? "Calibrating…" : String(cal?.status ?? a.calibration_state)}</strong>
          <small>{calibrating ? "still, then the exercise slowly" : `quality ${num(cal?.quality, 2)}`}</small>
        </div>
      </div>

      <div className="mv-stage-grid mv-stage-sides">
        {(["left", "right"] as const).map((side) => (
          <div key={side} className={`mv-imu mv-imu-${side}`}>
            <span className="eyebrow">{side.toUpperCase()} IMU · MPU6050 · SHANK</span>
            <dl>
              <div><dt>Tilt</dt><dd>{num(v(`${side}_tilt_deg`), 1, "°")}</dd></div>
              <div><dt>|ω|</dt><dd>{num(v(`${side}_gyro_dps`), 0, "°/s")}</dd></div>
              <div><dt>|a|</dt><dd>{num(v(`${side}_acc_g`), 2, " g")}</dd></div>
            </dl>
            <span className="mv-force" title="Force channel, normalised ADC (not newtons)">
              <span className="mono">{((side === "left" ? forceLeft : forceRight) ? forceLabel((side === "left" ? forceLeft : forceRight) as string) : "force").toUpperCase()}</span>
              <span className="mv-bars-track"><i style={{ width: `${Math.min(100, 100 * (forceOf(side) ?? 0))}%` }} /></span>
              <span className="mono">{num(forceOf(side), 2)}</span>
            </span>
          </div>
        ))}
        <div className="mv-imu mv-imu-ai">
          <span className="eyebrow">PIPELINE OUTPUT AT THIS MOMENT</span>
          <dl>
            <div><dt>Activity (model)</dt><dd>{calibrating ? "waiting for calibration" : activity ? `${activityLabel(activity.activity)}${activity.status !== "OK" ? " · low confidence" : ""}` : "—"}</dd></div>
            <div><dt>Movement quality</dt><dd>{num(assessed?.mqi)}</dd></div>
            <div><dt>Asymmetry</dt><dd>{assessed?.asymmetry_score == null ? "—" : num(assessed.asymmetry_score * 100, 1, "%")}</dd></div>
          </dl>
        </div>
      </div>

      <div className="mv-chart" style={{ height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={recent} margin={{ top: 6, right: 8, bottom: 6, left: 0 }}>
            <YAxis width={36} tick={{ fill: c.tick, fontSize: 10 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
            <Line type="monotone" dataKey="l" stroke={c.teal} dot={false} strokeWidth={1.6} isAnimationActive={false} />
            <Line type="monotone" dataKey="r" stroke={c.violet} dot={false} strokeWidth={1.6} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="fine-print">Last 10 s of left (teal) and right (violet) segment tilt, as the pipeline computed it.</p>
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * B. real ESP32
 * ------------------------------------------------------------------ */

function RealDevice() {
  const [nonce, setNonce] = useState(0);
  const live = useApi(movementApi.liveDevices, [nonce]);
  useEffect(() => {
    const timer = window.setInterval(() => setNonce((n) => n + 1), 5000);
    return () => window.clearInterval(timer);
  }, []);
  const online = live.data?.physical_online ?? [];
  if (online.length) {
    return (
      <Panel eyebrow="REAL ESP32" title="A registered device is streaming">
        <ul className="mv-devices">
          {online.map((d) => (
            <li key={d.device_id}>
              <Wifi size={18} aria-hidden="true" />
              <div className="mv-device-copy">
                <strong className="mono">{d.device_id}</strong>
                <span className="fine-print">firmware {d.firmware_version ?? "—"} · {num(d.sample_rate_hz, 0)} Hz · last seen {dateTime(d.last_seen)}</span>
              </div>
              <ProvenanceBadge value="PHYSICAL_REGISTERED" compact />
            </li>
          ))}
        </ul>
        <Link className="button button-small mv-gap" href="/workspace/hardware">Open the hardware lab</Link>
      </Panel>
    );
  }
  return (
    <Panel eyebrow="REAL ESP32" title="WAITING FOR REAL ESP32"
      footer={live.data ? `Checked ${dateTime(live.data.checked_at)} · every 5 s · a registered device that is online and seen in the last minute counts.` : undefined}>
      <div className="mv-waiting">
        <span className="mv-waiting-pulse" aria-hidden="true" />
        <p>
          No authenticated RehabSense device is connected. Nothing here is simulated: this panel stays
          waiting until a registered ESP32 (two MPU6050 + heel force) opens its stream with its own key.
        </p>
        <ol>
          <li>Register the board (Devices → register; a technician or admin account) and note its key.</li>
          <li>Flash the firmware in <code>firmware/rehabsense_dual_imu</code> with that key and your Wi-Fi.</li>
          <li>Power it on: it connects to <code>/ws/ingest/v2</code> and appears here within seconds.</li>
        </ol>
        {live.error && <p className="fine-print mv-error">{live.error}</p>}
      </div>
    </Panel>
  );
}
