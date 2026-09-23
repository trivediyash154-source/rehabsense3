"use client";

import { useId, useState } from "react";
import { fingerprint, type Session } from "@/lib/demo-data";

/**
 * MOVEMENT FINGERPRINT
 *
 * Six axes of movement character drawn as a layered radial signature. The
 * outline is the session's shape; the ghost behind it is the comparison
 * session, so the fingerprint visibly deforms as you move through history.
 *
 * Not a score. It is a *shape* — two sessions with the same composite
 * indicator can produce very different fingerprints, which is the point.
 */
export function MovementFingerprint({
  session,
  compare,
  size = 260,
  interactive = true,
}: {
  session: Session;
  compare?: Session;
  size?: number;
  interactive?: boolean;
}) {
  const raw = useId().replace(/:/g, "");
  const [hover, setHover] = useState<number | null>(null);

  const axes = fingerprint(session);
  const ghost = compare ? fingerprint(compare) : null;
  const cx = 150;
  const cy = 150;
  const rMax = 108;

  const point = (index: number, value: number, count: number) => {
    const angle = (index / count) * Math.PI * 2 - Math.PI / 2;
    const r = (value / 100) * rMax;
    return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r] as const;
  };

  const polygon = (values: { value: number }[]) =>
    values.map((v, i) => point(i, v.value, values.length).join(",")).join(" ");

  return (
    <figure className="fingerprint" style={{ maxWidth: size }}>
      <svg viewBox="0 0 300 300" role="img" aria-label={fingerprintLabel(session)}>
        <defs>
          <radialGradient id={`fp-${raw}`}>
            <stop offset="0%" stopColor="var(--cyan)" stopOpacity="0.42" />
            <stop offset="70%" stopColor="var(--violet)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="var(--violet)" stopOpacity="0.02" />
          </radialGradient>
        </defs>

        {/* graticule */}
        {[0.25, 0.5, 0.75, 1].map((step) => (
          <circle key={step} cx={cx} cy={cy} r={rMax * step} className="fp-ring" />
        ))}
        {axes.map((axis, i) => {
          const [x, y] = point(i, 100, axes.length);
          return <line key={axis.axis} x1={cx} y1={cy} x2={x} y2={y} className="fp-spoke" />;
        })}

        {/* comparison ghost */}
        {ghost && <polygon points={polygon(ghost)} className="fp-ghost" />}

        {/* the signature */}
        <polygon points={polygon(axes)} className="fp-shape" fill={`url(#fp-${raw})`} />

        {axes.map((axis, i) => {
          const [x, y] = point(i, axis.value, axes.length);
          const [lx, ly] = point(i, 128, axes.length);
          const on = hover === i;
          return (
            <g key={axis.axis} className={`fp-axis ${on ? "is-on" : ""}`}>
              <circle
                cx={x}
                cy={y}
                r={on ? 6 : 4}
                className="fp-node"
                onMouseEnter={interactive ? () => setHover(i) : undefined}
                onMouseLeave={interactive ? () => setHover(null) : undefined}
              />
              <text x={lx} y={ly} className="fp-label" textAnchor="middle" dominantBaseline="middle">
                {axis.axis}
              </text>
              {on && (
                <text x={lx} y={ly + 12} className="fp-value" textAnchor="middle">
                  {axis.value}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="mono">
        MOVEMENT FINGERPRINT · {session.label.toUpperCase()}
        {compare && ` VS ${compare.label.toUpperCase()}`}
      </figcaption>
    </figure>
  );
}

function fingerprintLabel(session: Session) {
  const axes = fingerprint(session);
  return `Movement fingerprint for ${session.label}: ${axes
    .map((a) => `${a.axis} ${a.value}`)
    .join(", ")}. Illustrative shape, not a clinical measurement.`;
}
