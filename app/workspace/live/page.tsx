"use client";

import { Suspense } from "react";
import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { LiveLab } from "@/components/workspace/LiveLab";
import { LiveLabModes } from "@/components/movement/LiveLabModes";
import { Loading } from "@/components/movement/Bits";

export default function LivePage() {
  const { session } = useWorkspace();
  return (
    <>
      <WorkspaceHeader
        eyebrow="LIVE LAB"
        title="Watch the pipeline run."
        lede="Three separate sources, never mixed: a stored synthetic session replayed in real time, a real ESP32 once one connects, or the two-node simulator."
        stats={[
          { label: "SYNTHETIC", value: "Replay of stored output", tone: "violet" },
          { label: "REAL ESP32", value: "Waits for a device", tone: "amber" },
          { label: "HARDWARE VALIDATION", value: "Not validated", tone: "amber" },
        ]}
      />
      <Suspense fallback={<Loading what="the live lab" />}>
        <LiveLabModes legacy={<LiveLab session={session} />} />
      </Suspense>
    </>
  );
}
