import type { Metadata } from "next";
import { WorkspaceProvider, WorkspaceShell } from "@/components/workspace/WorkspaceShell";
import { WorkspaceGate } from "@/components/workspace/WorkspaceGate";
import { DataProvider } from "@/lib/api/DataProvider";
import { LiveSessionProvider } from "@/components/workspace/LiveSessionProvider";

export const metadata: Metadata = {
  title: { default: "Workspace", template: "%s · RehabSense Workspace" },
  description:
    "RehabSense workspace. Recorded values are estimated decision-support indicators, not clinical measurements.",
  robots: { index: false, follow: false },
};

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <DataProvider>
      <LiveSessionProvider>
        <WorkspaceProvider>
        <WorkspaceShell>
          {/* Pages render only when there is data behind them. Without this,
              a failed request would leave every visualisation drawing from
              whatever it could still reach. */}
          <WorkspaceGate>{children}</WorkspaceGate>
          </WorkspaceShell>
        </WorkspaceProvider>
      </LiveSessionProvider>
    </DataProvider>
  );
}
