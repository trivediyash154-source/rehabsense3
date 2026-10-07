"use client";

import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { movementApi, useApi } from "@/lib/api/movement";
import { clock, exerciseLabel, num, signed } from "@/lib/movement-format";
import { Failure, Loading, Panel, TrendTag } from "./Bits";
import { DistributionBars, Sparkline, useChartColors } from "./Charts";
import { ResearchNote } from "./Provenance";

const WHAT_IT_SHOWS: Record<string, string> = {
  SQUAT: "Both sides load together: range and timing differences show up as asymmetry.",
  SIT_TO_STAND: "A transfer: how evenly both sides share the rise, rep after rep.",
  STEP_UP: "One side at a time: each limb's range and control, set by set.",
  WALK: "Alternating gait cycles: stride-to-stride consistency and left/right balance.",
  KNEE_EXTENSION: "Seated, one side at a time: range under control on each side.",
  SINGLE_LEG_BALANCE: "A static hold: sway rather than repetitions.",
};

/** Per-exercise aggregates over every hardware-v2 session the account may see. */
export function ExerciseAnalyticsView() {
  const c = useChartColors();
  const { data, error, loading, reload } = useApi(movementApi.exercises, []);
  if (loading && !data) return <Loading what="exercise analytics" />;
  if (error || !data) return <Failure error={error ?? "No data."} retry={reload} />;
  const synthetic = data.labels.provenance != null;
  const total = data.items.reduce((sum, e) => sum + e.sessions, 0);
  return (
    <>
      <WorkspaceHeader
        eyebrow="EXERCISE ANALYTICS"
        title="Every exercise, and what it revealed."
        lede="Repetitions, movement quality and asymmetry per prescribed exercise, from stored sessions. The trend is each record's own session-to-session change, averaged."
        stats={[
          { label: "EXERCISES", value: String(data.items.length) },
          { label: "SESSIONS", value: String(total), tone: "violet" },
          { label: "SOURCE", value: synthetic ? "Synthetic demo" : "Recorded", tone: synthetic ? "violet" : "teal" },
        ]}
      />
      <ResearchNote synthetic={synthetic} />
      <div className="mv-exercises">
        {data.items.map((e) => (
          <Panel key={e.exercise_type} eyebrow={`${e.sessions} SESSIONS · ${e.patients} RECORD${e.patients === 1 ? "" : "S"}`}
            title={exerciseLabel(e.exercise_type)}
            actions={<TrendTag trend={e.trend} label={`${e.trend} (${signed(e.mqi_slope_per_session, 2)}/session)`} />}>
            <p className="mv-ex-copy">{WHAT_IT_SHOWS[e.exercise_type] ?? ""}</p>
            <dl className="mv-facts mv-ex-facts">
              <div><dt>Avg repetitions</dt><dd>{num(e.average_repetitions, 0)}</dd></div>
              <div><dt>Avg MQI</dt><dd>{num(e.average_mqi)}</dd></div>
              <div><dt>Avg asymmetry</dt><dd>{num(e.average_asymmetry_pct, 1, "%")}</dd></div>
              <div><dt>Avg duration</dt><dd>{clock(e.average_duration_s)}</dd></div>
              <div><dt>Rep / cycle time</dt><dd>{num(e.average_rep_duration_s, 2, " s")}</dd></div>
            </dl>
            <div className="mv-ex-spark">
              <span className="mono">MQI BY SESSION</span>
              <Sparkline values={e.series.map((s) => s.mqi)} color={c.teal} width={260} height={40} domain={[50, 100]} />
            </div>
            <span className="eyebrow">WHAT THE ACTIVITY MODEL CALLS IT</span>
            <DistributionBars seconds={e.model_activity_seconds} top={3} />
            <p className="fine-print mv-gap">Performed by: {e.patient_names.join(", ")}</p>
          </Panel>
        ))}
      </div>
      <p className="fine-print">
        {data.note} The activity model was trained on public datasets with no rehabilitation exercises; its
        labels here are model output, not a check of the exercise performed.
      </p>
    </>
  );
}
