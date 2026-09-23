"use client";

import { useState } from "react";
import { Download, FileText, LoaderCircle } from "lucide-react";
import { WorkspaceHeader, useWorkspace } from "@/components/workspace/WorkspaceShell";
import { MovementPassport } from "@/components/workspace/MovementPassport";
import { ComparisonReceipt } from "@/components/dashboard/ComparisonReceipt";
import { exerciseLabels } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { downloadFile } from "@/lib/api/download";

export default function ReportsPage() {
  const { sessions, mode, patient } = useData();
  const { session, setSession } = useWorkspace();
  const [receipt, setReceipt] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const recorded = mode === "live";

  async function exportCsv() {
    setExporting(true);
    setExportError(null);
    try {
      await downloadFile(
        `/sessions/${session.id}/report.csv`,
        `rehabsense-session-${session.id}.csv`,
      );
    } catch (error) {
      // Inline failure: an export that cannot be produced must not replace
      // the workspace with an error page.
      setExportError(error instanceof Error ? error.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <WorkspaceHeader
        eyebrow="ARTIFACTS"
        title="Two documents, two timescales."
        lede="The receipt records one session against its baseline. The passport records the whole period."
        stats={[
          { label: "SESSION RECORDS", value: String(sessions.length) },
          { label: "SELECTED", value: session.label, tone: "violet" },
        ]}
        actions={
          <button type="button" className="button button-small" onClick={() => setReceipt(true)}>
            <FileText size={14} aria-hidden="true" />
            Open recovery receipt
          </button>
        }
      />

      <section className="rp-picker">
        <span className="eyebrow">RECEIPT FOR SESSION</span>
        <div className="rp-picker-row">
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              className={s.id === session.id ? "is-active" : ""}
              aria-pressed={s.id === session.id}
              onClick={() => setSession(s)}
            >
              <strong>{s.label}</strong>
              <small>{s.dayLabel} · {exerciseLabels[s.exercise]}</small>
              <span className="mono">{s.score}/100</span>
            </button>
          ))}
        </div>
        <div className="rp-actions">
          <button type="button" className="button button-outline button-small" onClick={() => setReceipt(true)}>
            Generate receipt for {session.label}
          </button>
          <button
            type="button"
            className="button button-outline button-small"
            onClick={() => void exportCsv()}
            disabled={!recorded || exporting}
            title={
              recorded
                ? "Download the recorded values for this session as CSV"
                : "Recorded sessions only — illustrative data is not exported"
            }
          >
            {exporting ? (
              <LoaderCircle className="spin" size={14} aria-hidden="true" />
            ) : (
              <Download size={14} aria-hidden="true" />
            )}
            {exporting ? "Preparing…" : "Download CSV"}
          </button>
        </div>
        {exportError && (
          <p className="fine-print rp-export-error" role="alert">
            {exportError}
          </p>
        )}
      </section>

      <MovementPassport />

      <ComparisonReceipt
        patientId={patient?.id ?? null}
        patientName={patient?.name ?? null}
        sessions={sessions}
        currentSessionId={session.id}
        open={receipt}
        onClose={() => setReceipt(false)}
      />
    </>
  );
}
