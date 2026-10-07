"use client";

import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { ExerciseStudio } from "@/components/workspace/ExerciseStudio";
import { exercises } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { ExerciseAnalyticsView } from "@/components/movement/ExerciseAnalyticsView";

export default function ExercisesPage() {
  const { hasMovement } = useData();
  return hasMovement ? <ExerciseAnalyticsView /> : <ExerciseLibrary />;
}

function ExerciseLibrary() {
  const { sessions } = useData();
  const recorded = new Set(sessions.map((s) => s.exercise)).size;
  return (
    <>
      <WorkspaceHeader
        eyebrow="EXERCISE STUDIO"
        title="Every movement, and what it reveals."
        lede="Each exercise surfaces something different: bilateral timing, single-limb loading, range under control, or steadiness."
        stats={[
          { label: "IN LIBRARY", value: String(exercises.length) },
          { label: "RECORDED HERE", value: `${recorded} types`, tone: "teal" },
          { label: "PRESCRIPTION", value: "Not connected", tone: "amber" },
        ]}
      />
      <ExerciseStudio />
    </>
  );
}
