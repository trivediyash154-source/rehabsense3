"use client";

import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { HardwareLab } from "@/components/hardware/HardwareLab";

export default function HardwarePage() {
  return (
    <>
      <WorkspaceHeader
        eyebrow="HARDWARE LAB · PROTOCOL v2"
        title="One device, two sides, one clock."
        lede="An ESP32 with a left and a right MPU6050 and force sensors streams through calibration, stream checks and analysis. Every panel says when it has nothing trustworthy to show."
        stats={[
          { label: "IMUS", value: "2 · left + right" },
          { label: "FORCE", value: "Configurable", tone: "violet" },
          { label: "VALIDATION", value: "Not validated", tone: "amber" },
        ]}
      />
      <HardwareLab />
    </>
  );
}
