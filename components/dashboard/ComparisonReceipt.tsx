"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Printer, X, ArrowRight, LoaderCircle, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useComparison, type Delta } from "@/lib/api/useComparison";
import { useSessionDetail } from "@/lib/api/useSessionDetail";
import { exerciseLabels, type ExerciseType, type Session } from "@/lib/demo-data";
import { metric, score as fmtScore } from "@/lib/format";

/**
 * RECOVERY RECEIPT — a comparison document.
 *
 * Two recorded sessions, side by side, with the change between them. Every
 * number is the backend's: the deltas come from `/progress/compare` and the
 * indicator breakdown from the session summary, so this document, the
 * progress page and any export cannot disagree about what changed.
 *
 * Which two sessions get compared is the reader's choice, because "against
 * the baseline" and "against last week" answer different questions.
 */

const ROW_ORDER = ["rom_deg", "symmetry_index_pct", "cadence_spm", "recovery_score"];

/**
 * Join a value to its unit.
 *
 * Symbols sit tight against the number ("64°", "95%"); worded units need the
 * space, or the reader gets "97steps/min".
 */
function withUnit(value: number, unit: string): string {
  const tight = unit === "" || unit === "°" || unit === "%" || unit.startsWith("/");
  return tight ? `${value}${unit}` : `${value} ${unit}`;
}

function DirectionIcon({ direction }: { direction: Delta["direction"] }) {
  if (direction === "up") return <TrendingUp size={13} aria-hidden="true" />;
  if (direction === "down") return <TrendingDown size={13} aria-hidden="true" />;
  return <Minus size={13} aria-hidden="true" />;
}

/** A from → to bar, drawn against the larger of the two values. */
function DeltaBar({ from, to }: { from: number; to: number }) {
  const span = Math.max(Math.abs(from), Math.abs(to), 1);
  return (
    <span className="rc-bars" aria-hidden="true">
      <i className="rc-bar-from" style={{ width: `${(Math.abs(from) / span) * 100}%` }} />
      <i className="rc-bar-to" style={{ width: `${(Math.abs(to) / span) * 100}%` }} />
    </span>
  );
}

export function ComparisonReceipt({
  patientId,
  patientName,
  sessions,
  currentSessionId,
  open,
  onClose,
}: {
  patientId: number | null;
  patientName: string | null;
  sessions: Session[];
  currentSessionId: number | null;
  open: boolean;
  onClose: () => void;
}) {
  const [baselineId, setBaselineId] = useState<number | null>(null);
  const [currentId, setCurrentId] = useState<number | null>(currentSessionId);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  useEffect(() => setCurrentId(currentSessionId), [currentSessionId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const { comparison, loading, error } = useComparison(patientId, baselineId, currentId, open);
  const { scoring } = useSessionDetail(comparison?.current.id ?? null, open);

  if (!open || !mounted) return null;

  const b = comparison?.baseline;
  const c = comparison?.current;

  const body = (
    <div className="rc-scrim" role="dialog" aria-modal="true" aria-label="Recovery receipt">
      <article className="rc">
        <header className="rc-top">
          <div>
            <span className="eyebrow">RECOVERY RECEIPT</span>
            <h2>What changed between two recorded sessions.</h2>
          </div>
          <div className="rc-top-actions">
            <button type="button" className="button button-outline button-small"
                    onClick={() => window.print()}>
              <Printer size={14} aria-hidden="true" /> Print / save as PDF
            </button>
            <button type="button" className="icon-button" onClick={onClose} aria-label="Close receipt">
              <X size={18} />
            </button>
          </div>
        </header>

        {/* ---- which two sessions (§26 selection) ---- */}
        <div className="rc-pick">
          <label>
            <span className="mono">BASELINE</span>
            <select value={baselineId ?? ""} onChange={(e) => setBaselineId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">First recorded session</option>
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>{s.label} · {s.date}</option>
              ))}
            </select>
          </label>
          <ArrowRight size={16} aria-hidden="true" className="rc-arrow" />
          <label>
            <span className="mono">COMPARED WITH</span>
            <select value={currentId ?? ""} onChange={(e) => setCurrentId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Most recent session</option>
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>{s.label} · {s.date}</option>
              ))}
            </select>
          </label>
        </div>

        {loading && (
          <p className="rc-state"><LoaderCircle className="spin" size={16} /> Building the comparison…</p>
        )}
        {error && <p className="rc-state rc-error" role="alert">{error}</p>}

        {comparison && b && c && (
          <>
            {/* ---- identity band ---- */}
            <dl className="rc-identity">
              <div><dt className="mono">RECORD</dt><dd>{patientName ?? `Patient ${comparison.patient_id}`}</dd></div>
              <div><dt className="mono">EXERCISE</dt><dd>{exerciseLabels[c.exercise_type as ExerciseType] ?? c.exercise_type}</dd></div>
              <div><dt className="mono">BASELINE</dt><dd>{b.day_label ?? "—"}</dd></div>
              <div><dt className="mono">CURRENT</dt><dd>{c.day_label ?? "—"}</dd></div>
              <div><dt className="mono">SPAN</dt><dd>{comparison.elapsed_days ?? 0} days</dd></div>
              <div><dt className="mono">ANALYTICS</dt><dd className="mono">{comparison.analytics_version ?? "—"}</dd></div>
            </dl>

            {/* ---- the comparison itself ---- */}
            <section className="rc-block">
              <span className="eyebrow">WHAT CHANGED</span>
              <ul className="rc-rows">
                {ROW_ORDER.map((key) => {
                  const d = comparison.deltas[key];
                  if (!d) return null;
                  const measurable = d.from !== null && d.to !== null && d.change !== null;
                  return (
                    <li key={key} className={`rc-row dir-${d.direction}`}>
                      <span className="rc-label">{d.label}</span>
                      {measurable ? (
                        <>
                          <span className="rc-from tabular">{withUnit(d.from!, d.unit)}</span>
                          <ArrowRight size={13} aria-hidden="true" className="rc-to-arrow" />
                          <span className="rc-to tabular">{withUnit(d.to!, d.unit)}</span>
                          <DeltaBar from={d.from!} to={d.to!} />
                          <span className="rc-change">
                            <DirectionIcon direction={d.direction} />
                            {d.change! > 0 ? "+" : ""}{withUnit(d.change!, d.unit)}
                          </span>
                        </>
                      ) : (
                        <span className="rc-unmeasured">
                          Not measured in {d.from === null ? "the baseline" : "this session"} —
                          no comparison possible.
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>

            {/* ---- bilateral: the thing this product is actually about ---- */}
            <section className="rc-block">
              <span className="eyebrow">BILATERAL PEAK FLEXION</span>
              <div className="rc-limbs">
                {(["baseline", "current"] as const).map((which) => {
                  const s = which === "baseline" ? b : c;
                  const left = s.peak_angle_left_deg;
                  const right = s.peak_angle_right_deg;
                  const span = Math.max(left ?? 0, right ?? 0, 1);
                  return (
                    <div key={which} className="rc-limb-col">
                      <span className="mono">{which === "baseline" ? "BASELINE" : "CURRENT"} · {s.day_label ?? "—"}</span>
                      {(["LEFT", "RIGHT"] as const).map((leg) => {
                        const v = leg === "LEFT" ? left : right;
                        return (
                          <div key={leg} className={`rc-limb leg-${leg.toLowerCase()}`}>
                            <span className="mono">{leg}</span>
                            <span className="rc-limb-bar">
                              <i style={{ width: `${((v ?? 0) / span) * 100}%` }} />
                            </span>
                            <strong className="tabular">{metric(v, "°")}</strong>
                          </div>
                        );
                      })}
                      <small className="mono">
                        LSI {metric(s.symmetry_index_pct, "%")}
                      </small>
                    </div>
                  );
                })}
              </div>
              <p className="fine-print">
                Symmetry is the limb symmetry index the analytics layer computed from comparable
                repetition peaks, not a comparison of instantaneous angles.
              </p>
            </section>

            {/* ---- indicator composition, from the backend ---- */}
            {scoring && scoring.contributions.length > 0 && (
              <section className="rc-block">
                <span className="eyebrow">
                  INDICATOR COMPOSITION · {fmtScore(scoring.recoveryValue)}
                </span>
                <ul className="rc-contrib">
                  {scoring.contributions.map((f) => (
                    <li key={f.key} className={f.available ? "" : "is-unavailable"}>
                      <span className="rc-contrib-label">{f.label}</span>
                      <span className="rc-contrib-bar" aria-hidden="true">
                        <i style={{ width: `${Math.round((f.normalized ?? 0) * 100)}%` }} />
                      </span>
                      <span className="mono rc-contrib-weight">×{f.weight.toFixed(2)}</span>
                      <span className="rc-contrib-value">
                        {f.available ? Math.round((f.normalized ?? 0) * 100) : "not available"}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* ---- narrative + confidence ---- */}
            <div className="rc-split">
              <section className="rc-block">
                <span className="eyebrow">WHAT MATTERS</span>
                <ul className="rc-summary">
                  {(comparison.summary ?? []).map((line) => <li key={line}>{line}</li>)}
                </ul>
              </section>
              <section className="rc-block">
                <span className="eyebrow">DATA CONFIDENCE</span>
                <dl className="rc-conf">
                  <div><dt className="mono">BASELINE</dt><dd>{metric(b.confidence, "%")} · {b.confidence_band ?? "—"}</dd></div>
                  <div><dt className="mono">CURRENT</dt><dd>{metric(c.confidence, "%")} · {c.confidence_band ?? "—"}</dd></div>
                  <div><dt className="mono">COVERAGE</dt><dd>{metric(c.coverage_pct, "%")}</dd></div>
                  <div><dt className="mono">REPETITIONS</dt><dd>{b.repetitions ?? "—"} → {c.repetitions ?? "—"}</dd></div>
                  <div><dt className="mono">SOURCE</dt><dd>{c.mode === "SIMULATED" ? "Simulated stream" : c.mode === "LIVE" ? "Connected device" : "Unknown"}</dd></div>
                </dl>
              </section>
            </div>

            <footer className="rc-foot">
              <p className="fine-print">
                {comparison.responsible_use ??
                  "Every figure above is an estimated decision-support indicator produced by the RehabSense analytics layer. It is not a diagnosis, a prognosis, a clearance criterion or a clinical measurement. Discuss any change with your physiotherapist."}
              </p>
              <span className="mono rc-stamp">
                {comparison.session_count} RECORDED SESSIONS · ANALYTICS{" "}
                {(comparison.analytics_version ?? "—").toUpperCase()}
              </span>
            </footer>
          </>
        )}
      </article>
    </div>
  );

  return createPortal(body, document.body);
}
