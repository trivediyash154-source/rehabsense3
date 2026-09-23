"use client";

import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { LiveLab } from "@/components/workspace/LiveLab";

import { exerciseLabels } from "@/lib/demo-data";

export default function LivePage() {
  const { session } = useWorkspace();
  return (
    <>
      <WorkspaceHeader
        eyebrow="BIOMECHANICS LAB"
        title="Watch the pipeline run."
        lede="A simulated stream drives limb angles, repetition detection, symmetry and cadence — the same chain a connected sensor would."
        stats={[
          { label: "EXERCISE", value: exerciseLabels[session.exercise] },
          { label: "NODES", value: "2 simulated", tone: "violet" },
          { label: "STREAM", value: "Not connected", tone: "amber" },
        ]}
      />
      <LiveLab session={session} />

    </>
  );
}
