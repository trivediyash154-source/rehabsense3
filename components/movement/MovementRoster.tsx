"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import type { Roster, RosterEntry } from "@/lib/api/movement";
import { activityLabel, longDate, num, relativeDay, signed } from "@/lib/movement-format";
import { Panel, StatusChip, TrendTag } from "./Bits";
import { Sparkline, useChartColors } from "./Charts";
import { ProvenanceBadge, ResearchNote } from "./Provenance";

function Row({ p, onOpen }: { p: RosterEntry; onOpen: () => void }) {
  const c = useChartColors();
  return (
    <tr className="is-link" onClick={onOpen}>
      <td>
        <Link href={`/workspace/patients/${p.id}`} className="mv-name">{p.name}</Link>
        <ProvenanceBadge value={p.provenance} compact />
      </td>
      <td className="num">{p.age ?? "—"}</td>
      <td className="mv-programme">{p.program ?? "—"}{p.program_days ? <small> · {p.program_days} d</small> : null}</td>
      <td className="num">{p.sessions_completed}</td>
      <td>{p.last_session_at ? <>{longDate(p.last_session_at)}<small> · {relativeDay(p.last_session_at)}</small></> : "—"}</td>
      <td className="num">{num(p.current_mqi)} <small>({signed(p.mqi_change)})</small></td>
      <td title={`Movement quality ${p.mqi_trend}`}>
        <span className="mv-trend-cell">
          <Sparkline values={p.series.map((s) => s.mqi)} color={p.status === "NEEDS_ATTENTION" ? c.amber : c.teal} width={72} />
          <TrendTag trend={p.mqi_trend} label="" />
        </span>
      </td>
      <td title={`Asymmetry ${p.asymmetry_trend} (lower = more alike)`}>
        <span className="mv-trend-cell">
          <Sparkline values={p.series.map((s) => s.asymmetry_pct)} color={c.violet} width={72} />
          <TrendTag trend={p.asymmetry_trend} label={num(p.current_asymmetry_pct, 1, "%")} />
        </span>
      </td>
      <td title={p.status_reasons.join("; ")}><StatusChip status={p.status} /></td>
      <td>{activityLabel(p.last_activity)}</td>
    </tr>
  );
}

/** The clinician command centre for hardware-v2 records. */
export function MovementRoster({ roster }: { roster: Roster }) {
  const router = useRouter();
  const flagged = roster.items.filter((p) => p.status === "NEEDS_ATTENTION").length;
  return (
    <>
      <WorkspaceHeader
        eyebrow="CLINICIAN COMMAND CENTRE"
        title="Who needs a look, and why."
        lede="Records ordered by what changed. Status is a stated rule over stored research indicators — an observation, not a clinical instruction."
        stats={[
          { label: "RECORDS", value: String(roster.items.length) },
          { label: "NEEDS ATTENTION", value: String(flagged), tone: "amber" },
          { label: "IMPROVING", value: String(roster.items.filter((p) => p.status === "IMPROVING").length), tone: "teal" },
          { label: "SOURCE", value: roster.synthetic ? "Synthetic demo" : "Recorded", tone: roster.synthetic ? "violet" : "teal" },
        ]}
      />
      <ResearchNote synthetic={roster.synthetic} />
      <Panel eyebrow="RECORDS" title={`${roster.items.length} record${roster.items.length === 1 ? "" : "s"}`}
        footer={`Needs attention when ${roster.status_rule.NEEDS_ATTENTION}. Improving when ${roster.status_rule.IMPROVING}. ${roster.status_rule.basis}.`}>
        <div className="mv-table-wrap">
          <table className="mv-table mv-roster">
            <thead>
              <tr>
                <th>Record</th><th className="num">Age</th><th>Programme</th><th className="num">Sessions</th>
                <th>Last session</th><th className="num">Current MQI</th><th>Quality trend</th>
                <th>Asymmetry trend</th><th>Status</th><th>Last activity (model)</th>
              </tr>
            </thead>
            <tbody>
              {roster.items.map((p) => (
                <Row key={p.id} p={p} onOpen={() => router.push(`/workspace/patients/${p.id}`)} />
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {roster.references.length > 0 && (
        <Panel eyebrow="REFERENCE DATASETS" title="Public recordings replayed through the device pipeline"
          footer="Healthy public volunteers, not patients. Used to check the activity model end to end; never counted as RehabSense hardware or clinical data.">
          <ul className="mv-refs">
            {roster.references.map((r) => (
              <li key={r.id}>
                <Link href={`/workspace/patients/${r.id}`}><strong>{r.name}</strong></Link>
                <ProvenanceBadge value={r.provenance} compact />
                <span className="fine-print">{r.sessions_completed} replayed recordings · {r.program}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}
