"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { movementApi, useApi, type PatientMovement } from "@/lib/api/movement";
import {
  activityLabel,
  clock,
  exerciseLabel,
  longDate,
  num,
  parseTime,
  shortDate,
  signed,
} from "@/lib/movement-format";
import { Failure, Kpi, KpiGrid, Loading, Panel, StatusChip, TrendTag } from "./Bits";
import { DistributionBars, TrendChart, useChartColors } from "./Charts";
import { ProvenanceBadge, ResearchNote } from "./Provenance";
import { ReportsPanel } from "./ReportsPanel";

/**
 * One record's longitudinal movement summary (GET /analytics/patients/{id}).
 * `detail` is the patient page; `progress` the Progress page's analysis view.
 */
export function PatientMovementView({ patientId, variant }: { patientId: number; variant: "detail" | "progress" }) {
  const { data, error, loading, reload } = useApi(() => movementApi.patient(patientId), [patientId]);
  if (loading && !data) return <Loading what="this record" />;
  if (error || !data) return <Failure error={error ?? "No data."} retry={reload} />;
  return <Body data={data} variant={variant} />;
}

function Body({ data, variant }: { data: PatientMovement; variant: "detail" | "progress" }) {
  const c = useChartColors();
  const router = useRouter();
  const { patient, summary: s, sessions } = data;
  const synthetic = patient.provenance === "SYNTHETIC_DEMONSTRATION";
  const replay = patient.provenance === "PUBLIC_DATASET_REPLAY";

  const points = useMemo(
    () =>
      sessions.map((r) => ({
        x: parseTime(r.started_at)?.getTime() ?? 0,
        id: r.id,
        mqi: r.mqi,
        asym: r.asymmetry_pct,
        reps: r.repetitions,
        duration: r.duration_s == null ? null : Math.round(r.duration_s),
        confidence: r.confidence_pct,
      })),
    [sessions],
  );
  const open = (datum: Record<string, unknown>) => {
    if (typeof datum.id === "number") router.push(`/workspace/sessions/${datum.id}`);
  };

  const title = variant === "progress"
    ? synthetic ? "Longitudinal synthetic demonstration." : "Progress across the recorded period."
    : patient.name;

  return (
    <>
      <WorkspaceHeader
        eyebrow={variant === "progress" ? `LONGITUDINAL PROGRESS · ${patient.name.toUpperCase()}` : "PATIENT RECORD"}
        title={title}
        lede={[
          s.programme ?? "No programme set",
          s.programme_days ? `${s.programme_days}-day programme` : null,
          `operated side ${patient.operated_leg.toLowerCase()}`,
          patient.age ? `demo age ${patient.age}` : null,
        ].filter(Boolean).join(" · ")}
        stats={[
          { label: "SESSIONS", value: String(s.sessions_completed) },
          { label: "CURRENT MQI", value: num(s.current_mqi), tone: "teal" },
          { label: "CHANGE", value: signed(s.mqi_change), tone: (s.mqi_change ?? 0) >= 0 ? "teal" : "amber" },
          { label: "STATUS", value: s.status.replace("_", " ").toLowerCase(), tone: s.status === "NEEDS_ATTENTION" ? "amber" : "violet" },
        ]}
        actions={<ProvenanceBadge value={patient.provenance ?? s.provenance} />}
      />
      <ResearchNote synthetic={synthetic}>
        {replay
          ? "Public dataset replay: healthy public volunteers' recordings re-sent through the device pipeline. Not a patient, not RehabSense hardware data."
          : undefined}
      </ResearchNote>

      <KpiGrid>
        <Kpi label="PROGRAMME" value={s.programme ?? "—"}
          sub={s.start_date ? `from ${longDate(s.start_date)}${s.programme_end ? ` to ${longDate(s.programme_end)}` : ""}` : "no start date"} tone="blue" />
        <Kpi label="DURATION" value={`${s.duration_days} days`} sub={`${num(s.sessions_per_week, 1)} sessions per week`} tone="muted" />
        <Kpi label="SESSIONS COMPLETED" value={s.planned_sessions ? `${s.sessions_completed} / ${s.planned_sessions}` : s.sessions_completed}
          sub={s.planned_sessions ? "of the planned programme" : "no plan recorded"} tone="violet" />
        <Kpi label="ADHERENCE" value={num(s.adherence_pct, 0, "%")}
          sub={s.expected_sessions_to_date != null ? `vs ${num(s.expected_sessions_to_date, 1)} expected to date` : "needs a planned programme"} tone="cyan" />
        <Kpi label="MOVEMENT QUALITY" value={`${num(s.initial_mqi)} → ${num(s.current_mqi)}`}
          sub={`${signed(s.mqi_change)} points · ${signed(s.improvement_pct, 0, "%")}`} tone="teal" />
        <Kpi label="ASYMMETRY" value={`${num(s.initial_asymmetry_pct, 1, "%")} → ${num(s.current_asymmetry_pct, 1, "%")}`}
          sub={`${signed(s.asymmetry_change_pct)} points · lower = more alike`} tone="violet" />
        <Kpi label="TREND" value={<StatusChip status={s.status} />}
          sub={<><TrendTag trend={s.mqi_trend} label={`MQI ${signed(s.mqi_slope_per_week, 2)}/wk`} /> <TrendTag trend={s.asymmetry_trend} label={`asym ${signed(s.asymmetry_slope_per_week, 2)}/wk`} /></>} tone="amber" />
        <Kpi label="CONSISTENCY" value={`SD ${num(s.consistency_sd)}`} sub="MQI spread over the last six sessions" tone="muted" />
        {variant === "progress" && (
          <>
            <Kpi label="BEST SESSION" value={num(s.best_session?.mqi)}
              sub={s.best_session ? `${shortDate(s.best_session.started_at)} · ${exerciseLabel(s.best_session.exercise_type)}` : "—"} tone="teal" />
            <Kpi label="WORST SESSION" value={num(s.worst_session?.mqi)}
              sub={s.worst_session ? `${shortDate(s.worst_session.started_at)} · ${exerciseLabel(s.worst_session.exercise_type)}` : "—"} tone="coral" />
          </>
        )}
      </KpiGrid>

      {s.status_reasons.length > 0 && (
        <p className="fine-print mv-reasons">
          <strong>Why “{s.status.replace("_", " ").toLowerCase()}”:</strong> {s.status_reasons.join("; ")}. {data.status_rule.basis}.
        </p>
      )}

      <div className="mv-grid-2">
        <Panel eyebrow="MOVEMENT QUALITY OVER TIME" title="MQI per session (research metric)"
          footer="Dashed line: the start value (mean of the first two sessions). Click a point to open the session.">
          <TrendChart data={points} height={250} domain={[40, 100]} onSelect={open}
            reference={s.initial_mqi != null ? { y: s.initial_mqi, label: "start" } : undefined}
            series={[{ key: "mqi", label: "MQI", color: c.teal }]} />
        </Panel>
        <Panel eyebrow="ASYMMETRY OVER TIME" title="Bilateral asymmetry per session"
          footer="0% = left and right segments move alike. Segment tilt from the two shank IMUs, not a joint angle.">
          <TrendChart data={points} height={250} domain={[0, "auto"]} unit="%" onSelect={open}
            reference={s.initial_asymmetry_pct != null ? { y: s.initial_asymmetry_pct, label: "start" } : undefined}
            series={[{ key: "asym", label: "Asymmetry", color: c.violet }]} />
        </Panel>
      </div>

      <div className="mv-grid-3">
        <Panel eyebrow="REPETITIONS OVER TIME" title={`Mean ${num(s.mean_repetitions, 0)} per session`}>
          <TrendChart data={points} height={180} digits={0} onSelect={open}
            series={[{ key: "reps", label: "Repetitions / gait cycles", color: c.blue }]} />
        </Panel>
        <Panel eyebrow="SESSION DURATION" title={`Mean ${clock(s.mean_duration_s)}`}>
          <TrendChart data={points} height={180} unit=" s" digits={0} onSelect={open}
            series={[{ key: "duration", label: "Duration", color: c.amber }]} />
        </Panel>
        <Panel eyebrow="SIGNAL CONFIDENCE" title={`Mean ${num(s.mean_confidence_pct, 0, "%")}`}
          footer="Stream completeness × calibration quality.">
          <TrendChart data={points} height={180} unit="%" digits={0} domain={[50, 100]} onSelect={open}
            series={[{ key: "confidence", label: "Confidence", color: c.cyan }]} />
        </Panel>
      </div>

      <div className="mv-grid-2">
        <Panel eyebrow="ACTIVITY DISTRIBUTION" title="Activity-model output, all sessions"
          footer={`Model ${s.models.join(", ") || "unavailable"}, trained on public datasets. On ${synthetic ? "synthetic" : replay ? "replayed" : "these"} signals it is a model result, not an observation.`}>
          <DistributionBars seconds={s.activity_seconds} />
        </Panel>
        <Panel eyebrow="PROGRAMME MIX" title="Exercises and session frequency">
          <ul className="mv-bars">
            {Object.entries(s.exercises).map(([ex, n]) => (
              <li key={ex}>
                <span className="mv-bars-label">{exerciseLabel(ex)}</span>
                <span className="mv-bars-track" aria-hidden="true"><i style={{ width: `${(100 * n) / Math.max(1, s.sessions_completed)}%` }} /></span>
                <span className="mv-bars-value mono">{n}</span>
              </li>
            ))}
          </ul>
          <p className="fine-print mv-gap">
            {num(s.sessions_per_week, 1)} sessions per week over {s.duration_days} days · last session{" "}
            {s.last_session_at ? longDate(s.last_session_at) : "—"}.
          </p>
        </Panel>
      </div>

      <Panel eyebrow="SESSION HISTORY" title={`${sessions.length} completed sessions`}>
        <div className="mv-table-wrap">
          <table className="mv-table">
            <thead>
              <tr>
                <th>Date</th><th className="num">Day</th><th>Exercise</th><th className="num">Duration</th>
                <th className="num">Reps</th><th className="num">Quality</th><th className="num">Asymmetry</th>
                <th>Status</th><th>Activity (model)</th><th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {[...sessions].reverse().map((r) => (
                <tr key={r.id} className="is-link" onClick={() => router.push(`/workspace/sessions/${r.id}`)}>
                  <td><Link href={`/workspace/sessions/${r.id}`}>{longDate(r.started_at)}</Link></td>
                  <td className="num">{r.programme_day ?? "—"}</td>
                  <td>{exerciseLabel(r.exercise_type)}</td>
                  <td className="num">{clock(r.duration_s)}</td>
                  <td className="num">{r.repetitions ?? "—"}</td>
                  <td className="num">{num(r.mqi)}</td>
                  <td className="num">{num(r.asymmetry_pct, 1, "%")}</td>
                  <td>{r.status.toLowerCase()} · calib. {(r.calibration_status ?? "—").toLowerCase()}</td>
                  <td title={r.model ?? undefined}>{activityLabel(r.activity_top)}</td>
                  <td><ProvenanceBadge value={r.provenance} compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {variant === "detail" && !replay && <ReportsPanel patientId={patient.id} patientName={patient.name} />}
    </>
  );
}
