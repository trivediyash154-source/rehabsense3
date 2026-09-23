"use client";

import { useEffect, useState } from "react";

export type StageFocus = "thigh" | "shin" | "sync" | "score";

/**
 * The Lite product stage.
 *
 * This is the wearable assembly drawn as layered SVG with CSS depth, and it
 * is the *only* product visual whenever WebGL is unavailable, lost, declined
 * (reduced motion, save-data), or switched off by the user. It deliberately
 * mirrors the composition of the 3D scene — thigh and shin modules on a
 * translucent brace, a recovery ring around the knee, paired bilateral
 * signals — so the two modes read as the same product rather than a rich
 * version and a placeholder.
 *
 * It listens to the same `rehab:focus` event the 3D product does, so the
 * hero's sensor controls drive both identically.
 */
export function ProductStageFallback({
  active = true,
  compact = false,
  chrome = true,
}: {
  active?: boolean;
  compact?: boolean;
  /**
   * Draws the stage's own callouts, labels and badge. Turn this off where the
   * host already supplies that framing — inside the hero the surrounding
   * telemetry and sensor controls would otherwise collide with it.
   */
  chrome?: boolean;
}) {
  const [focus, setFocus] = useState<StageFocus>("sync");

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (detail === "thigh" || detail === "shin" || detail === "sync" || detail === "score") {
        setFocus(detail);
      }
    };
    window.addEventListener("rehab:focus", handler);
    return () => window.removeEventListener("rehab:focus", handler);
  }, []);

  return (
    <div
      className={`product-stage focus-${focus} ${active ? "is-active" : "is-behind"} ${
        compact ? "is-compact" : ""
      }`}
      aria-hidden="true"
    >
      <div className="stage-depth">
        <svg viewBox="0 0 420 580" fill="none" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="ps-shell" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--stage-shell-a)" />
              <stop offset="100%" stopColor="var(--stage-shell-b)" />
            </linearGradient>
            <linearGradient id="ps-left" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--cyan)" stopOpacity="0" />
              <stop offset="45%" stopColor="var(--cyan)" stopOpacity="1" />
              <stop offset="100%" stopColor="var(--cyan)" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="ps-right" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--violet)" stopOpacity="0" />
              <stop offset="55%" stopColor="var(--violet)" stopOpacity="1" />
              <stop offset="100%" stopColor="var(--violet)" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="ps-ring" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--cyan)" />
              <stop offset="100%" stopColor="var(--teal)" />
            </linearGradient>
            <linearGradient id="ps-sweep" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--stage-sweep)" stopOpacity="0" />
              <stop offset="50%" stopColor="var(--stage-sweep)" stopOpacity="0.85" />
              <stop offset="100%" stopColor="var(--stage-sweep)" stopOpacity="0" />
            </linearGradient>
            <radialGradient id="ps-halo">
              <stop offset="0%" stopColor="var(--cyan)" stopOpacity="0.5" />
              <stop offset="100%" stopColor="var(--cyan)" stopOpacity="0" />
            </radialGradient>
            <clipPath id="ps-thigh-clip">
              <rect x="150" y="58" width="120" height="196" rx="58" />
            </clipPath>
            <clipPath id="ps-shin-clip">
              <rect x="158" y="336" width="100" height="182" rx="48" />
            </clipPath>
          </defs>

          {/* ---- instrument backdrop ---- */}
          <g className="stage-grid">
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <line key={`h${i}`} x1="24" x2="396" y1={70 + i * 74} y2={70 + i * 74} />
            ))}
            {[0, 1, 2, 3, 4].map((i) => (
              <line key={`v${i}`} y1="40" y2="540" x1="60 " x2="60" transform={`translate(${i * 76} 0)`} />
            ))}
          </g>
          <g className="stage-orbits">
            <circle cx="210" cy="296" r="164" />
            <circle cx="210" cy="296" r="128" />
          </g>

          {/* ---- bilateral signal arcs: left and right limb ---- */}
          <g className="stage-signals">
            <path
              className="signal-path signal-left"
              d="M64 92 C24 210 24 380 64 500"
              stroke="url(#ps-left)"
              strokeWidth="2.4"
              fill="none"
            />
            <path
              className="signal-path signal-right"
              d="M356 92 C396 210 396 380 356 500"
              stroke="url(#ps-right)"
              strokeWidth="2.4"
              fill="none"
            />
            <circle className="signal-mote mote-left" r="4" fill="var(--cyan)">
              <animateMotion dur="7s" repeatCount="indefinite" path="M64 92 C24 210 24 380 64 500" />
            </circle>
            <circle className="signal-mote mote-right" r="4" fill="var(--violet)">
              <animateMotion dur="7s" begin="-0.9s" repeatCount="indefinite" path="M356 92 C396 210 396 380 356 500" />
            </circle>
          </g>

          {/* ---- thigh segment ---- */}
          <g className="segment segment-thigh">
            <rect x="150" y="58" width="120" height="196" rx="58" fill="url(#ps-shell)" className="shell" />
            <rect x="150" y="58" width="120" height="196" rx="58" className="shell-edge" />
            <g clipPath="url(#ps-thigh-clip)">
              <rect className="shell-sweep" x="150" y="-140" width="120" height="140" fill="url(#ps-sweep)" />
            </g>
            <rect x="146" y="96" width="128" height="15" rx="7" className="strap" />
            <rect x="146" y="200" width="128" height="15" rx="7" className="strap" />
          </g>

          {/* ---- knee: translucent brace structure ---- */}
          <g className="segment segment-knee">
            <circle cx="210" cy="296" r="52" className="knee-core" />
            <path className="brace-arc" d="M158 296 A52 52 0 0 1 262 296" />
            <path className="brace-arc brace-arc-b" d="M262 296 A52 52 0 0 1 158 296" />
            <circle cx="210" cy="296" r="14" className="knee-pivot" />
          </g>

          {/* ---- recovery ring ---- */}
          <g className="stage-ring">
            <circle cx="210" cy="296" r="92" className="ring-track" />
            <circle
              cx="210"
              cy="296"
              r="92"
              className="ring-value"
              stroke="url(#ps-ring)"
              transform="rotate(-96 210 296)"
            />
            <circle cx="210" cy="296" r="112" className="ring-outer" />
          </g>

          {/* ---- shin segment ---- */}
          <g className="segment segment-shin">
            <rect x="158" y="336" width="100" height="182" rx="48" fill="url(#ps-shell)" className="shell" />
            <rect x="158" y="336" width="100" height="182" rx="48" className="shell-edge" />
            <g clipPath="url(#ps-shin-clip)">
              <rect className="shell-sweep shell-sweep-b" x="158" y="-140" width="100" height="140" fill="url(#ps-sweep)" />
            </g>
            <rect x="154" y="370" width="108" height="14" rx="7" className="strap" />
            <rect x="154" y="464" width="108" height="14" rx="7" className="strap" />
          </g>

          {/* ---- sensor modules ---- */}
          <g className="sensor sensor-thigh">
            <circle cx="210" cy="152" r="52" fill="url(#ps-halo)" className="sensor-halo" />
            <rect x="180" y="118" width="60" height="72" rx="15" className="sensor-body" />
            <rect x="188" y="126" width="44" height="56" rx="11" className="sensor-face" />
            <rect x="196" y="134" width="28" height="5" rx="2.5" className="sensor-led" />
            <circle cx="210" cy="164" r="9" className="sensor-aperture" />
            <circle cx="210" cy="164" r="3.4" className="sensor-pupil" />
          </g>

          <g className="sensor sensor-shin">
            <circle cx="208" cy="424" r="46" fill="url(#ps-halo)" className="sensor-halo" />
            <rect x="182" y="396" width="52" height="62" rx="13" className="sensor-body" />
            <rect x="189" y="403" width="38" height="48" rx="10" className="sensor-face" />
            <rect x="196" y="410" width="24" height="4.5" rx="2.2" className="sensor-led" />
            <circle cx="208" cy="436" r="7.5" className="sensor-aperture" />
            <circle cx="208" cy="436" r="2.8" className="sensor-pupil" />
          </g>

          {/* ---- bilateral link: thigh module to shin module ---- */}
          <g className="stage-link">
            <path className="link-path" d="M210 190 L210 396" />
            <circle className="link-pulse" cx="210" cy="190" r="4.5" />
          </g>

          {/* ---- callout leaders + technical labels ---- */}
          {chrome && (
          <g className="stage-callouts">
            <path className="leader" d="M240 152 L318 152" />
            <path className="leader" d="M234 424 L312 424" />
            <path className="leader leader-left" d="M118 296 L58 296" />
            <text className="callout" x="324" y="149">IMU / 01</text>
            <text className="callout callout-sub" x="324" y="163">THIGH</text>
            <text className="callout" x="318" y="421">IMU / 02</text>
            <text className="callout callout-sub" x="318" y="435">SHIN</text>
            <text className="callout callout-end" x="52" y="293">RECOVERY</text>
            <text className="callout callout-sub callout-end" x="52" y="307">RING</text>
          </g>
          )}

          {/* ---- data pulses along the link ---- */}
          <g className="stage-data">
            {[0, 1, 2, 3].map((i) => (
              <rect key={i} className="data-tick" x={286 + i * 11} y="284" width="4" height="24" rx="2" style={{ animationDelay: `${i * 0.16}s` }} />
            ))}
          </g>
        </svg>

        {/* Score readout appears with the recovery-ring focus state. */}
        <div className="stage-readout">
          <span className="mono">ESTIMATED COMPOSITE</span>
          <strong>
            76<small>/100</small>
          </strong>
          <span className="stage-readout-note">Illustrative indicator</span>
        </div>
      </div>

      {chrome && (
        <span className="stage-badge mono">LITE VISUAL · CONCEPTUAL SENSING SYSTEM</span>
      )}
    </div>
  );
}
