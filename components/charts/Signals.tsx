"use client";

import { useEffect, useId, useRef, useState } from "react";

const NOISY =
  "M0 50 L18 50 Q27 50 31 36 L39 70 L49 14 L60 84 L71 42 L79 50 L108 50 Q117 50 121 36 L129 70 L139 14 L150 84 L161 42 L169 50 L198 50 Q207 50 211 36 L219 70 L229 14 L240 84 L251 42 L260 50";
const CALM =
  "M0 66 C25 66 25 58 45 58 S75 34 95 38 S120 27 145 29 S170 17 195 20 S230 7 260 11";

/**
 * A movement signal. `paired` draws the second limb slightly offset —
 * the bilateral comparison the product is built around.
 */
export function Signal({
  paired = false,
  calm = false,
  aligned = false,
}: {
  paired?: boolean;
  calm?: boolean;
  aligned?: boolean;
}) {
  const raw = useId();
  const id = raw.replace(/:/g, "");
  const path = calm ? CALM : NOISY;

  return (
    <svg
      className={`signal ${calm ? "signal-calm" : ""}`}
      viewBox="0 0 260 100"
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={`g-${id}`} x1="0" x2="1">
          <stop stopColor="var(--cyan)" />
          <stop offset="1" stopColor="var(--violet)" />
        </linearGradient>
      </defs>
      {[25, 50, 75].map((y) => (
        <path key={y} d={`M0 ${y}H260`} stroke="var(--line)" strokeWidth=".6" />
      ))}
      {paired && (
        <path
          d={path}
          transform={aligned ? "translate(0 5)" : "translate(4 13)"}
          stroke="var(--violet)"
          strokeWidth="1.5"
          opacity=".65"
          style={{ transition: "transform .9s cubic-bezier(.22,1,.36,1)" }}
        />
      )}
      <path d={path} stroke={`url(#g-${id})`} strokeWidth="2" className="signal-line" />
      <path
        d={path}
        stroke="var(--cyan)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray="12 620"
        className="signal-packet"
      />
    </svg>
  );
}

/**
 * Range of motion. The arc sweeps through a controlled range and reports a
 * rounded estimate — deliberately no decimal places, to avoid fake precision.
 */
export function MotionArc({ min = 34, max = 118 }: { min?: number; max?: number }) {
  const [value, setValue] = useState(max);
  const frame = useRef(0);

  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const start = performance.now();
    const loop = (now: number) => {
      const cycle = (Math.sin((now - start) / 2400) + 1) / 2;
      setValue(Math.round(min + (max - min) * cycle));
      frame.current = requestAnimationFrame(loop);
    };
    frame.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame.current);
  }, [min, max]);

  // Sweep from 150° down to the current angle around a fixed joint centre.
  const cx = 120;
  const cy = 96;
  const r = 74;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const point = (deg: number) => [cx + r * Math.cos(toRad(deg)), cy - r * Math.sin(toRad(deg))];
  const [sx, sy] = point(188);
  const [ex, ey] = point(188 - value);
  const large = value > 180 ? 1 : 0;

  return (
    <svg viewBox="0 0 240 150" className="motion-arc" role="img" aria-label={`Illustrative knee range-of-motion arc, currently showing about ${value} degrees. Estimated indicator, not a clinical measurement.`}>
      {/* Sweep flag 1: the arc travels over the top of the joint centre. */}
      <path
        d={`M ${point(188)[0]} ${point(188)[1]} A ${r} ${r} 0 1 1 ${point(8)[0]} ${point(8)[1]}`}
        fill="none"
        stroke="var(--line)"
        strokeWidth="10"
        strokeLinecap="round"
      />
      <path
        d={`M ${sx} ${sy} A ${r} ${r} 0 ${large} 1 ${ex} ${ey}`}
        fill="none"
        stroke="var(--cyan)"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      {/* segment references */}
      <path d={`M ${cx} ${cy} L ${sx} ${sy}`} stroke="var(--muted)" strokeWidth="4" strokeLinecap="round" opacity=".55" />
      <path d={`M ${cx} ${cy} L ${ex} ${ey}`} stroke="var(--text)" strokeWidth="4" strokeLinecap="round" opacity=".8" />
      <circle cx={cx} cy={cy} r="7" fill="var(--surface)" stroke="var(--cyan)" strokeWidth="2" />
      <text x={cx} y="132" textAnchor="middle" fill="var(--text)" fontSize="21" className="arc-value">
        ≈{value}°
      </text>
      <text x={cx} y="146" textAnchor="middle" fill="var(--muted)" fontSize="8" letterSpacing="1.4" className="arc-label">
        ILLUSTRATIVE ESTIMATE
      </text>
    </svg>
  );
}

/**
 * Exercise repetitions: a repeating pulse sequence with markers on the
 * movement curve. Values are illustrative, never a rep-quality judgement.
 */
export function RepetitionTrace({ count = 24 }: { count?: number }) {
  const marks = Array.from({ length: 8 }, (_, i) => i);
  return (
    <div className="rep-trace">
      <svg viewBox="0 0 260 74" fill="none" aria-hidden="true" preserveAspectRatio="none">
        <path d="M0 60H260" stroke="var(--line)" strokeWidth=".8" />
        <path
          d="M0 60 C10 60 12 14 26 14 S42 60 52 60 S64 14 78 14 S94 60 104 60 S116 14 130 14 S146 60 156 60 S168 14 182 14 S198 60 208 60 S220 14 234 14 S250 60 260 60"
          stroke="var(--cyan)"
          strokeWidth="1.8"
          className="rep-path"
        />
        {marks.map((i) => (
          <circle
            key={i}
            cx={26 + i * 26}
            cy={i % 2 === 0 ? 14 : 60}
            r="3"
            fill="var(--violet)"
            className="rep-mark"
            style={{ animationDelay: `${i * 0.22}s` }}
          />
        ))}
      </svg>
      <div className="rep-readout">
        <strong>{count}</strong>
        <span>illustrative repetitions</span>
      </div>
    </div>
  );
}

/**
 * Signal confidence rendered as clarity: a clean waveform degrades into a
 * noisy, sparse one so the trade-off is visible rather than asserted.
 */
export function ConfidenceWave({ quality = 0.78 }: { quality?: number }) {
  const bars = 34;
  return (
    <div className="confidence-wave" role="img" aria-label="Illustrative signal quality. Where the waveform becomes sparse and irregular, an estimate is less dependable.">
      {Array.from({ length: bars }, (_, i) => {
        const clarity = i / bars < quality ? 1 : 0.32;
        // Deterministic jitter: rendered identically on server and client.
        const jitter = clarity < 1 ? Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 5 : 0;
        const height = 6 + Math.abs(Math.sin(i * 0.55)) * 30 * clarity + jitter;
        return (
          <i
            key={i}
            style={{
              height: `${Math.round(height)}px`,
              opacity: clarity === 1 ? 0.95 : 0.35,
              background: clarity === 1 ? "var(--cyan)" : "var(--muted)",
            }}
          />
        );
      })}
    </div>
  );
}
