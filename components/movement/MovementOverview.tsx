"use client";

import Link from "next/link";
import { ArrowUpRight, FlaskConical } from "lucide-react";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { movementApi, useApi, type Overview } from "@/lib/api/movement";
import { compact, dateTime, exerciseLabel, activityLabel, num, parseTime, signed } from "@/lib/movement-format";
import { Failure, Kpi, KpiGrid, Loading, Panel, StatusChip } from "./Bits";
import { Sparkline, TrendChart, useChartColors } from "./Charts";
import { PROVENANCE_BADGE, ProvenanceBadge, ResearchNote } from "./Provenance";

const PROVENANCE_COLOR: Record<string, string> = {
  SYNTHETIC_DEMONSTRATION: "var(--violet)",
  PUBLIC_DATASET_REPLAY: "var(--blue)",
  SIMULATED: "var(--cyan)",
  PHYSICAL_REGISTERED: "var(--teal)",
  PHYSICAL_UNVERIFIED: "var(--amber)",
};

/** Cohort dashboard: every figure comes from GET /analytics/overview. */
export function MovementOverview() {
  const { data, error, loading, reload } = useApi(movementApi.overview, []);
  if (loading && !data) return <Loading what="the cohort overview" />;
  if (error || !data) return <Failure error={error ?? "No data."} retry={reload} />;
  return <OverviewBody data={data} />;
}

function OverviewBody({ data }: { data: Overview }) {
  const c = useChartColors();
  const k = data.kpis;
  const trend = data.weekly_trend.map((w) => ({
    x: parseTime(`${w.week}T00:00:00Z`)?.getTime() ?? 0,
    mqi: w.mean_mqi,
    asym: w.mean_asymmetry_pct,
  }));
  const provTotal = Object.values(data.provenance.sessions).reduce((a, b) => a + b, 0) || 1;

  return (
    <>
      <WorkspaceHeader
        eyebrow={data.synthetic ? "SYNTHETIC DEMONSTRATION · OVERVIEW" : "RESEARCH WORKSPACE · OVERVIEW"}
        title="Every record, at a glance."
        lede="Movement quality, asymmetry and activity across the records you can see — each figure read from stored pipeline output, recomputed nowhere."
        stats={[
          { label: "RECORDS", value: String(k.patients) },
          { label: "SESSIONS", value: String(k.total_sessions), tone: "violet" },
          { label: "AVERAGE MQI", value: num(k.average_mqi), tone: "teal" },
          { label: "NEEDS ATTENTION", value: String(k.needs_attention), tone: "amber" },
        ]}
        actions={
          <Link className="button button-small" href="/workspace/research">
            <FlaskConical size={14} aria-hidden="true" />
            Research view
          </Link>
        }
      />
      <ResearchNote synthetic={data.synthetic} />

      <KpiGrid>
        <Kpi label="ACTIVE PATIENTS" value={k.active_patients}
          sub={data.synthetic ? "demonstration records in an ongoing programme" : "in an ongoing programme"} />
        <Kpi label="SESSIONS THIS WEEK" value={k.sessions_this_week} sub="last 7 days" tone="violet" />
        <Kpi label="TOTAL SESSIONS" value={k.total_sessions} sub={`${k.sessions_completed} completed and analysed`} tone="blue" />
        <Kpi label="AVERAGE MOVEMENT QUALITY" value={num(k.average_mqi)} sub="MQI, current per record (research metric)" tone="teal" />
        <Kpi label="AVERAGE ASYMMETRY" value={num(k.average_asymmetry_pct, 1, "%")} sub="current per record · lower = more alike" tone="violet" />
        <Kpi label="IMPROVEMENT TREND" value={signed(k.average_mqi_change)} sub="mean MQI change since each record's start" tone={(k.average_mqi_change ?? 0) >= 0 ? "teal" : "coral"} />
        <Kpi label="STATUS" value={`${k.improving} · ${k.stable} · ${k.needs_attention} · ${k.completed}`}
          sub="improving · stable · attention · completed" tone="amber" />
        <Kpi label="EXERCISES PERFORMED" value={k.exercises_performed}
          sub={Object.keys(data.exercise_counts).map(exerciseLabel).join(", ")} tone="cyan" />
        <Kpi label="MODEL INFERENCES" value={compact(k.model_inferences)} sub="activity-model windows stored" tone="blue" />
        <Kpi label="REPETITIONS" value={compact(k.total_repetitions)} sub="detected across both sides" tone="muted" />
      </KpiGrid>

      <div className="mv-grid-2">
        <Panel eyebrow="COHORT TREND" title="Weekly mean movement quality and asymmetry"
          footer="Each point is the mean of every session recorded that week, across records.">
          <TrendChart data={trend} height={240} domain={[0, 100]}
            series={[{ key: "mqi", label: "Mean MQI", color: c.teal }, { key: "asym", label: "Mean asymmetry %", color: c.violet }]} />
        </Panel>
        <Panel eyebrow="NEEDS ATTENTION" title={data.needs_attention.length ? `${data.needs_attention.length} record${data.needs_attention.length > 1 ? "s" : ""}` : "Nothing flagged"}
          footer={`Rule: ${data.status_rule.NEEDS_ATTENTION}. ${data.status_rule.basis}.`}>
          {data.needs_attention.length === 0 ? (
            <p className="mv-empty">No record meets the attention rule.</p>
          ) : (
            <ul className="mv-attention">
              {data.needs_attention.map((a) => (
                <li key={a.patient_id}>
                  <Link href={`/workspace/patients/${a.patient_id}`}>
                    <strong>{a.name}</strong>
                    <span className="mono">MQI {num(a.current_mqi)} · ASYM {num(a.current_asymmetry_pct, 1, "%")}</span>
                  </Link>
                  <ul>
                    {a.reasons.map((r) => <li key={r}>{r}</li>)}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel eyebrow="RECORDS" title="Trajectories"
        actions={<Link className="mv-link" href="/workspace/patients">Command centre <ArrowUpRight size={13} /></Link>}>
        <div className="mv-records">
          {data.patients.map((p) => (
            <Link key={p.id} href={`/workspace/patients/${p.id}`} className="mv-record">
              <span className="mv-record-top">
                <strong>{p.name}</strong>
                <ProvenanceBadge value={p.provenance} compact />
              </span>
              <span className="fine-print">{p.program ?? "No programme set"}{p.program_days ? ` · ${p.program_days} days` : ""}</span>
              <Sparkline values={p.series} width={180} height={34}
                color={p.status === "NEEDS_ATTENTION" ? c.amber : p.status === "IMPROVING" ? c.teal : c.blue} />
              <span className="mv-record-foot">
                <StatusChip status={p.status} />
                <span className="mono">MQI {num(p.current_mqi)} ({signed(p.mqi_change)})</span>
              </span>
            </Link>
          ))}
        </div>
      </Panel>

      <div className="mv-grid-2">
        <Panel eyebrow="RECENT SESSIONS" title="Latest recordings"
          actions={<Link className="mv-link" href="/workspace/sessions">All sessions <ArrowUpRight size={13} /></Link>}>
          <div className="mv-table-wrap">
            <table className="mv-table">
              <thead>
                <tr><th>When</th><th>Record</th><th>Exercise</th><th className="num">MQI</th><th className="num">Asym.</th><th>Activity (model)</th></tr>
              </thead>
              <tbody>
                {data.recent_sessions.map((s) => (
                  <tr key={s.id}>
                    <td><Link href={`/workspace/sessions/${s.id}`}>{dateTime(s.started_at)}</Link></td>
                    <td>{s.patient_name}</td>
                    <td>{exerciseLabel(s.exercise_type)}</td>
                    <td className="num">{num(s.mqi)}</td>
                    <td className="num">{num(s.asymmetry_pct, 1, "%")}</td>
                    <td>{activityLabel(s.activity_top)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel eyebrow="DATA PROVENANCE" title={`${data.provenance.all_sessions} sessions by source`}
          footer="Only PHYSICAL_REGISTERED data from an authenticated RehabSense device counts as hardware evidence.">
          <ul className="mv-bars">
            {Object.entries(data.provenance.sessions).map(([p, n]) => (
              <li key={p}>
                <span className="mv-bars-label"><ProvenanceBadge value={p} compact /></span>
                <span className="mv-bars-track" aria-hidden="true"><i style={{ width: `${(100 * n) / provTotal}%`, background: PROVENANCE_COLOR[p] }} /></span>
                <span className="mv-bars-value mono">{n}</span>
              </li>
            ))}
            {!Object.keys(data.provenance.sessions).length && <li className="mv-empty">No sessions.</li>}
          </ul>
          <p className="fine-print mv-gap">
            {Object.entries(data.provenance.records).map(([p, n]) =>
              `${n} ${p === "REAL_RECORD" ? "recorded" : (PROVENANCE_BADGE[p]?.label ?? p).toLowerCase()} record${n > 1 ? "s" : ""}`).join(" · ")}
          </p>
        </Panel>
      </div>
    </>
  );
}
