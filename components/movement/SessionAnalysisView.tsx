"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { movementApi, useApi, type SessionAnalysis, type SessionTrace } from "@/lib/api/movement";
import { activityLabel, clock, dateTime, exerciseLabel, num } from "@/lib/movement-format";
import { Failure, Kpi, KpiGrid, Loading, Panel } from "./Bits";
import { ActivityTimeline, tooltipStyle, useChartColors } from "./Charts";
import { ProvenanceBadge, ResearchNote } from "./Provenance";

type Summary = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const Y_AXIS = 40;
const RIGHT = 8;

/** Index of the last row with t <= time (rows sorted by t). */
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

/** Session-time series chart; the cursor is an overlay so playback stays cheap. */
/** The force column for one side, whatever the device named its channels. */
export function forceColumn(columns: string[], side: "left" | "right"): string | undefined {
  return columns.find((n) => n.startsWith("force_") && n.includes(side));
}

export function forceLabel(column: string): string {
  return column.replace(/^force_/, "").replace(/_(adc_norm|N)$/, "").replace(/_/g, " ");
}

function SignalChart({
  data,
  lines,
  cursor,
  duration,
  height,
  unit,
  domain,
  tickDigits = 0,
}: {
  data: Record<string, number | null>[];
  lines: { key: string; label: string; color: string }[];
  cursor: number;
  duration: number;
  height: number;
  unit: string;
  domain?: [number | "auto", number | "auto"];
  tickDigits?: number;
}) {
  const c = useChartColors();
  const chart = useMemo(
    () => (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: RIGHT, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={c.grid} strokeDasharray="3 6" />
          <XAxis dataKey="t" type="number" domain={[0, duration]} tick={{ fill: c.tick, fontSize: 10 }}
            axisLine={false} tickLine={false} tickFormatter={(v: number) => `${Math.round(v)}s`} />
          <YAxis width={Y_AXIS} domain={domain ?? ["auto", "auto"]} tick={{ fill: c.tick, fontSize: 10 }}
            axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v.toFixed(tickDigits)}${unit}`} />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => `t = ${Number(v).toFixed(1)} s`}
            formatter={(v: number, name: string) => [`${num(v, 1)}${unit}`, name]} />
          {lines.map((l) => (
            <Line key={l.key} type="monotone" dataKey={l.key} name={l.label} stroke={l.color} dot={false}
              strokeWidth={1.4} isAnimationActive={false} connectNulls={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    ),
    [data, lines, duration, domain, unit, c, tickDigits],
  );
  const frac = duration > 0 ? Math.min(1, Math.max(0, cursor / duration)) : 0;
  return (
    <div className="mv-chart mv-signal" style={{ height }}>
      {chart}
      <i className="mv-cursor" style={{ left: `calc(${Y_AXIS}px + (100% - ${Y_AXIS + RIGHT}px) * ${frac})` }} aria-hidden="true" />
    </div>
  );
}

export function SessionAnalysisView({ sessionId }: { sessionId: number }) {
  const analysis = useApi(() => movementApi.analysis(sessionId), [sessionId]);
  const trace = useApi(() => movementApi.trace(sessionId), [sessionId]);
  if (analysis.loading && !analysis.data) return <Loading what="the session" />;
  if (analysis.error || !analysis.data) return <Failure error={analysis.error ?? "No data."} retry={analysis.reload} />;
  if (analysis.data.protocol_version !== 2 || !analysis.data.summary) {
    return (
      <Failure error="This session has no hardware-v2 analysis (it may be a protocol v1 recording, or still running)." />
    );
  }
  return <Body a={analysis.data} trace={trace.data} traceError={trace.error} traceLoading={trace.loading} />;
}

function Body({
  a,
  trace,
  traceError,
  traceLoading,
}: {
  a: SessionAnalysis;
  trace: SessionTrace | null;
  traceError: string | null;
  traceLoading: boolean;
}) {
  const c = useChartColors();
  const s = a.summary as Summary;
  const mq = s.movement_quality ?? {};
  const bi = s.bilateral ?? {};
  const rs = s.repetition_summary ?? {};
  const act = s.activity ?? {};
  const conf = s.confidence ?? {};
  const cal = s.calibration ?? null;
  const stream = s.stream ?? null;
  const gen = a.generation;
  const synthetic = a.provenance === "SYNTHETIC_DEMONSTRATION";
  const duration = Number(s.duration_s ?? 0);

  // --- replay over the stored trace ----------------------------------------
  const rows = useMemo(() => trace?.rows ?? [], [trace]);
  const col = useMemo(() => {
    const index: Record<string, number> = {};
    (trace?.columns ?? []).forEach((name, i) => (index[name] = i));
    return index;
  }, [trace]);
  const forceCols = useMemo(() => (trace?.columns ?? []).filter((n) => n.startsWith("force_")), [trace]);
  const end = rows.length ? Number(rows[rows.length - 1][0]) : duration;
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const raf = useRef<number | null>(null);
  const last = useRef<number | null>(null);

  useEffect(() => {
    if (!playing) return;
    const step = (now: number) => {
      const prev = last.current ?? now;
      last.current = now;
      setCursor((t) => {
        const next = t + ((now - prev) / 1000) * speed;
        if (next >= end) {
          setPlaying(false);
          return end;
        }
        return next;
      });
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      raf.current = null;
      last.current = null;
    };
  }, [playing, speed, end]);

  const tiltData = useMemo(
    () => rows.map((r) => ({ t: Number(r[0]), left: r[col.left_tilt_deg] as number | null, right: r[col.right_tilt_deg] as number | null })),
    [rows, col],
  );
  const forceData = useMemo(
    () => rows.map((r) => {
      const point: Record<string, number | null> = { t: Number(r[0]) };
      forceCols.forEach((name) => (point[name] = r[col[name]] as number | null));
      return point;
    }),
    [rows, col, forceCols],
  );
  const tiltLines = useMemo(() => [
    { key: "left", label: "Left shank tilt", color: c.teal },
    { key: "right", label: "Right shank tilt", color: c.violet },
  ], [c]);
  const forceLines = useMemo(() => forceCols.map((name) => ({
    key: name, label: `${forceLabel(name)} (normalised)`, color: name.includes("right") ? c.violet : c.teal,
  })), [forceCols, c]);
  const forceLeft = forceColumn(trace?.columns ?? [], "left");
  const forceRight = forceColumn(trace?.columns ?? [], "right");

  const at = rowAt(rows, cursor);
  const now = at >= 0 ? rows[at] : null;
  const v = (name: string) => (now && col[name] != null ? (now[col[name]] as number | null) : null);
  const activityNow = a.activity_segments.find((g) => g.t_start <= cursor && cursor <= g.t_end) ?? null;
  const windowNow = [...a.assessments].reverse().find((w) => w.t_end <= cursor + 0.01) ?? null;
  const repsNow = a.repetitions.filter((r) => r.t_start <= cursor && cursor <= r.t_end);

  const assessmentData = useMemo(() => a.assessments.map((w) => ({
    t: w.t_end, mqi: w.mqi, asym: w.asymmetry_score == null ? null : w.asymmetry_score * 100,
  })), [a.assessments]);
  const assessmentLines = useMemo(() => [
    { key: "mqi", label: "Window MQI", color: c.teal },
    { key: "asym", label: "Window asymmetry %", color: c.violet },
  ], [c]);

  const leftReps = a.repetitions.filter((r) => r.side === "LEFT");
  const rightReps = a.repetitions.filter((r) => r.side === "RIGHT");
  const side = (k: "LEFT" | "RIGHT") => rs[k] ?? {};
  const mean = (xs: (number | null)[]) => {
    const vals = xs.filter((x): x is number => x != null);
    return vals.length ? vals.reduce((p, q) => p + q, 0) / vals.length : null;
  };

  return (
    <>
      <WorkspaceHeader
        eyebrow={`SESSION ${a.session_id} · ${exerciseLabel(a.exercise_type).toUpperCase()}`}
        title={`${exerciseLabel(a.exercise_type)}, ${dateTime(a.started_at)}`}
        lede={`Hardware protocol v2 · ${a.status.toLowerCase()} · calibration ${String(cal?.status ?? a.calibration_state).toLowerCase()} · every panel below is read from what the pipeline stored for this session.`}
        stats={[
          { label: "MQI", value: num(mq.mqi), tone: "teal" },
          { label: "ASYMMETRY", value: num(bi.asymmetry_score == null ? null : bi.asymmetry_score * 100, 1, "%"), tone: "violet" },
          { label: "REPETITIONS", value: String(s.repetitions ?? "—") },
          { label: "DURATION", value: clock(duration), tone: "amber" },
        ]}
        actions={
          <div className="mv-head-actions">
            <ProvenanceBadge value={a.provenance} />
            <Link className="mv-link" href={`/workspace/patients/${a.patient_id}`}>Open record</Link>
          </div>
        }
      />
      <ResearchNote synthetic={synthetic}>
        {a.provenance === "PUBLIC_DATASET_REPLAY"
          ? "Public dataset replay — a public volunteer's recording re-sent through the device pipeline. Model result — public dataset replay, not a patient's sensor result."
          : undefined}
      </ResearchNote>

      <Panel
        eyebrow="MOVEMENT REPLAY"
        title="Stored per-side trace, replayed in session time"
        actions={
          <div className="mv-player">
            <button type="button" className="button button-small" onClick={() => {
              if (cursor >= end) setCursor(0);
              setPlaying((p) => !p);
            }} disabled={!rows.length}>
              {playing ? <Pause size={13} aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
              {playing ? "Pause" : "Play"}
            </button>
            <button type="button" className="button button-outline button-small" onClick={() => { setPlaying(false); setCursor(0); }} disabled={!rows.length}>
              <RotateCcw size={13} aria-hidden="true" /> Restart
            </button>
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Playback speed">
              {[0.5, 1, 2, 4].map((x) => <option key={x} value={x}>{x}×</option>)}
            </select>
            <span className="mono">t = {cursor.toFixed(1)} s / {end.toFixed(1)} s</span>
          </div>
        }
        footer={trace ? `Frames at ${num(trace.rate_hz, 0)} Hz from the pipeline's own calibrated output (device sampled at ${num(stream?.declared_rate_hz ?? 100, 0)} Hz). Tilt is segment tilt from neutral, not a joint angle.` : undefined}
      >
        {traceLoading && !trace ? <Loading what="the movement trace" /> : traceError || !trace ? (
          <p className="mv-empty">{traceError ?? "No movement trace was stored for this session."}</p>
        ) : (
          <>
            <input className="mv-scrub" type="range" min={0} max={end} step={0.1} value={cursor}
              onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }} aria-label="Replay position" />
            <SignalChart data={tiltData} lines={tiltLines} cursor={cursor} duration={end} height={210} unit="°" />
            {forceLines.length > 0 && (
              <SignalChart data={forceData} lines={forceLines} cursor={cursor} duration={end} height={110} unit="" domain={[0, 1]} tickDigits={1} />
            )}
            <div className="mv-readouts">
              <div>
                <span className="eyebrow">LEFT</span>
                <dl>
                  <div><dt>Tilt</dt><dd>{num(v("left_tilt_deg"), 1, "°")}</dd></div>
                  <div><dt>|ω|</dt><dd>{num(v("left_gyro_dps"), 0, "°/s")}</dd></div>
                  <div><dt>|a|</dt><dd>{num(v("left_acc_g"), 2, " g")}</dd></div>
                  <div><dt>{forceLeft ? forceLabel(forceLeft) : "Force"}</dt><dd>{forceLeft ? num(v(forceLeft), 2) : "—"}</dd></div>
                </dl>
              </div>
              <div>
                <span className="eyebrow">RIGHT</span>
                <dl>
                  <div><dt>Tilt</dt><dd>{num(v("right_tilt_deg"), 1, "°")}</dd></div>
                  <div><dt>|ω|</dt><dd>{num(v("right_gyro_dps"), 0, "°/s")}</dd></div>
                  <div><dt>|a|</dt><dd>{num(v("right_acc_g"), 2, " g")}</dd></div>
                  <div><dt>{forceRight ? forceLabel(forceRight) : "Force"}</dt><dd>{forceRight ? num(v(forceRight), 2) : "—"}</dd></div>
                </dl>
              </div>
              <div>
                <span className="eyebrow">BILATERAL</span>
                <dl>
                  <div><dt>Tilt L − R</dt><dd>{v("left_tilt_deg") != null && v("right_tilt_deg") != null ? num((v("left_tilt_deg") as number) - (v("right_tilt_deg") as number), 1, "°") : "—"}</dd></div>
                  <div><dt>Activity (model)</dt><dd>{activityNow ? `${activityLabel(activityNow.activity)}${activityNow.status !== "OK" ? " (low conf.)" : ""}` : "—"}</dd></div>
                  <div><dt>Window MQI</dt><dd>{num(windowNow?.mqi)}</dd></div>
                  <div><dt>Window asym.</dt><dd>{windowNow?.asymmetry_score == null ? "—" : num(windowNow.asymmetry_score * 100, 1, "%")}</dd></div>
                  <div><dt>In repetition</dt><dd>{repsNow.length ? repsNow.map((r) => `${r.side[0]}${r.rep_index}`).join(", ") : "—"}</dd></div>
                </dl>
              </div>
            </div>
          </>
        )}
      </Panel>

      <KpiGrid>
        <Kpi label="MOVEMENT QUALITY" value={num(mq.mqi)} sub={`${String(mq.status ?? "—").toLowerCase()} · confidence ${num(mq.confidence, 2)}`} tone="teal" />
        <Kpi label="ASYMMETRY" value={num(bi.asymmetry_score == null ? null : bi.asymmetry_score * 100, 1, "%")} sub={`${String(bi.status ?? "—").toLowerCase()} · ${bi.label ?? bi.mode ?? ""}`} tone="violet" />
        <Kpi label="REPETITIONS L / R" value={`${side("LEFT").count ?? 0} / ${side("RIGHT").count ?? 0}`} sub={String(s.repetition_kind ?? "").toLowerCase().replace("_", " ")} tone="blue" />
        <Kpi label="SIGNAL CONFIDENCE" value={num(conf.percent, 0, "%")} sub={`${conf.band ?? ""} · coverage ${num((conf.bilateral_coverage ?? 0) * 100, 0, "%")}`} tone="cyan" />
        <Kpi label="CALIBRATION" value={String(cal?.status ?? a.calibration_state)} sub={cal ? `quality ${num(cal.quality, 2)}` : "details are clinician-only"} tone="amber" />
        <Kpi label="ACTIVITY MODEL" value={act.model ?? "unavailable"} sub={`${act.windows ?? 0} windows · ${act.low_confidence_windows ?? 0} low-confidence`} tone="muted" />
      </KpiGrid>

      <div className="mv-grid-2">
        <Panel eyebrow="BILATERAL COMPARISON" title="Left and right, side by side"
          footer="Range = mean segment-tilt range per repetition; SPARC closer to 0 = smoother.">
          <div className="mv-table-wrap">
            <table className="mv-table mv-compare">
              <thead><tr><th>Measure</th><th className="num">Left</th><th className="num">Right</th></tr></thead>
              <tbody>
                <tr><td>Repetitions</td><td className="num">{side("LEFT").count ?? "—"}</td><td className="num">{side("RIGHT").count ?? "—"}</td></tr>
                <tr><td>Range (mean)</td><td className="num">{num(side("LEFT").rom_proxy_deg_mean, 1, "°")}</td><td className="num">{num(side("RIGHT").rom_proxy_deg_mean, 1, "°")}</td></tr>
                <tr><td>Repetition duration</td><td className="num">{num(side("LEFT").duration_s_mean, 2, " s")}</td><td className="num">{num(side("RIGHT").duration_s_mean, 2, " s")}</td></tr>
                <tr><td>Peak angular velocity</td><td className="num">{num(side("LEFT").peak_velocity_dps_mean, 0, "°/s")}</td><td className="num">{num(side("RIGHT").peak_velocity_dps_mean, 0, "°/s")}</td></tr>
                <tr><td>Smoothness (SPARC)</td><td className="num">{num(side("LEFT").sparc_median, 2)}</td><td className="num">{num(side("RIGHT").sparc_median, 2)}</td></tr>
                <tr><td>Heel force peak (mean)</td><td className="num">{num(mean(leftReps.map((r) => r.force_peak)), 2)}</td><td className="num">{num(mean(rightReps.map((r) => r.force_peak)), 2)}</td></tr>
              </tbody>
            </table>
          </div>
          {bi.components && (
            <ul className="mv-bars mv-gap">
              {Object.entries(bi.components as Record<string, number>).map(([k, val]) => (
                <li key={k}>
                  <span className="mv-bars-label">{k.replace(/_/g, " ")}</span>
                  <span className="mv-bars-track" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.abs(val) * 100)}%`, background: "var(--violet)" }} /></span>
                  <span className="mv-bars-value mono">{num(val, 3)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel eyebrow="MOVEMENT QUALITY INDEX" title={`MQI ${num(mq.mqi)} — component breakdown`}
          footer={`${mq.label ?? "Research metric — not clinically validated"}. Equal weights over available components; unavailable: ${(mq.unavailable ?? []).join(", ") || "none"}.`}>
          <ul className="mv-bars">
            {Object.entries((mq.components ?? {}) as Record<string, number>).map(([k, val]) => (
              <li key={k}>
                <span className="mv-bars-label">{k.replace(/_/g, " ")}</span>
                <span className="mv-bars-track" aria-hidden="true"><i style={{ width: `${Math.max(1, val * 100)}%` }} /></span>
                <span className="mv-bars-value mono">{num(val * 100, 0)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel eyebrow="REPETITIONS" title={`${a.repetitions.length} detected (${leftReps.length} left, ${rightReps.length} right)`}
        footer="Each bar spans one detected repetition or gait cycle in session time; height follows its range.">
        <div className="mv-lanes">
          {(["LEFT", "RIGHT"] as const).map((sd) => {
            const reps = sd === "LEFT" ? leftReps : rightReps;
            const maxRom = Math.max(1, ...a.repetitions.map((r) => r.rom_proxy_deg));
            return (
              <div key={sd} className="mv-lane">
                <span className="mono">{sd}</span>
                <div className="mv-lane-track">
                  {reps.map((r) => (
                    <i key={`${sd}-${r.rep_index}`}
                      className={r.t_start <= cursor && cursor <= r.t_end ? "is-now" : ""}
                      title={`${sd} #${r.rep_index}: ${r.rom_proxy_deg.toFixed(1)}° range, ${(r.t_end - r.t_start).toFixed(2)} s`}
                      style={{
                        left: `${(100 * r.t_start) / Math.max(end, 1)}%`,
                        width: `${Math.max(0.3, (100 * (r.t_end - r.t_start)) / Math.max(end, 1))}%`,
                        height: `${30 + (70 * r.rom_proxy_deg) / maxRom}%`,
                        background: sd === "LEFT" ? "var(--teal)" : "var(--violet)",
                      }} />
                  ))}
                  <b className="mv-lane-cursor" style={{ left: `${(100 * cursor) / Math.max(end, 1)}%` }} />
                </div>
              </div>
            );
          })}
        </div>
        <details className="mv-details">
          <summary>Repetition table</summary>
          <div className="mv-table-wrap">
            <table className="mv-table">
              <thead><tr><th>Side</th><th className="num">#</th><th className="num">Start</th><th className="num">Duration</th><th className="num">Range</th><th className="num">Peak |ω|</th><th className="num">SPARC</th><th className="num">Force peak</th></tr></thead>
              <tbody>
                {a.repetitions.map((r) => (
                  <tr key={`${r.side}-${r.rep_index}`}>
                    <td>{r.side.toLowerCase()}</td><td className="num">{r.rep_index}</td>
                    <td className="num">{num(r.t_start, 2, " s")}</td><td className="num">{num(r.t_end - r.t_start, 2, " s")}</td>
                    <td className="num">{num(r.rom_proxy_deg, 1, "°")}</td><td className="num">{num(r.peak_velocity_dps, 0)}</td>
                    <td className="num">{num(r.smoothness_sparc, 2)}</td><td className="num">{num(r.force_peak, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </Panel>

      <div className="mv-grid-2">
        <Panel eyebrow="ACTIVITY CLASSIFICATION" title={`Model ${act.model ?? "unavailable"}`}
          footer={a.provenance === "PUBLIC_DATASET_REPLAY" ? "Model result — public dataset replay." : "On generated signals this is what the public-dataset-trained model reports, not an observation of a person."}>
          <ActivityTimeline segments={a.activity_segments} duration={end} cursor={cursor} />
        </Panel>
        <Panel eyebrow="WINDOW ASSESSMENTS" title="Movement quality and asymmetry through the session">
          <SignalChart data={assessmentData} lines={assessmentLines} cursor={cursor} duration={end} height={190} unit="" domain={[0, 100]} />
        </Panel>
      </div>

      <div className="mv-grid-2">
        <Panel eyebrow="STREAM AND CALIBRATION" title="What the device link looked like">
          {stream ? (
            <dl className="mv-facts">
              <div><dt>Declared / measured rate</dt><dd>{num(stream.declared_rate_hz, 0)} / {num(stream.measured_rate_hz, 1)} Hz</dd></div>
              <div><dt>Samples accepted</dt><dd>{stream.samples_accepted?.toLocaleString?.() ?? "—"}</dd></div>
              <div><dt>Loss</dt><dd>{num((stream.loss_ratio ?? 0) * 100, 2, "%")} · {stream.gaps ?? 0} gaps</dd></div>
              <div><dt>Both sides available</dt><dd>{num((stream.left_available_ratio ?? 0) * 100, 0, "%")} / {num((stream.right_available_ratio ?? 0) * 100, 0, "%")}</dd></div>
              <div><dt>Clock</dt><dd>{stream.clock?.sync_status ?? "—"}</dd></div>
              <div><dt>Calibration</dt><dd>{cal?.status ?? "—"} · quality {num(cal?.quality, 2)}</dd></div>
            </dl>
          ) : <p className="mv-empty">Device and stream internals are visible to the assigned clinician.</p>}
          {stream?.clock?.sync_status === "NOT_REAL_TIME" && (
            <p className="fine-print mv-gap">
              NOT_REAL_TIME: the samples were streamed faster than they were timestamped (a replayed or
              generated stream). Correctly reported; it is not physical clock drift.
            </p>
          )}
        </Panel>
        <Panel eyebrow="HOW THIS SESSION WAS PRODUCED" title={gen ? (gen.generator ?? "Generated") : "Recorded from a device"}>
          {gen ? (
            <>
              <dl className="mv-facts">
                <div><dt>Label</dt><dd>{gen.label}</dd></div>
                <div><dt>Generator version</dt><dd>{gen.synthetic_generator_version}</dd></div>
                <div><dt>Seed (session)</dt><dd>{gen.seed} ({gen.session_seed})</dd></div>
                <div><dt>Source data</dt><dd>{gen.source_dataset}{gen.dataset_subject ? ` — ${gen.dataset_subject}` : ""}</dd></div>
                <div><dt>Model</dt><dd>{gen.model_version ?? "—"} · pipeline {gen.pipeline_version}</dd></div>
                <div><dt>Generated</dt><dd>{dateTime(gen.generation_timestamp)}</dd></div>
                {gen.trajectory && <div><dt>Trajectory design</dt><dd>{gen.trajectory.replace(/_/g, " ").toLowerCase()} · day {gen.programme_day} of {gen.programme_days}</dd></div>}
              </dl>
              {gen.inputs && (
                <details className="mv-details">
                  <summary>Generator inputs (what was designed, before the pipeline measured it)</summary>
                  <div className="mv-table-wrap">
                    <table className="mv-table">
                      <thead><tr><th>Input</th><th className="num">Left</th><th className="num">Right</th></tr></thead>
                      <tbody>
                        {Object.keys(gen.inputs.left).map((k) => (
                          <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{gen.inputs!.left[k]}</td><td className="num">{gen.inputs!.right[k]}</td></tr>
                        ))}
                        <tr><td>packet loss</td><td className="num" colSpan={2}>{num(gen.inputs.packet_loss * 100, 2, "%")}</td></tr>
                        <tr><td>movement time</td><td className="num" colSpan={2}>{gen.inputs.movement_s} s</td></tr>
                        <tr><td>reported pain (generated)</td><td className="num" colSpan={2}>{gen.inputs.reported_pain}/10</td></tr>
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
              <p className="fine-print mv-gap">{gen.note}</p>
            </>
          ) : (
            <p className="mv-empty">No generation record: this session came from a device stream.</p>
          )}
        </Panel>
      </div>
    </>
  );
}
