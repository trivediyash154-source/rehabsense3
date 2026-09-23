"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Printer, X } from "lucide-react";
import {
  baseline,
  contributions,
  deltas,
  exerciseLabels,
  nextFocus,
  whatChanged,
  whatMatters,
  type Session,
} from "@/lib/demo-data";
import { plot } from "@/lib/format";

/**
 * REHABSENSE RECOVERY RECEIPT
 *
 * A structured session record: what happened, what changed, what matters,
 * what to review. Modelled on a formal clinical summary rather than a till
 * receipt — ruled columns, metric stamps, a small anatomical mark, and an
 * explicit confidence and responsible-use block.
 *
 * Deliberately *not* included: any signature line, verification code or
 * QR-style graphic. Those would imply an authenticity guarantee this
 * prototype cannot provide.
 */
export function RecoveryReceipt({
  session,
  open,
  onClose,
}: {
  session: Session;
  open: boolean;
  onClose: () => void;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // Escape closes, and the page behind must not scroll under the document.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open || !mounted) return null;

  const compare = session.id === baseline.id ? session : baseline;
  const rows = deltas(compare, session);
  const changed = whatChanged(compare, session);
  const matters = whatMatters(session);
  const focus = nextFocus(session);
  const factors = contributions(session);
  const unit = (u: string) => (u === "/100" ? "" : u.length > 2 ? ` ${u}` : u);

  return createPortal(
    <div className="receipt-overlay" role="dialog" aria-modal="true" aria-label="Recovery receipt">
      <div className="receipt-scroll">
        <div className="receipt-actions">
          <button type="button" className="button button-outline button-small" onClick={() => window.print()}>
            <Printer size={14} aria-hidden="true" />
            Print / save as PDF
          </button>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close recovery receipt">
            <X size={20} />
          </button>
        </div>

        <article className="receipt" ref={sheet}>
          <div className="receipt-perf" aria-hidden="true" />

          <header className="receipt-head">
            <div>
              <span className="mono">REHABSENSE</span>
              <h2>Recovery Receipt</h2>
              <p className="mono">MOVEMENT INTELLIGENCE · SESSION RECORD</p>
            </div>
            <AnatomicalMark rom={session.rom} symmetry={plot(session.symmetry, 100)} />
          </header>

          <dl className="receipt-meta">
            <div><dt>Patient</dt><dd>Demo patient (no record connected)</dd></div>
            <div><dt>Session</dt><dd>{session.label}</dd></div>
            <div><dt>Date</dt><dd>{session.date} · {session.dayLabel}</dd></div>
            <div><dt>Exercise</dt><dd>{exerciseLabels[session.exercise]}</dd></div>
            <div><dt>Duration</dt><dd>{session.duration}</dd></div>
            <div><dt>Compared with</dt><dd>{compare.label} ({compare.dayLabel})</dd></div>
          </dl>

          <Rule label="MEASURED THIS SESSION" />

          <table className="receipt-table">
            <thead>
              <tr>
                <th scope="col">Indicator</th>
                <th scope="col">Baseline</th>
                <th scope="col">Current</th>
                <th scope="col">Change</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td className="num">{row.from}{unit(row.unit)}</td>
                  <td className="num strong">{row.to}{unit(row.unit)}</td>
                  <td className={`num delta delta-${row.direction}`}>
                    <span className="delta-mark" aria-hidden="true" />
                    {row.change > 0 ? "+" : ""}
                    {row.change}
                    {unit(row.unit)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <Rule label="WHAT CHANGED" />
          <ul className="receipt-list">
            {changed.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>

          <Rule label="WHAT MATTERS" />
          <div className="receipt-matters">
            <strong>{matters.heading}</strong>
            <p>{matters.body}</p>
          </div>

          <Rule label="EXERCISE ACTIVITY" />
          <div className="receipt-activity">
            <Stamp value={String(session.reps)} label="repetitions recorded" />
            <Stamp value={session.duration} label="session duration" />
            <Stamp value={`${session.coverage}%`} label="both limbs connected" />
            <Stamp value={exerciseLabels[session.exercise]} label="exercise performed" wide />
          </div>

          <Rule label="INDICATOR COMPOSITION" />
          <div className="receipt-factors">
            {factors.map((f) => (
              <div key={f.key}>
                <span>{f.label}</span>
                <div className="receipt-bar" aria-hidden="true">
                  <i style={{ width: `${f.value}%`, background: f.color }} />
                </div>
                <em className="mono">×{f.weight.toFixed(2)}</em>
                <strong>{f.contribution}</strong>
              </div>
            ))}
            <p className="fine-print">
              Weighted contributions to the composite indicator. Weights follow the proposed
              model; the values are illustrative.
            </p>
          </div>

          <Rule label="NEXT FOCUS" />
          <div className="receipt-focus">
            <div><dt className="mono">FOCUS AREA</dt><dd>{focus.area}</dd></div>
            <div><dt className="mono">OBSERVED PATTERN</dt><dd>{focus.observed}</dd></div>
            <div><dt className="mono">SUGGESTED DISCUSSION</dt><dd>{focus.discuss}</dd></div>
            <p className="fine-print">
              System-generated observation drawn from the values above. Not a prescription, and
              not a clinician-selected exercise.
            </p>
          </div>

          <Rule label="DATA CONFIDENCE" />
          <div className="receipt-confidence">
            <div className={`confidence-chip chip-${session.confidence.toLowerCase()}`}>
              {session.confidence} illustrative confidence
            </div>
            <ul>
              <li>Signal coverage: {session.coverage}% of the session had both limbs connected.</li>
              <li>Estimates derive from relative thigh–shin orientation, not a fixed reference.</li>
              <li>Sensor placement, strap fit and signal quality all affect interpretation.</li>
            </ul>
          </div>

          <Rule label="RESPONSIBLE USE" />
          <p className="receipt-disclaimer">
            RehabSense is a research prototype. Every figure in this document is an estimated
            decision-support indicator produced from illustrative interface data — not a clinical
            measurement, diagnosis, prognosis or clearance decision. No patient record is
            connected. Interpretation belongs with a qualified physiotherapist.
          </p>

          <footer className="receipt-foot">
            <span className="mono">REHABSENSE · MOVEMENT INTELLIGENCE</span>
            <span className="mono">RESEARCH PROTOTYPE · NOT A MEDICAL DEVICE</span>
          </footer>
        </article>
      </div>
      <button className="receipt-backdrop" onClick={onClose} aria-label="Close recovery receipt" tabIndex={-1} />
    </div>,
    document.body,
  );
}

function Rule({ label }: { label: string }) {
  return (
    <div className="receipt-rule">
      <span className="mono">{label}</span>
      <i aria-hidden="true" />
    </div>
  );
}

function Stamp({ value, label, wide = false }: { value: string; label: string; wide?: boolean }) {
  return (
    <div className={`receipt-stamp ${wide ? "is-wide" : ""}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

/** A restrained anatomical mark: limb segments, joint, and the ROM envelope. */
function AnatomicalMark({ rom, symmetry }: { rom: number; symmetry: number }) {
  const sweep = Math.min(78, rom * 0.55);
  const rad = (d: number) => (d * Math.PI) / 180;
  const p = (deg: number, r: number) => [46 + r * Math.cos(rad(deg)), 54 + r * Math.sin(rad(deg))];
  const [ax, ay] = p(-90, 30);
  const [bx, by] = p(-90 + sweep, 30);

  return (
    <svg className="receipt-mark" viewBox="0 0 92 108" aria-hidden="true">
      <rect x="38" y="10" width="16" height="40" rx="8" className="mark-seg" />
      <g transform={`rotate(${sweep} 46 54)`}>
        <rect x="39" y="58" width="14" height="38" rx="7" className="mark-seg" />
      </g>
      <circle cx="46" cy="54" r="7" className="mark-joint" />
      <path d={`M ${ax.toFixed(1)} ${ay.toFixed(1)} A 30 30 0 0 1 ${bx.toFixed(1)} ${by.toFixed(1)}`} className="mark-arc" />
      <text x="46" y="106" className="mark-label" textAnchor="middle">
        LSI {symmetry}%
      </text>
    </svg>
  );
}
