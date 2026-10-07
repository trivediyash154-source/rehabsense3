"use client";

import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { DeviceExplorer } from "@/components/workspace/DeviceExplorer";
import { SensorConstellation } from "@/components/workspace/SensorConstellation";
import { DeviceProvenanceView } from "@/components/movement/DeviceProvenanceView";
import { useData } from "@/lib/api/DataProvider";

export default function DevicesPage() {
  const { session } = useWorkspace();
  const { sessions, authenticated } = useData();
  return (
    <>
      <WorkspaceHeader
        eyebrow="DEVICE EXPLORER"
        title="The assembly, and the path its signal takes."
        lede="A conceptual sensing node: rotate it, separate the layers, and select a component to see its role in the chain."
        stats={[
          { label: "NODES", value: "2 · one per limb" },
          { label: "IMUS PER NODE", value: "2", tone: "violet" },
          { label: "HARDWARE", value: "Conceptual", tone: "amber" },
        ]}
      />
      {authenticated && <DeviceProvenanceView />}
      <DeviceExplorer />

      <section className="dv-future">
        <span className="eyebrow">FUTURE DEVICE CAPABILITIES</span>
        <ul>
          <li>Battery health per node <em>future</em></li>
          <li>Firmware version and update <em>future</em></li>
          <li>Calibration centre <em>future</em></li>
          <li>Per-sensor diagnostics <em>future</em></li>
        </ul>
        <p className="fine-print">
          Placeholders for planned capability. No hardware is connected and none of these
          perform an action.
        </p>
      </section>

      {/* Drawn from a recorded knee-angle session; never from a placeholder. */}
      {sessions.length > 0 && <SensorConstellation session={session} />}
    </>
  );
}
