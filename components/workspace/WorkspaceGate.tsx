"use client";

import { usePathname } from "next/navigation";
import { DataState } from "./DataState";
import { useData } from "@/lib/api/DataProvider";

/**
 * Routes that stand on their own without a recorded session.
 *
 * The live lab is where a first session gets started, so it must remain
 * reachable from an empty account; devices and settings describe the system
 * rather than a patient's history.
 */
const ALWAYS_AVAILABLE = [
  "/workspace/live",
  "/workspace/devices",
  "/workspace/settings",
  // Focus is where a first target gets set, so it must work on a brand-new
  // account with no history at all.
  "/workspace/focus",
];

export function WorkspaceGate({ children }: { children: React.ReactNode }) {
  const { mode, sessions } = useData();
  const pathname = usePathname();

  const hasData = (mode === "live" || mode === "illustrative") && sessions.length > 0;
  if (hasData) return <>{children}</>;

  // These routes are still useful with no history, but only once we know the
  // API is actually there.
  const standalone = ALWAYS_AVAILABLE.some((p) => pathname.startsWith(p));
  if (standalone && (mode === "empty" || mode === "live")) return <>{children}</>;

  return <DataState />;
}
