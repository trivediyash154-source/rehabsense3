"use client";

import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { CommandCenter } from "@/components/workspace/CommandCenter";
import { useData } from "@/lib/api/DataProvider";
import { useRoster } from "@/lib/api/useRoster";
import { patients as demoRoster } from "@/lib/demo-data";
import { movementApi, useApi } from "@/lib/api/movement";
import { MovementRoster } from "@/components/movement/MovementRoster";
import { Loading } from "@/components/movement/Bits";

export default function PatientsPage() {
  const { authenticated, mode } = useData();
  const illustrative = mode === "illustrative";
  const roster = useApi(movementApi.roster, [], authenticated && !illustrative);
  const v2 = roster.data && (roster.data.items.some((p) => p.sessions_completed > 0) || roster.data.references.length > 0);
  if (roster.loading && !roster.data) return <Loading what="records" />;
  return v2 && roster.data ? <MovementRoster roster={roster.data} /> : <KneeAngleRoster />;
}

function KneeAngleRoster() {
  const { authenticated, mode } = useData();
  // The demo roster only in illustrative mode (entered deliberately); a real
  // account with no records shows zero, not invented patients.
  const illustrative = mode === "illustrative";
  const { rows, loading } = useRoster(authenticated && !illustrative);

  const attention = illustrative
    ? demoRoster.map((p) => p.attention)
    : (rows ?? []).map((p) => p.attention);
  const total = attention.length;
  const flagged = attention.filter((a) => a !== "steady").length;
  const rosterLabel = illustrative
    ? "Illustrative"
    : rows
      ? "Assigned to you"
      : loading
        ? "…"
        : "Unavailable";

  return (
    <>
      <WorkspaceHeader
        eyebrow="CLINICIAN COMMAND CENTRE"
        title="Who needs a look, and why."
        lede="Records ordered by what changed rather than alphabetically. Every reason is an observation drawn from the recorded data, not a clinical instruction."
        stats={[
          { label: "RECORDS", value: loading ? "…" : String(total) },
          { label: "FLAGGED", value: loading ? "…" : String(flagged), tone: "amber" },
          {
            label: "ROSTER",
            value: rosterLabel,
            tone: illustrative ? "violet" : rows ? "teal" : "amber",
          },
        ]}
      />
      <CommandCenter />
    </>
  );
}
