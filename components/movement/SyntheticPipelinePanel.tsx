"use client";

import Link from "next/link";
import { Play } from "lucide-react";
import { movementApi, useApi } from "@/lib/api/movement";
import { compact, num } from "@/lib/movement-format";
import { Panel } from "./Bits";

const STAGES = [
  "Generator / replayed recording",
  "/ws/ingest/v2 handshake + provenance",
  "Stream integrity checks",
  "Device calibration",
  "Windowing + features",
  "Activity model",
  "Bilateral asymmetry",
  "Repetitions",
  "Movement Quality Index",
  "PostgreSQL",
];

/**
 * The hardware page's demonstration section: what the stored synthetic data
 * exercised, and a way to replay it -- next to (never instead of) the honest
 * hardware-validation status in the lab below.
 */
export function SyntheticPipelinePanel() {
  const { data } = useApi(movementApi.research, []);
  const latest = useApi(() => movementApi.sessions(), []);
  const firstSynthetic = latest.data?.items.find((s) => s.provenance === "SYNTHETIC_DEMONSTRATION");
  const synth = data?.dataset.sessions_by_provenance?.SYNTHETIC_DEMONSTRATION ?? 0;
  const replay = data?.dataset.sessions_by_provenance?.PUBLIC_DATASET_REPLAY ?? 0;
  const agreement = data?.model.replay_agreement;
  return (
    <Panel
      eyebrow="SYNTHETIC PIPELINE DEMONSTRATION"
      title="The same pathway, without claiming hardware validation"
      actions={
        <Link className="button button-small" href={`/workspace/live?mode=replay${firstSynthetic ? `&session=${firstSynthetic.id}` : ""}`}>
          <Play size={13} aria-hidden="true" /> Launch synthetic replay
        </Link>
      }
      footer="Real RehabSense hardware validated: NO. Synthetic and public-replay sessions never count as hardware evidence; the validation status below is computed from registered-device data only."
    >
      <p className="mv-pipeline-copy">
        This replay exercises the same ingestion, preprocessing and inference pathway without claiming
        physical hardware validation.
      </p>
      <ol className="mv-pipeline">
        {STAGES.map((s) => <li key={s}>{s}</li>)}
      </ol>
      <dl className="mv-facts mv-pipeline-facts">
        <div><dt>Synthetic sessions processed</dt><dd>{data ? synth : "…"}</dd></div>
        <div><dt>Public-dataset replays</dt><dd>{data ? replay : "…"}</dd></div>
        <div><dt>Samples stored</dt><dd>{data ? compact(data.dataset.samples) : "…"}</dd></div>
        <div><dt>Model windows inferred</dt><dd>{data ? compact(data.model.total) : "…"}</dd></div>
        <div><dt>Replay agreement with dataset labels</dt><dd>{agreement?.agreement_pct != null ? `${num(agreement.agreement_pct, 1, "%")} (${agreement.windows_scored} windows, seen in training)` : "—"}</dd></div>
        <div><dt>Physical sessions</dt><dd>{data ? data.dataset.physical_sessions : "…"}</dd></div>
      </dl>
    </Panel>
  );
}
