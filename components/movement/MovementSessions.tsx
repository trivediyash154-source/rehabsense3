"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { movementApi, useApi } from "@/lib/api/movement";
import { activityLabel, clock, dateTime, exerciseLabel, num } from "@/lib/movement-format";
import { Failure, Loading, Panel } from "./Bits";
import { PROVENANCE_BADGE, ProvenanceBadge, ResearchNote } from "./Provenance";

/** Every completed hardware-v2 session the account may see. */
export function MovementSessions() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi(() => movementApi.sessions(), []);
  const [record, setRecord] = useState("all");
  const [exercise, setExercise] = useState("all");
  const [source, setSource] = useState("all");

  const rows = useMemo(() => data?.items ?? [], [data]);
  const records = useMemo(
    () => Array.from(new Map(rows.map((r) => [String(r.patient_id), r.patient_name ?? `Record ${r.patient_id}`])).entries()),
    [rows],
  );
  const exercises = useMemo(() => Array.from(new Set(rows.map((r) => r.exercise_type))), [rows]);
  const sources = useMemo(() => Array.from(new Set(rows.map((r) => r.provenance))), [rows]);
  const shown = rows.filter((r) =>
    (record === "all" || String(r.patient_id) === record) &&
    (exercise === "all" || r.exercise_type === exercise) &&
    (source === "all" || r.provenance === source));

  if (loading && !data) return <Loading what="sessions" />;
  if (error || !data) return <Failure error={error ?? "No data."} retry={reload} />;
  const synthetic = rows.some((r) => r.provenance === "SYNTHETIC_DEMONSTRATION");

  return (
    <>
      <WorkspaceHeader
        eyebrow="SESSIONS · PROTOCOL v2"
        title="Every session, and what the pipeline measured."
        lede="Open a session to replay its stored movement trace, repetitions and model output side by side."
        stats={[
          { label: "SESSIONS", value: String(rows.length) },
          { label: "SHOWN", value: String(shown.length), tone: "violet" },
          { label: "RECORDS", value: String(records.length), tone: "teal" },
        ]}
      />
      <ResearchNote synthetic={synthetic} />
      <Panel
        eyebrow="FILTER"
        title={`${shown.length} session${shown.length === 1 ? "" : "s"}`}
        actions={
          <div className="mv-filters">
            <label>
              <span className="mono">RECORD</span>
              <select value={record} onChange={(e) => setRecord(e.target.value)}>
                <option value="all">All records</option>
                {records.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              </select>
            </label>
            <label>
              <span className="mono">EXERCISE</span>
              <select value={exercise} onChange={(e) => setExercise(e.target.value)}>
                <option value="all">All</option>
                {exercises.map((x) => <option key={x} value={x}>{exerciseLabel(x)}</option>)}
              </select>
            </label>
            <label>
              <span className="mono">SOURCE</span>
              <select value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="all">All</option>
                {sources.map((x) => <option key={x} value={x}>{PROVENANCE_BADGE[x]?.label ?? x}</option>)}
              </select>
            </label>
          </div>
        }
      >
        <div className="mv-table-wrap">
          <table className="mv-table">
            <thead>
              <tr>
                <th>Date</th><th>Record</th><th>Exercise</th><th className="num">Duration</th>
                <th className="num">Reps L / R</th><th>Activity (model)</th><th className="num">MQI</th>
                <th className="num">Range L / R</th><th className="num">Asymmetry</th><th>Source</th><th>Model</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} className="is-link" onClick={() => router.push(`/workspace/sessions/${r.id}`)}>
                  <td><Link href={`/workspace/sessions/${r.id}`}>{dateTime(r.started_at)}</Link></td>
                  <td>{r.patient_name}</td>
                  <td>{exerciseLabel(r.exercise_type)}</td>
                  <td className="num">{clock(r.duration_s)}</td>
                  <td className="num">{r.reps_left ?? "—"} / {r.reps_right ?? "—"}</td>
                  <td>{activityLabel(r.activity_top)}</td>
                  <td className="num">{num(r.mqi)}</td>
                  <td className="num">{num(r.rom_left_deg, 0, "°")} / {num(r.rom_right_deg, 0, "°")}</td>
                  <td className="num">{num(r.asymmetry_pct, 1, "%")}</td>
                  <td><ProvenanceBadge value={r.provenance} compact /></td>
                  <td className="mono mv-small">{r.model ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="fine-print mv-gap">
          Range is the mean segment-tilt range per repetition from each shank IMU (a proxy, not a joint angle).
        </p>
      </Panel>
    </>
  );
}
