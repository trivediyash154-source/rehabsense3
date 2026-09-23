"use client";

import { useState } from "react";
import { AlertCircle, Sparkles, Gauge, Check } from "lucide-react";
import { patients as demoRoster, type PatientRow } from "@/lib/demo-data";
import { toPatientRow, useRoster } from "@/lib/api/useRoster";
import { useData } from "@/lib/api/DataProvider";

const attentionMeta = {
  review: { label: "Review recommended", icon: AlertCircle, tone: "amber" },
  new: { label: "New session", icon: Sparkles, tone: "cyan" },
  confidence: { label: "Confidence reduced", icon: Gauge, tone: "coral" },
  steady: { label: "No action needed", icon: Check, tone: "teal" },
} as const;

/**
 * CLINICIAN COMMAND CENTER
 *
 * Prioritised by what needs attention rather than alphabetically. Each
 * patient is a compact movement object — a sparkline of their indicator plus
 * an attention state — not a card of fields. The queue is derived from the
 * data, and every reason is a stated observation, never a recommendation.
 */
export function CommandCenter() {
  const { authenticated, patient: activePatient, selectPatient } = useData();
  const { rows } = useRoster(authenticated);

  // Real records when the account has any; otherwise the labelled demo roster.
  const patients = rows && rows.length > 0 ? rows.map(toPatientRow) : demoRoster;
  const isReal = Boolean(rows && rows.length > 0);

  // The selected record is the workspace's record: choosing one here moves
  // every other page onto it, rather than only changing this panel.
  const selectedId = activePatient ? String(activePatient.id) : null;
  const selected =
    patients.find((p) => p.id === selectedId) ?? patients[0] ?? demoRoster[0];
  const setSelected = (row: PatientRow) => {
    const id = Number(row.id);
    if (Number.isFinite(id)) selectPatient(id);
  };
  const [filter, setFilter] = useState<"all" | "attention">("attention");

  const queue = patients.filter((p) => p.attention !== "steady");
  const shown = filter === "attention" ? queue : patients;

  return (
    <div className="command">
      <section className="cmd-queue">
        <header>
          <div>
            <span className="eyebrow">ATTENTION QUEUE</span>
            <h3>{queue.length} of {patients.length} records flagged for review.</h3>
          </div>
          <div className="segmented" role="group" aria-label="Filter records">
            <button type="button" aria-pressed={filter === "attention"} onClick={() => setFilter("attention")}>
              Needs review
            </button>
            <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
              All records
            </button>
          </div>
        </header>

        <ol className="cmd-list">
          {shown.map((p) => {
            const meta = attentionMeta[p.attention];
            const Icon = meta.icon;
            const active = selected.id === p.id;
            return (
              <li key={p.id}>
                <button type="button" className={active ? "is-active" : ""} aria-pressed={active} onClick={() => setSelected(p)}>
                  <span className="cmd-initials">{p.initials}</span>
                  <span className="cmd-identity">
                    <strong>{p.alias}</strong>
                    <small>
                      {p.operatedLeg === "LEFT" ? "Left" : "Right"} limb
                      {p.weeksPost > 0 ? ` · week ${p.weeksPost}` : ""} · {p.sessions}{" "}
                      {p.sessions === 1 ? "session" : "sessions"}
                    </small>
                  </span>
                  <Spark trend={p.trend} />
                  <span className={`cmd-flag tone-${meta.tone}`}>
                    <Icon size={12} aria-hidden="true" />
                    {meta.label}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        {/* Recent movement across the roster — the queue answers "who", this
            answers "what has been happening at all". */}
        <div className="cmd-recent">
          <span className="eyebrow">RECENT MOVEMENT</span>
          <div className="cmd-recent-track">
            {patients.map((p) => (
              <div key={p.id} className="cmd-recent-row">
                <span className="cmd-recent-name">{p.alias}</span>
                <div className="cmd-recent-cells">
                  {p.trend.slice(-10).map((v, i) => (
                    <span
                      key={i}
                      className="cmd-recent-cell"
                      style={{ "--v": (v - 50) / 45 } as React.CSSProperties}
                      title={`Session indicator ${v}`}
                    />
                  ))}
                </div>
                <span className="cmd-recent-latest">{p.score}</span>
              </div>
            ))}
          </div>
          <p className="fine-print">
            {isReal
            ? "Recorded recovery indicators per record, oldest to newest, from completed sessions."
            : "Last ten indicators per record, oldest to newest. Illustrative values."}
          </p>
        </div>
      </section>

      <aside className="cmd-detail">
        <span className="eyebrow">RECORD DETAIL</span>
        <div className="cmd-detail-head">
          <span className="cmd-initials is-large">{selected.initials}</span>
          <div>
            <h3>{selected.alias}</h3>
            <p className="mono">
              {selected.operatedLeg} LIMB
              {selected.weeksPost > 0 ? ` · WEEK ${selected.weeksPost}` : ""} ·{" "}
              {selected.sessions} {selected.sessions === 1 ? "SESSION" : "SESSIONS"}
            </p>
          </div>
        </div>

        <div className="cmd-metric">
          <span className="mono">LATEST INDICATOR</span>
          <strong>{selected.score}<small>/100</small></strong>
          <Spark trend={selected.trend} large />
        </div>

        <div className="cmd-observed">
          <span className="eyebrow">OBSERVED</span>
          <p>{selected.reason}</p>
        </div>

        <div className="cmd-actions">
          <span className="eyebrow">AVAILABLE IN THIS PROTOTYPE</span>
          <ul>
            <li className="is-ready">Open the recorded sessions for this record</li>
            <li className="is-ready">Generate a recovery receipt</li>
            <li className="is-future">Clinician annotations <em>future</em></li>
            <li className="is-future">Exercise prescription <em>future</em></li>
            <li className="is-future">Shared report history <em>future</em></li>
          </ul>
          <p className="fine-print">
            Items marked future are placeholders for planned capability. They are not connected
            and perform no action.
          </p>
        </div>

        <p className="fine-print">
          {isReal
            ? "Records assigned to this clinician account. Ordering reflects what changed in the recorded data — it is not a clinical prioritisation."
            : "Demo roster. No real patients, no identifying information, and no clinical prioritisation — the ordering reflects illustrative data only."}
        </p>
      </aside>
    </div>
  );
}

function Spark({ trend, large = false }: { trend: number[]; large?: boolean }) {
  const w = large ? 200 : 92;
  const h = large ? 48 : 26;

  // A record can legitimately have one session, or several identical scores.
  // Both make the naive denominators zero, which renders as cx="NaN" and an
  // SVG the browser refuses to draw.
  if (trend.length === 0) return <svg className="cmd-spark" aria-hidden="true" />;

  const min = Math.min(...trend) - 4;
  const max = Math.max(...trend) + 4;
  const range = max - min || 1;
  const span = Math.max(1, trend.length - 1);
  const y = (v: number) => h - ((v - min) / range) * h;
  // A single point sits at the right edge, where the marker already is.
  const x = (i: number) => (trend.length === 1 ? w : (i / span) * w);

  const d = trend.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)} ${y(v)}`).join(" ");
  return (
    <svg className={`cmd-spark ${large ? "is-large" : ""}`} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={d} />
      <circle cx={w} cy={y(trend[trend.length - 1])} r={large ? 3.4 : 2.4} />
    </svg>
  );
}
