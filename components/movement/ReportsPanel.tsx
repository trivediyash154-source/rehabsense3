"use client";

import { useState } from "react";
import { Download, ExternalLink, FileText, LoaderCircle, Plus } from "lucide-react";
import { downloadFile } from "@/lib/api/download";
import { movementApi, openPdf, useApi, type ReportItem } from "@/lib/api/movement";
import { dateTime, STATUS_LABEL } from "@/lib/movement-format";
import { Failure, Loading, Panel } from "./Bits";
import { ProvenanceBadge } from "./Provenance";

function slug(name: string | null | undefined) {
  return (name ?? "record").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "record";
}

export function ReportRow({ r }: { r: ReportItem }) {
  const [busy, setBusy] = useState<"open" | "save" | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  async function run(kind: "open" | "save") {
    setBusy(kind);
    setFailure(null);
    try {
      if (kind === "open") await openPdf(r.id);
      else await downloadFile(`/reports/${r.id}/pdf`, `rehabsense-movement-report-${r.id}-${slug(r.patient_name)}.pdf`);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "The PDF could not be produced.");
    } finally {
      setBusy(null);
    }
  }
  return (
    <li className="mv-report">
      <FileText size={18} aria-hidden="true" />
      <div className="mv-report-copy">
        <strong>{r.title ?? (r.kind === "MOVEMENT_PROGRESS" ? "Movement progress report" : r.kind.replace(/_/g, " ").toLowerCase())}</strong>
        <span className="fine-print">
          {r.patient_name ?? `Record ${r.patient_id}`} · report {r.id} · generated {dateTime(r.generated_at)}
          {r.sessions != null ? ` · ${r.sessions} sessions` : ""}
          {r.period_days ? ` over ${r.period_days} days` : ""}
          {r.status_label ? ` · ${STATUS_LABEL[r.status_label] ?? r.status_label}` : ""}
        </span>
        {failure && <span className="fine-print mv-error">{failure}</span>}
      </div>
      <ProvenanceBadge value={r.provenance} compact />
      {r.pdf ? (
        <div className="mv-report-actions">
          <button type="button" className="button button-outline button-small" onClick={() => void run("open")} disabled={busy !== null}>
            {busy === "open" ? <LoaderCircle className="spin" size={13} /> : <ExternalLink size={13} aria-hidden="true" />}
            Open PDF
          </button>
          <button type="button" className="button button-small" onClick={() => void run("save")} disabled={busy !== null}>
            {busy === "save" ? <LoaderCircle className="spin" size={13} /> : <Download size={13} aria-hidden="true" />}
            Download
          </button>
        </div>
      ) : (
        <span className="fine-print">{r.status.toLowerCase()} · no PDF rendering for this kind</span>
      )}
    </li>
  );
}

/** Stored reports for one record (or all), plus generating a new one. */
export function ReportsPanel({ patientId, patientName }: { patientId?: number | null; patientName?: string | null }) {
  const { data, error, loading, reload } = useApi(() => movementApi.reports(patientId ?? null), [patientId]);
  const [generating, setGenerating] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function generate() {
    if (!patientId) return;
    setGenerating(true);
    setNote(null);
    try {
      const created = await movementApi.createReport(patientId);
      await movementApi.generateReport(created.id);
      setNote(`Report ${created.id} generated from the stored sessions.`);
      reload();
    } catch (cause) {
      setNote(cause instanceof Error ? `Could not generate: ${cause.message}` : "Could not generate the report.");
    } finally {
      setGenerating(false);
    }
  }

  const items = (data?.items ?? []).filter((r) => r.kind === "MOVEMENT_PROGRESS" || !patientId);
  return (
    <Panel
      eyebrow="REPORTS"
      title={patientName ? `Reports for ${patientName}` : "Stored reports"}
      actions={patientId ? (
        <button type="button" className="button button-small" onClick={() => void generate()} disabled={generating}>
          {generating ? <LoaderCircle className="spin" size={13} /> : <Plus size={13} aria-hidden="true" />}
          {generating ? "Generating…" : "Generate report"}
        </button>
      ) : undefined}
      footer="Every PDF states its data provenance and carries “RehabSense is a research prototype and not a medical device.” on each page. Reports are frozen snapshots: later sessions need a new report."
    >
      {loading && !data ? <Loading what="reports" /> : error ? <Failure error={error} retry={reload} /> : items.length === 0 ? (
        <p className="mv-empty">No reports yet{patientId ? " — generate one from the stored sessions." : "."}</p>
      ) : (
        <ul className="mv-reports">
          {items.map((r) => <ReportRow key={r.id} r={r} />)}
        </ul>
      )}
      {note && <p className="fine-print mv-gap" aria-live="polite">{note}</p>}
    </Panel>
  );
}
