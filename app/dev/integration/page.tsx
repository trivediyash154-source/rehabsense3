import { notFound } from "next/navigation";
import { IntegrationReport } from "@/components/dev/IntegrationReport";

/**
 * Development-only integration diagnostics (§50).
 *
 * Returns 404 in a production build so it never becomes a public surface: it
 * names internal endpoints and reports which subsystems are reachable.
 */
export const dynamic = "force-dynamic";

export const metadata = {
  title: "Integration status",
  robots: { index: false, follow: false },
};

export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <IntegrationReport />;
}
