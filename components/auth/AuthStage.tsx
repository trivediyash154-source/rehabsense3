"use client";

import { useEffect, useState } from "react";
import type { AuthMode } from "@/lib/validations";

/**
 * The editorial visual panel for the authentication routes.
 *
 * Procedural, not photographic: `public/` holds no licensed imagery, and a
 * stock photo would either misrepresent RehabSense hardware or imply real
 * patients. Everything here is drawn, so it is always available — no WebGL,
 * no network, no licensing question — which also makes it the Lite visual
 * by default.
 *
 * Each route gets its own state of the same system rather than a different
 * illustration, so the five screens read as one product.
 */

type StageCopy = {
  eyebrow: string;
  headline: React.ReactNode;
  message: string;
  telemetry: [string, string][];
};

const stageCopy: Record<AuthMode, StageCopy> = {
  login: {
    eyebrow: "RETURN TO THE SIGNAL",
    headline: (
      <>
        Your movement
        <br />
        story <em>continues.</em>
      </>
    ),
    message: "Both limbs, still aligned in time.",
    telemetry: [
      ["SIGN-IN", "EMAIL + PASSWORD"],
      ["SESSION", "HTTPONLY COOKIE"],
    ],
  },
  signup: {
    eyebrow: "START MAKING MOVEMENT VISIBLE",
    headline: (
      <>
        Create a place
        <br />
        for <em>the work</em>
        <br />
        your body is doing.
      </>
    ),
    message: "Sensor nodes coming online, one segment at a time.",
    telemetry: [
      ["ACCOUNT", "EMAIL + PASSWORD"],
      ["PASSWORD", "ARGON2ID HASH"],
    ],
  },
  "verify-phone": {
    eyebrow: "PHONE VERIFICATION",
    headline: (
      <>
        Not part of
        <br />
        <em>this prototype.</em>
      </>
    ),
    message: "No SMS provider is connected, so no code is ever sent or checked.",
    telemetry: [
      ["CHANNEL", "SMS"],
      ["STATUS", "NOT CONFIGURED"],
    ],
  },
  "verify-email": {
    eyebrow: "EMAIL VERIFICATION",
    headline: (
      <>
        Not part of
        <br />
        <em>this prototype.</em>
      </>
    ),
    message: "No email provider is connected, so no verification message is ever sent.",
    telemetry: [
      ["CHANNEL", "EMAIL"],
      ["STATUS", "NOT CONFIGURED"],
    ],
  },
  "forgot-password": {
    eyebrow: "PASSWORD RESET",
    headline: (
      <>
        Reset by email
        <br />
        <em>is not available.</em>
      </>
    ),
    message: "No email provider is connected, so reset links cannot be sent.",
    telemetry: [
      ["CHANNEL", "EMAIL"],
      ["STATUS", "NOT CONFIGURED"],
    ],
  },
};

/** Route-specific artwork. One system, five states. */
function StageArt({ mode }: { mode: AuthMode }) {
  if (mode === "verify-phone") {
    return (
      <svg viewBox="18 104 364 226" fill="none" className="stage-art" aria-hidden="true">
        <g className="art-grid">
          {[0, 1, 2, 3, 4].map((i) => (
            <line key={i} x1="20" x2="380" y1={60 + i * 78} y2={60 + i * 78} />
          ))}
        </g>
        {/* handset node */}
        <g className="phone-node">
          <rect x="42" y="132" width="76" height="140" rx="16" />
          <rect x="52" y="146" width="56" height="104" rx="7" className="phone-screen" />
          <circle cx="80" cy="262" r="4" className="phone-dot" />
        </g>
        {/* six code segments travelling toward the sensor system */}
        <path className="code-path" d="M126 202 C190 202 210 202 268 202" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <rect
            key={i}
            className="code-cell"
            x={136 + i * 22}
            y="194"
            width="15"
            height="16"
            rx="3"
            style={{ animationDelay: `${i * 0.22}s` }}
          />
        ))}
        {/* receiving sensor */}
        <g className="receive-node">
          <circle cx="308" cy="202" r="52" className="receive-halo" />
          <rect x="282" y="172" width="52" height="62" rx="13" className="receive-body" />
          <rect x="292" y="182" width="32" height="5" rx="2.5" className="receive-led" />
          <circle cx="308" cy="212" r="9" className="receive-eye" />
        </g>
        <text className="art-label" x="42" y="300">YOUR DEVICE</text>
        <text className="art-label art-label-end" x="358" y="300">SENSING SYSTEM</text>
      </svg>
    );
  }

  if (mode === "verify-email") {
    return (
      <svg viewBox="10 66 380 268" fill="none" className="stage-art" aria-hidden="true">
        <g className="art-grid">
          {[0, 1, 2, 3, 4].map((i) => (
            <line key={i} x1="20" x2="380" y1={60 + i * 78} y2={60 + i * 78} />
          ))}
        </g>
        {/* illuminated envelope geometry */}
        <g className="envelope">
          <rect x="112" y="140" width="176" height="122" rx="12" className="env-body" />
          <path className="env-flap" d="M112 152 L200 216 L288 152" />
          <path className="env-beam" d="M112 262 L200 200 L288 262" />
        </g>
        <path className="data-route route-a" d="M28 96 C120 96 128 178 200 200" />
        <path className="data-route route-b" d="M372 96 C280 96 272 178 200 200" />
        <circle className="route-mote" r="4">
          <animateMotion dur="4.2s" repeatCount="indefinite" path="M28 96 C120 96 128 178 200 200" />
        </circle>
        <circle className="route-mote route-mote-b" r="4">
          <animateMotion dur="4.2s" begin="-2.1s" repeatCount="indefinite" path="M372 96 C280 96 272 178 200 200" />
        </circle>
        <circle cx="200" cy="200" r="9" className="env-seal" />
        <circle cx="200" cy="200" r="26" className="env-pulse" />
        <text className="art-label" x="200" y="316" textAnchor="middle">VERIFICATION PATH</text>
      </svg>
    );
  }

  if (mode === "forgot-password") {
    return (
      <svg viewBox="16 130 368 156" fill="none" className="stage-art" aria-hidden="true">
        <g className="art-grid">
          {[0, 1, 2, 3, 4].map((i) => (
            <line key={i} x1="20" x2="380" y1={60 + i * 78} y2={60 + i * 78} />
          ))}
        </g>
        {/* the interrupted path: fragments that re-knit toward the endpoint */}
        <path className="broken-track" d="M52 212 L348 212" />
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <line
            key={i}
            className="broken-seg"
            x1={56 + i * 42}
            x2={86 + i * 42}
            y1="212"
            y2="212"
            style={{ animationDelay: `${i * 0.18}s` }}
          />
        ))}
        <circle cx="52" cy="212" r="11" className="node-end node-start" />
        <circle cx="348" cy="212" r="11" className="node-end" />
        <circle cx="52" cy="212" r="22" className="node-ripple" />
        <circle className="repair-mote" r="5">
          <animateMotion dur="3.4s" repeatCount="indefinite" path="M52 212 L348 212" />
        </circle>
        <text className="art-label" x="52" y="262">ACCOUNT</text>
        <text className="art-label art-label-end" x="348" y="262">ACCESS RESTORED</text>
        <text className="art-note" x="200" y="160" textAnchor="middle">SIGNAL INTERRUPTED · NOT LOST</text>
      </svg>
    );
  }

  // login + signup share the paired-limb system, in two different states.
  const isSignup = mode === "signup";
  return (
    <svg viewBox="24 44 352 348" fill="none" className={`stage-art ${isSignup ? "art-forming" : "art-established"}`} aria-hidden="true">
      <g className="art-grid">
        {[0, 1, 2, 3, 4].map((i) => (
          <line key={i} x1="20" x2="380" y1={60 + i * 78} y2={60 + i * 78} />
        ))}
      </g>
      <g className="art-orbit">
        <circle cx="200" cy="212" r="132" />
        <circle cx="200" cy="212" r="96" />
      </g>
      {/* paired limb signals */}
      <path className="limb-path limb-left" d="M96 62 C58 150 142 274 104 360" />
      <path className="limb-path limb-right" d="M304 62 C342 150 258 274 296 360" />
      <circle className="limb-mote" r="4.5">
        <animateMotion dur="5.6s" repeatCount="indefinite" path="M96 62 C58 150 142 274 104 360" />
      </circle>
      <circle className="limb-mote limb-mote-b" r="4.5">
        <animateMotion dur="5.6s" begin={isSignup ? "-1.4s" : "-2.8s"} repeatCount="indefinite" path="M304 62 C342 150 258 274 296 360" />
      </circle>
      {/* sensor pair */}
      <g className="art-sensor art-sensor-top">
        <rect x="176" y="112" width="48" height="58" rx="12" />
        <rect x="185" y="122" width="30" height="5" rx="2.5" className="art-led" />
        <circle cx="200" cy="150" r="7.5" className="art-eye" />
      </g>
      <g className="art-sensor art-sensor-bottom">
        <rect x="178" y="256" width="44" height="54" rx="11" />
        <rect x="186" y="265" width="28" height="4.5" rx="2.2" className="art-led" />
        <circle cx="200" cy="291" r="7" className="art-eye" />
      </g>
      <path className="art-link" d="M200 170 L200 256" />
      {/* brace core: the same translucent knee structure as the hero product */}
      <g className="art-brace">
        <circle cx="200" cy="212" r="42" className="art-knee" />
        <path className="art-brace-arc" d="M158 212 A42 42 0 0 1 242 212" />
        <circle cx="200" cy="212" r="11" className="art-pivot" />
      </g>
      {/* recovery ring: complete for login, forming for signup */}
      <circle cx="200" cy="212" r="70" className="art-ring-track" />
      <circle cx="200" cy="212" r="70" className="art-ring" transform="rotate(-96 200 212)" />
      <text className="art-label" x="200" y="376" textAnchor="middle">
        {isSignup ? "NODES ACTIVATING" : "BILATERAL SIGNAL · ALIGNED"}
      </text>
    </svg>
  );
}

export function AuthStage({ mode, methods }: { mode: AuthMode; methods?: string[] }) {
  const copy = stageCopy[mode];
  // The sign-in methods this deployment actually offers, once the API has said
  // so; until then the static copy (email + password) stands.
  const telemetry = methods && methods.length > 1 && (mode === "login" || mode === "signup")
    ? copy.telemetry.map(([term, value]): [string, string] =>
        term === "SIGN-IN" || term === "ACCOUNT" ? [term, methods.join(" · ")] : [term, value])
    : copy.telemetry;
  const [live, setLive] = useState(false);

  // Lets the entrance choreography run once, after hydration.
  useEffect(() => {
    const id = requestAnimationFrame(() => setLive(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <aside className={`auth-stage stage-${mode} ${live ? "is-live" : ""}`}>
      <div className="auth-stage-frame" aria-hidden="true">
        <StageArt mode={mode} />
        <div className="stage-scanline" />
      </div>

      <div className="auth-stage-copy">
        <span className="eyebrow">{copy.eyebrow}</span>
        <h1>{copy.headline}</h1>
        <p>{copy.message}</p>
      </div>

      <dl className="auth-telemetry" aria-hidden="true">
        {telemetry.map(([term, value]) => (
          <div key={term}>
            <dt className="mono">{term}</dt>
            <dd className="mono">{value}</dd>
          </div>
        ))}
        <div>
          <dt className="mono">SYSTEM</dt>
          <dd className="mono">RESEARCH PROTOTYPE</dd>
        </div>
      </dl>
    </aside>
  );
}
