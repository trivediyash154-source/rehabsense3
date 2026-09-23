import type { Metadata } from "next";
import { Header, Footer } from "@/components/navigation/Header";
import { Dashboard } from "@/components/dashboard/Dashboard";

export const metadata: Metadata = {
  title: "Demo workspace",
  description: "An illustrative RehabSense workspace. All values shown are invented for the interface.",
  robots: { index: false, follow: false },
};

export default function DashboardPage() {
  return (
    <>
      <Header />
      <main id="main" className="container dashboard-page">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">REHABSENSE / OPEN DEMO</span>
            <h1>
              Your movement.
              <br />
              <em>A clearer perspective.</em>
            </h1>
          </div>
          <p>
            No account required. No patient record connected.
            <br />
            All values are illustrative, not clinical measurements.
          </p>
        </div>
        <Dashboard standalone />
        <p className="section-footnote">
          Estimated decision-support indicators. RehabSense does not replace clinical evaluation.
        </p>
      </main>
      <Footer />
    </>
  );
}
