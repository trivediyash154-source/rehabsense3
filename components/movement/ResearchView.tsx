"use client";

import Link from "next/link";
import { useMemo } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { movementApi, useApi, type Research } from "@/lib/api/movement";
import { activityLabel, compact, exerciseLabel, num, signed } from "@/lib/movement-format";
import { Failure, Kpi, KpiGrid, Loading, Panel, StatusChip, TrendTag } from "./Bits";
import { DistributionBars, Histogram, QualityScatter, tooltipStyle, useChartColors } from "./Charts";
import { PROVENANCE_BADGE, ProvenanceBadge, ResearchNote } from "./Provenance";

export function ResearchView() {
  const { data, error, loading, reload } = useApi(movementApi.research, []);
  const models = useApi(movementApi.mlModels, []);
  if (loading && !data) return <Loading what="research analytics" />;
  if (error || !data) return <Failure error={error ?? "No data."} retry={reload} />;
  return <Body r={data} block={models.data?.status_block ?? null} />;
}

function Body({ r, block }: { r: Research; block: Record<string, string | number> | null }) {
  const c = useChartColors();
  const synthetic = r.labels.provenance != null;
  const exColors = useMemo(() => {
    const keys = Object.keys(r.dataset.exercises);
    return Object.fromEntries(keys.map((k, i) => [k, c.series[i % c.series.length]]));
  }, [r.dataset.exercises, c.series]);
  const scatter = r.movement.points
    .filter((p) => p.mqi != null && p.asymmetry_pct != null)
    .map((p) => ({ x: p.asymmetry_pct as number, y: p.mqi as number, group: exerciseLabel(p.exercise_type) }));
  const groupColor = (g: string) => {
    const key = Object.keys(exColors).find((k) => exerciseLabel(k) === g);
    return key ? exColors[key] : c.tick;
  };
  // Longitudinal overlay on programme day, one line per record.
  const overlay = useMemo(() => {
    const byDay = new Map<number, Record<string, number | null>>();
    r.longitudinal.records.forEach((rec) => {
      rec.series.forEach((p) => {
        if (p.day == null) return;
        const row = byDay.get(p.day) ?? { day: p.day };
        row[`p${rec.patient_id}`] = p.mqi;
        byDay.set(p.day, row);
      });
    });
    return Array.from(byDay.values()).sort((a, b) => (a.day as number) - (b.day as number));
  }, [r.longitudinal.records]);
  const agreement = r.model.replay_agreement;
  const confusionCols = Array.from(new Set(Object.values(agreement.confusion).flatMap((m) => Object.keys(m))));

  return (
    <>
      <WorkspaceHeader
        eyebrow="RESEARCH VIEW"
        title="Dataset, model, movement, trajectories."
        lede="Everything the stored data can say about the pipeline itself — with each source kept apart. Research metrics; none clinically validated."
        stats={[
          { label: "SESSIONS", value: String(r.dataset.sessions) },
          { label: "SAMPLES", value: compact(r.dataset.samples), tone: "violet" },
          { label: "MODEL WINDOWS", value: compact(r.model.total), tone: "teal" },
          { label: "PHYSICAL SESSIONS", value: String(r.dataset.physical_sessions), tone: "amber" },
        ]}
      />
      <ResearchNote synthetic={synthetic} />

      <Panel eyebrow="DATASET SUMMARY" title="What is stored, and where it came from">
        <KpiGrid>
          <Kpi label="SESSIONS" value={r.dataset.sessions} sub={Object.entries(r.dataset.sessions_by_provenance).map(([p, n]) => `${n} ${(PROVENANCE_BADGE[p]?.label ?? p).toLowerCase()}`).join(" · ")} />
          <Kpi label="RECORDS" value={r.dataset.patients} sub={Object.entries(r.dataset.records_by_provenance).map(([p, n]) => `${n} ${p === "REAL_RECORD" ? "recorded" : (PROVENANCE_BADGE[p]?.label ?? p).toLowerCase()}`).join(" · ")} tone="violet" />
          <Kpi label="SAMPLES" value={compact(r.dataset.samples)} sub={`${compact(r.dataset.chunks)} stored raw-sample chunks (13 channels)`} tone="blue" />
          <Kpi label="ACTIVITIES" value={r.dataset.activities.length} sub={r.dataset.activities.map(activityLabel).join(", ")} tone="teal" />
          <Kpi label="EXERCISES" value={Object.keys(r.dataset.exercises).length} sub={Object.entries(r.dataset.exercises).map(([e, n]) => `${exerciseLabel(e)} ${n}`).join(" · ")} tone="cyan" />
          <Kpi label="MODEL VERSIONS" value={r.dataset.model_versions.length} sub={r.dataset.model_versions.join(", ") || "none"} tone="muted" />
        </KpiGrid>
        <ul className="mv-bars mv-gap">
          {Object.entries(r.dataset.sessions_by_provenance).map(([p, n]) => (
            <li key={p}>
              <span className="mv-bars-label"><ProvenanceBadge value={p} compact /></span>
              <span className="mv-bars-track" aria-hidden="true"><i style={{ width: `${(100 * n) / Math.max(1, r.dataset.sessions)}%` }} /></span>
              <span className="mv-bars-value mono">{n}</span>
            </li>
          ))}
        </ul>
      </Panel>

      <div className="mv-grid-2">
        <Panel eyebrow="MODEL ANALYTICS" title={`${compact(r.model.total)} inference windows`}
          footer={r.model.note}>
          <dl className="mv-facts">
            {Object.entries(r.model.by_status).map(([k, n]) => (
              <div key={k}><dt>{k.replace(/_/g, " ").toLowerCase()}</dt><dd>{n.toLocaleString()} ({num((100 * n) / Math.max(1, r.model.total), 1, "%")})</dd></div>
            ))}
            <div><dt>Mean confidence</dt><dd>{num(r.model.mean_confidence, 3)}</dd></div>
            {Object.entries(r.model.by_model).map(([m, n]) => (
              <div key={m}><dt>{m}</dt><dd>{n.toLocaleString()} windows</dd></div>
            ))}
          </dl>
          <span className="eyebrow mv-gap">CONFIDENCE DISTRIBUTION</span>
          <Histogram bins={r.model.confidence_histogram} color={c.blue} height={150} />
        </Panel>
        <Panel eyebrow="ACTIVITY DISTRIBUTION" title="What the model reported, by source">
          {Object.entries(r.model.by_provenance).map(([p, counts]) => (
            <div key={p} className="mv-subsection">
              <span className="mv-subhead"><ProvenanceBadge value={p} compact /> {counts.total.toLocaleString()} windows</span>
              <DistributionBars seconds={counts.by_activity} top={5} />
            </div>
          ))}
        </Panel>
      </div>

      <Panel eyebrow="MODEL RESULT — PUBLIC DATASET REPLAY" title={agreement.agreement_pct != null ? `${num(agreement.agreement_pct, 1, "%")} agreement with the dataset's labels` : "No public replay stored"}
        footer={agreement.scope}>
        {agreement.windows_scored > 0 ? (
          <div className="mv-table-wrap">
            <table className="mv-table mv-confusion">
              <thead>
                <tr><th>Dataset label ↓ / model output →</th>{confusionCols.map((k) => <th key={k} className="num">{k.startsWith("(") ? k : activityLabel(k)}</th>)}</tr>
              </thead>
              <tbody>
                {Object.entries(agreement.confusion).map(([truth, row]) => (
                  <tr key={truth}>
                    <td>{activityLabel(truth)}</td>
                    {confusionCols.map((k) => (
                      <td key={k} className={`num${k === truth ? " is-diag" : ""}`}>{row[k] ?? ""}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="mv-empty">Replay public recordings with the seed script to populate this check.</p>}
      </Panel>

      <div className="mv-grid-2">
        <Panel eyebrow="MOVEMENT ANALYTICS" title={`Mean MQI ${num(r.movement.mean_mqi)} · mean asymmetry ${num(r.movement.mean_asymmetry_pct, 1, "%")}`}>
          <span className="eyebrow">MQI DISTRIBUTION (SESSIONS)</span>
          <Histogram bins={r.movement.mqi_histogram} color={c.teal} height={150} />
          <span className="eyebrow mv-gap">ASYMMETRY DISTRIBUTION (SESSIONS)</span>
          <Histogram bins={r.movement.asymmetry_histogram} color={c.violet} height={150} unit="%" />
        </Panel>
        <Panel eyebrow="QUALITY VS ASYMMETRY" title="Each session, by exercise"
          footer="MQI includes a symmetry component, so some coupling is by construction — not a finding.">
          <QualityScatter points={scatter} colorFor={groupColor} height={260} />
          <ul className="mv-legend">
            {Object.keys(exColors).map((k) => <li key={k}><i style={{ background: exColors[k] }} />{exerciseLabel(k)}</li>)}
          </ul>
        </Panel>
      </div>

      <div className="mv-grid-3">
        <Panel eyebrow="MQI COMPONENTS" title="Mean across sessions">
          <ul className="mv-bars">
            {Object.entries(r.movement.components_mean).filter(([, v]) => v != null).map(([k, v]) => (
              <li key={k}>
                <span className="mv-bars-label">{k.replace(/_/g, " ")}</span>
                <span className="mv-bars-track" aria-hidden="true"><i style={{ width: `${(v as number) * 100}%` }} /></span>
                <span className="mv-bars-value mono">{num((v as number) * 100, 0)}</span>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel eyebrow="REPETITION TIMING" title="Mean repetition / cycle time">
          <dl className="mv-facts">
            {Object.entries(r.movement.rep_duration_by_exercise).map(([ex, d]) => (
              <div key={ex}><dt>{exerciseLabel(ex)}</dt><dd>{num(d, 2, " s")}</dd></div>
            ))}
          </dl>
        </Panel>
        <Panel eyebrow="LEFT / RIGHT" title={`${num(r.movement.left_right_rom_difference_deg, 1, "°")} mean range difference`}
          footer="Absolute difference of the mean per-repetition segment-tilt range between sides.">
          <dl className="mv-facts">
            {r.longitudinal.records.map((rec) => (
              <div key={rec.patient_id}><dt>{rec.name}</dt><dd>MQI SD {num(r.movement.mqi_sd_by_patient[String(rec.patient_id)])}</dd></div>
            ))}
          </dl>
        </Panel>
      </div>

      <Panel eyebrow="LONGITUDINAL ANALYSIS" title="Trajectories by programme day"
        footer={`Mean adherence ${num(r.longitudinal.mean_adherence_pct, 0, "%")}. Trajectory classes: ${Object.entries(r.longitudinal.trajectories).map(([k, n]) => `${n} ${k}`).join(", ")}.`}>
        <div className="mv-chart" style={{ height: 280 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={overlay} margin={{ top: 10, right: 14, bottom: 0, left: -14 }}>
              <CartesianGrid vertical={false} stroke={c.grid} strokeDasharray="3 6" />
              <XAxis dataKey="day" type="number" domain={[1, "dataMax"]} tick={{ fill: c.tick, fontSize: 10 }}
                axisLine={false} tickLine={false} tickFormatter={(v: number) => `day ${v}`} />
              <YAxis domain={[50, 100]} tick={{ fill: c.tick, fontSize: 10 }} axisLine={false} tickLine={false} width={44} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => `Programme day ${v}`} formatter={(v: number, n: string) => [num(v), n]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {r.longitudinal.records.map((rec, i) => (
                <Line key={rec.patient_id} type="monotone" dataKey={`p${rec.patient_id}`} name={rec.name}
                  stroke={c.series[i % c.series.length]} strokeWidth={1.8} dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mv-table-wrap">
          <table className="mv-table">
            <thead>
              <tr><th>Record</th><th>Status</th><th>Quality trend</th><th>Asymmetry trend</th><th className="num">Start → current MQI</th><th className="num">Sessions</th><th className="num">Adherence</th><th className="num">Consistency SD</th></tr>
            </thead>
            <tbody>
              {r.longitudinal.records.map((rec) => (
                <tr key={rec.patient_id}>
                  <td><Link href={`/workspace/patients/${rec.patient_id}`}>{rec.name}</Link></td>
                  <td><StatusChip status={rec.status} /></td>
                  <td><TrendTag trend={rec.mqi_trend} label={`${signed(rec.mqi_slope_per_week, 2)}/wk`} /></td>
                  <td><TrendTag trend={rec.asymmetry_trend} label={`${signed(rec.asymmetry_slope_per_week, 2)}/wk`} /></td>
                  <td className="num">{num(rec.initial_mqi)} → {num(rec.current_mqi)}</td>
                  <td className="num">{rec.sessions}</td>
                  <td className="num">{num(rec.adherence_pct, 0, "%")}</td>
                  <td className="num">{num(rec.consistency_sd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel eyebrow="VALIDATION STATUS" title="What has and has not been shown"
        footer="Computed from the deployed model bundles and registered-device data — never asserted. Public-dataset performance is not RehabSense hardware performance.">
        <dl className="mv-facts mv-validation">
          <div><dt>Model implemented</dt><dd>{String(block?.MODEL_IMPLEMENTED ?? "—")}</dd></div>
          <div><dt>Public dataset validated</dt><dd>{String(block?.PUBLIC_DATASET_VALIDATED ?? "—")}</dd></div>
          <div><dt>Real RehabSense hardware validated</dt><dd className="is-no">{String(block?.REAL_REHABSENSE_HARDWARE_VALIDATED ?? "NO")}</dd></div>
          <div><dt>Human-labelled physical recordings</dt><dd>{String(block?.HUMAN_LABELED_PHYSICAL_DATA ?? 0)}</dd></div>
          <div><dt>Clinical validation</dt><dd className="is-no">{String(block?.CLINICAL_VALIDATION ?? "NO")}</dd></div>
        </dl>
      </Panel>
    </>
  );
}
