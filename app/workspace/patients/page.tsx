"use client";

import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { CommandCenter } from "@/components/workspace/CommandCenter";
import { useData } from "@/lib/api/DataProvider";
import { useRoster } from "@/lib/api/useRoster";
import { patients as demoRoster } from "@/lib/demo-data";

export default function PatientsPage() {
  const { authenticated } = useData();
  const { rows, loading } = useRoster(authenticated);

  const real = rows && rows.length > 0;
  const roster = real ? rows : null;
  const total = roster ? roster.length : demoRoster.length;
  const flagged = roster
    ? roster.filter((p) => p.attention !== "steady").length
    : demoRoster.filter((p) => p.attention !== "steady").length;

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
            value: real ? "Assigned to you" : "Demo only",
            tone: real ? "teal" : "violet",
          },
        ]}
      />
      <CommandCenter />
    </>
  );
}
