"use client";

import { ResearchView } from "@/components/movement/ResearchView";
import { useWorkspace } from "@/components/workspace/WorkspaceShell";
import { Failure } from "@/components/movement/Bits";

export default function ResearchPage() {
  const { canSwitch } = useWorkspace();
  // The research endpoint is clinician/admin only; say so instead of erroring.
  if (!canSwitch) return <Failure error="Research analytics are available to clinician and admin accounts." />;
  return <ResearchView />;
}
