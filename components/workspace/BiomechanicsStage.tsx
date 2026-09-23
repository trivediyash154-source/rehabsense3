"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type LimbState = {
  /** Knee flexion in degrees, per limb. */
  left: number;
  right: number;
  /** 0–1 through the current movement cycle. */
  phase: number;
  active: boolean;
  degradedRight?: boolean;
};

/**
 * BIOMECHANICS STAGE
 *
 * Both lower limbs rendered as layered 2.5D SVG with motion trails. This is
 * the shared anatomy for the live lab and the replay: same geometry, same
 * trail language, driven purely by a `LimbState`, so live data and recorded
 * data look identical — which is the honest thing, since both are estimates
 * from the same pipeline.
 *
 * SVG rather than WebGL by choice: it stays crisp, works in Lite and
 * reduced-motion, needs no context, and the anatomy is planar anyway.
 */
/** A finite number, or the fallback. Guards every numeric input at the edge. */
function finite(value: number | null | undefined, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function BiomechanicsStage({ state: raw, trails = true }: { state: LimbState; trails?: boolean }) {
  // This stage is shared by the live lab, replay and overview. Sanitising
  // once here means a single bad upstream value cannot emit rotate(NaN),
  // cy="NaN" or opacity:NaN and break the whole SVG for every caller.
  const state: LimbState = {
    ...raw,
    left: finite(raw.left, 8),
    right: finite(raw.right, 8),
    phase: finite(raw.phase, 0),
  };

  const history = useRef<{ l: number[]; r: number[] }>({ l: [], r: [] });
  const [, force] = useState(0);

  useEffect(() => {
    const h = history.current;
    h.l.push(state.left);
    h.r.push(state.right);
    if (h.l.length > 90) h.l.shift();
    if (h.r.length > 90) h.r.shift();
    force((n) => (n + 1) % 1000);
  }, [state.left, state.right]);

  const trailPath = (values: number[], originX: number) => {
    // A trail is decorative; one bad sample must not void the whole path.
    const clean = values.filter((v) => Number.isFinite(v));
    if (clean.length < 2) return "";
    return clean
      .map((v, i) => {
        const t = i / Math.max(1, clean.length - 1);
        const angle = ((v - 10) * Math.PI) / 180;
        const x = originX + Math.sin(angle) * 74 * (0.35 + t * 0.65);
        const y = 250 + Math.cos(angle) * 74 * (0.35 + t * 0.65);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  };

  return (
    <div className={`bio-stage ${state.active ? "is-active" : "is-idle"}`}>
      <svg viewBox="82 78 356 368" role="img" aria-label={`Estimated knee flexion: left ${Math.round(state.left)} degrees, right ${Math.round(state.right)} degrees. Illustrative visualisation.`}>
        <defs>
          <linearGradient id="bio-shell" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--stage-shell-a)" />
            <stop offset="100%" stopColor="var(--stage-shell-b)" />
          </linearGradient>
        </defs>

        {/* spatial field */}
        <g className="bio-field">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <ellipse key={i} cx="260" cy="252" rx={54 + i * 26} ry={17 + i * 8} />
          ))}
        </g>

        <Limb x={168} flex={state.left} side="LEFT" phase={state.phase} degraded={false} />
        <Limb x={352} flex={state.right} side="RIGHT" phase={state.phase} degraded={Boolean(state.degradedRight)} />

        {trails && (
          <g className="bio-trails">
            <path d={trailPath(history.current.l, 168)} className="bio-trail trail-left" />
            <path d={trailPath(history.current.r, 352)} className="bio-trail trail-right" />
          </g>
        )}

        {/* bilateral link: brightness tracks how alike the limbs are */}
        <g className="bio-link" style={{ opacity: 0.25 + (1 - Math.min(1, Math.abs(state.left - state.right) / 45)) * 0.7 }}>
          <path d="M206 250 L314 250" />
          <text x="260" y="242" className="bio-link-label">
            Δ {Math.abs(Math.round(state.left - state.right))}°
          </text>
        </g>
      </svg>
    </div>
  );
}

function Limb({
  x,
  flex,
  side,
  phase,
  degraded,
}: {
  x: number;
  flex: number;
  side: "LEFT" | "RIGHT";
  phase: number;
  degraded: boolean;
}) {
  // Defence in depth: a non-finite angle from any caller would emit
  // rotate(NaN ...) and an arc path the browser refuses to draw.
  const safeFlex = Number.isFinite(flex) ? flex : 0;
  const angle = Math.min(85, Math.max(0, safeFlex));
  const arc = useMemo(() => {
    const r = 52;
    const rad = (d: number) => (d * Math.PI) / 180;
    const p = (d: number) => [x + r * Math.sin(rad(d)), 250 + r * Math.cos(rad(d))];
    const [x0, y0] = p(0);
    const [x1, y1] = p(angle);
    return `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 0 ${angle >= 0 ? 0 : 1} ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  }, [x, angle]);

  return (
    <g className={`bio-limb side-${side.toLowerCase()} ${degraded ? "is-degraded" : ""}`}>
      {/* thigh */}
      <rect x={x - 22} y={118} width="44" height="118" rx="22" className="bio-seg" fill="url(#bio-shell)" />
      <rect x={x - 26} y={140} width="52" height="11" rx="5" className="bio-strap" />
      <g className="bio-sensor" transform={`translate(${x} 168)`}>
        <rect x="-17" y="-21" width="34" height="42" rx="9" />
        <rect x="-10" y="-14" width="20" height="4" rx="2" className="bio-led" />
        <circle cy="6" r="5.5" className="bio-eye" />
      </g>

      {/* knee */}
      <circle cx={x} cy="250" r="19" className="bio-knee" />
      <path d={arc} className="bio-arc" />
      <text
        x={side === "LEFT" ? x - 56 : x + 56}
        y={262}
        className="bio-angle"
      >
        {Math.round(angle)}°
      </text>

      {/* shin, articulating */}
      <g transform={`rotate(${angle} ${x} 250)`} className="bio-shin">
        <rect x={x - 18} y={262} width="36" height="106" rx="18" className="bio-seg" fill="url(#bio-shell)" />
        <rect x={x - 22} y={288} width="44" height="10" rx="5" className="bio-strap" />
        <g className="bio-sensor" transform={`translate(${x} 316)`}>
          <rect x="-15" y="-19" width="30" height="38" rx="8" />
          <rect x="-9" y="-12" width="18" height="3.6" rx="1.8" className="bio-led" />
          <circle cy="5" r="5" className="bio-eye" />
        </g>
      </g>

      <text x={x} y={100} className="bio-side">{side}</text>
      {degraded && <text x={x} y={432} className="bio-warn">SIGNAL INTERRUPTED</text>}
      {/* phase pip travelling the segment */}
      <circle
        cx={x}
        cy={130 + phase * 100}
        r="3.4"
        className="bio-pip"
      />
    </g>
  );
}
