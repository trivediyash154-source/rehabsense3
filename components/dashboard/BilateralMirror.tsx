"use client";

import { useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { ArrowUpRight, Layers, Columns2 } from "lucide-react";
import { limbCurve, type Session } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";
import { allPresent } from "@/lib/format";

type Mode = "overlay" | "side";

/**
 * BILATERAL MIRROR — old vs new as a visual transformation.
 *
 * The earlier session is drawn as a ghosted limb trace; the later one is
 * drawn live on top. A drag handle wipes between them so the change reads as
 * one movement becoming another, rather than two numbers in a table.
 */
export function BilateralMirror({ current }: { current: Session }) {
  const [mode, setMode] = useState<Mode>("overlay");
  const { sessions } = useData();
  const [wipe, setWipe] = useState(58);
  const [dragging, setDragging] = useState(false);
  const frame = useRef<HTMLDivElement>(null);

  // Compare against the baseline unless that *is* the current session, in
  // which case use the next one. With a single recorded session there is
  // nothing to compare against, so fall back to the session itself.
  const previous =
    (current.id === sessions[0]?.id ? sessions[1] : sessions[0]) ?? current;

  const move = (clientX: number) => {
    const box = frame.current?.getBoundingClientRect();
    if (!box) return;
    setWipe(Math.min(100, Math.max(0, ((clientX - box.left) / box.width) * 100)));
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    setDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    move(event.clientX);
  };

  const romDelta = current.rom - previous.rom;
  // Null when either session measured only one limb; there is no delta then.
  const symDelta = allPresent(current.symmetry, previous.symmetry)
    ? current.symmetry! - previous.symmetry!
    : null;

  return (
    <section className="mirror" aria-labelledby="mirror-title">
      <header className="mirror-head">
        <div>
          <span className="eyebrow">BILATERAL MIRROR · OLD VS NEW</span>
          <h3 id="mirror-title">Watch one movement become another.</h3>
        </div>
        <div className="segmented" role="group" aria-label="Comparison mode">
          <button type="button" aria-pressed={mode === "overlay"} onClick={() => setMode("overlay")}>
            <Layers size={13} aria-hidden="true" />
            Overlay
          </button>
          <button type="button" aria-pressed={mode === "side"} onClick={() => setMode("side")}>
            <Columns2 size={13} aria-hidden="true" />
            Side by side
          </button>
        </div>
      </header>

      {mode === "overlay" ? (
        <div
          ref={frame}
          className={`mirror-frame ${dragging ? "is-dragging" : ""}`}
          style={{ "--wipe": `${wipe}%` } as CSSProperties}
          onPointerDown={onPointerDown}
          onPointerMove={(event) => dragging && move(event.clientX)}
          onPointerUp={() => setDragging(false)}
          onPointerCancel={() => setDragging(false)}
        >
          <LimbPlate session={previous} variant="ghost" />
          <div className="mirror-reveal">
            <LimbPlate session={current} variant="live" />
          </div>

          <div
            className="mirror-handle"
            role="slider"
            tabIndex={0}
            aria-label="Reveal the later session"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(wipe)}
            aria-valuetext={`${Math.round(wipe)}% revealed, ${previous.label} on the left, ${current.label} on the right`}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") setWipe((w) => Math.max(0, w - 4));
              if (event.key === "ArrowRight") setWipe((w) => Math.min(100, w + 4));
            }}
          >
            <span className="mirror-grip" aria-hidden="true">
              <i />
              <i />
            </span>
          </div>

          <span className="mirror-tag mirror-tag-old mono">{previous.label} · GHOSTED</span>
          <span className="mirror-tag mirror-tag-new mono">{current.label} · CURRENT</span>
        </div>
      ) : (
        <div className="mirror-split">
          <figure>
            <LimbPlate session={previous} variant="ghost" />
            <figcaption className="mono">{previous.label} · {previous.dayLabel}</figcaption>
          </figure>
          <figure>
            <LimbPlate session={current} variant="live" />
            <figcaption className="mono">{current.label} · {current.dayLabel}</figcaption>
          </figure>
        </div>
      )}

      <div className="mirror-deltas">
        <DeltaStamp label="ROM estimate" from={previous.rom} to={current.rom} unit="°" delta={romDelta} />
        {symDelta !== null && (
          <DeltaStamp label="Symmetry" from={previous.symmetry!} to={current.symmetry!} unit="%" delta={symDelta} />
        )}
        <div className="mirror-note">
          <ArrowUpRight size={14} aria-hidden="true" />
          <p>
            The ghosted trace is {previous.label.toLowerCase()}; the lit trace is{" "}
            {current.label.toLowerCase()}. Both are illustrative estimates, not clinical
            measurements.
          </p>
        </div>
      </div>
    </section>
  );
}

function DeltaStamp({
  label,
  from,
  to,
  unit,
  delta,
}: {
  label: string;
  from: number;
  to: number;
  unit: string;
  delta: number;
}) {
  const dir = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return (
    <div className={`delta-stamp dir-${dir}`}>
      <span className="mono">{label}</span>
      <div className="delta-flow">
        <em>
          {from}
          {unit}
        </em>
        <span className="delta-arrow" aria-hidden="true" />
        <strong>
          {to}
          {unit}
        </strong>
      </div>
      <span className="delta-change">
        {delta > 0 ? "+" : ""}
        {delta}
        {unit} {dir === "up" ? "higher" : dir === "down" ? "lower" : "unchanged"}
      </span>
    </div>
  );
}

/**
 * A limb plate: thigh segment, knee, shin segment at the session's estimated
 * flexion, with its motion trail. The same anatomy language as the hero.
 */
function LimbPlate({ session, variant }: { session: Session; variant: "ghost" | "live" }) {
  // Visual flexion, damped so the shin reads as articulating rather than splaying.
  const flex = Math.min(62, session.rom * 0.42);
  const curve = limbCurve(session.peakLeft);
  const trail = curve
    .map((p, i) => `${(i / (curve.length - 1)) * 240 + 30} ${188 - (p.value / 135) * 74}`)
    .join(" L");

  return (
    <svg
      className={`limb-plate is-${variant}`}
      viewBox="0 0 300 230"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
    >
      <g className="plate-grid">
        {[0, 1, 2, 3].map((i) => (
          <line key={i} x1="18" x2="282" y1={44 + i * 48} y2={44 + i * 48} />
        ))}
      </g>

      {/* thigh reference segment */}
      <g className="limb-seg">
        <rect x="112" y="34" width="34" height="82" rx="17" />
        <circle className="limb-node" cx="129" cy="52" r="6" />
      </g>

      {/* knee joint + ROM arc */}
      <circle className="limb-knee" cx="129" cy="122" r="15" />
      <path
        className="limb-arc"
        d={arcPath(129, 122, 40, -90, -90 + flex)}
      />

      {/* shin segment, rotated to the session's estimated flexion */}
      <g className="limb-seg" transform={`rotate(${flex} 129 122)`}>
        <rect x="114" y="126" width="30" height="76" rx="15" />
        <circle className="limb-node" cx="129" cy="186" r="5.5" />
      </g>

      {/* motion trail */}
      <path className="limb-trail" d={`M${trail}`} />
      <text className="limb-value" x={variant === "ghost" ? 34 : 266} y="42" textAnchor={variant === "ghost" ? "start" : "end"}>
        {session.rom}°
      </text>
      <text
        className="limb-value limb-value-sub"
        x={variant === "ghost" ? 34 : 266}
        y="55"
        textAnchor={variant === "ghost" ? "start" : "end"}
      >
        {variant === "ghost" ? "EARLIER PEAK" : "CURRENT PEAK"}
      </text>
    </svg>
  );
}

function arcPath(cx: number, cy: number, r: number, a0: number, a1: number) {
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const p = (deg: number) => [cx + r * Math.cos(rad(deg)), cy + r * Math.sin(rad(deg))];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 0 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
}
