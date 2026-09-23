/**
 * Illustrative session data for the demo workspace.
 *
 * Every value here is invented to demonstrate an interface. Nothing was
 * measured, no patient exists, and no clinical meaning attaches to any of it.
 * It lives in one module so the workspace, the time machine, the bilateral
 * comparison and the recovery receipt all narrate the *same* story instead of
 * drifting apart.
 *
 * Metric definitions follow the documented analytics model:
 *   knee angle = shin inclination − thigh inclination
 *   LSI        = operated / non-operated × 100%
 *   composite  = Σ wᵢ·sᵢ over ROM .30, symmetry .25, compliance .20,
 *                cadence .15, inverse pain .10
 */

import { allPresent, plot } from "./format";

export type ExerciseType =
  | "WALK"
  | "SQUAT"
  | "SIT_TO_STAND"
  | "STEP_UP"
  | "SINGLE_LEG_BALANCE";

export const exerciseLabels: Record<ExerciseType, string> = {
  WALK: "Walking",
  SQUAT: "Squat",
  SIT_TO_STAND: "Sit to stand",
  STEP_UP: "Step up",
  SINGLE_LEG_BALANCE: "Single-leg balance",
};

export type Session = {
  id: number;
  label: string;
  day: number;
  dayLabel: string;
  date: string;
  exercise: ExerciseType;
  /**
   * Composite recovery indicator, 0-100. Estimated.
   *
   * `null` when the backend declined to score the session -- no range,
   * symmetry or cadence could be measured. A null must never be rendered as
   * 0: that reads as a measured result of zero rather than an absent one.
   */
  score: number | null;
  /** Estimated peak knee flexion, degrees. */
  rom: number;
  /** Estimated cadence, steps per minute. */
  cadence: number;
  reps: number;
  duration: string;
  /**
   * Limb Symmetry Index, percent. 100 = limbs match.
   *
   * `null` when only one limb reported, so there is nothing to compare.
   */
  symmetry: number | null;
  /** Share of the session with both limbs connected, percent. */
  coverage: number;
  confidence: "Lower" | "Moderate" | "Higher";
  /** Peak knee flexion per limb — drives the bilateral comparison. */
  peakLeft: number;
  peakRight: number;
  note: string;
};

export const sessions: Session[] = [
  { id: 1, label: "Session 01", day: 1, dayLabel: "Day 1", date: "12 Aug", exercise: "SIT_TO_STAND", score: 61, rom: 96, cadence: 82, reps: 16, duration: "14:08", symmetry: 79, coverage: 74, confidence: "Moderate", peakLeft: 96, peakRight: 76, note: "Baseline session. Guided sit-to-stand, shorter than planned." },
  { id: 2, label: "Session 02", day: 4, dayLabel: "Day 4", date: "15 Aug", exercise: "WALK", score: 66, rom: 103, cadence: 85, reps: 20, duration: "16:32", symmetry: 83, coverage: 81, confidence: "Moderate", peakLeft: 103, peakRight: 85, note: "First walking session recorded end to end." },
  { id: 3, label: "Session 03", day: 8, dayLabel: "Day 8", date: "19 Aug", exercise: "WALK", score: 69, rom: 109, cadence: 88, reps: 22, duration: "17:45", symmetry: 87, coverage: 92, confidence: "Higher", peakLeft: 109, peakRight: 95, note: "Both limbs connected throughout. Cleanest signal so far." },
  { id: 4, label: "Session 04", day: 12, dayLabel: "Day 12", date: "23 Aug", exercise: "STEP_UP", score: 68, rom: 111, cadence: 89, reps: 21, duration: "15:10", symmetry: 84, coverage: 58, confidence: "Lower", peakLeft: 111, peakRight: 93, note: "One side dropped out partway through. Interpret with care." },
  { id: 5, label: "Session 05", day: 16, dayLabel: "Day 16", date: "27 Aug", exercise: "WALK", score: 76, rom: 118, cadence: 94, reps: 24, duration: "18:42", symmetry: 91, coverage: 95, confidence: "Higher", peakLeft: 118, peakRight: 107, note: "Longest session recorded, with the highest coverage." },
];

export const baseline = sessions[0];
export const latest = sessions[sessions.length - 1];

/**
 * A normalized gait/repetition curve for one limb.
 * Shaped from the session's peak flexion so the trace and the headline
 * numbers can never disagree.
 */
export function limbCurve(peak: number, phase = 0, points = 41) {
  return Array.from({ length: points }, (_, i) => {
    const t = i / (points - 1);
    const base = Math.pow(Math.sin(t * Math.PI + phase), 2);
    const ripple = 0.045 * Math.sin(t * Math.PI * 6 + phase * 2);
    return {
      cycle: Math.round(t * 100),
      value: Math.max(2, Math.round((base + ripple) * (peak - 8) + 8)),
    };
  });
}

export function gaitFor(session: Session) {
  const left = limbCurve(session.peakLeft, 0);
  const right = limbCurve(session.peakRight, 0.08);
  return left.map((point, i) => ({
    cycle: point.cycle,
    left: point.value,
    right: right[i].value,
  }));
}

/** Weighted contributions, matching the documented composite model. */
export const scoreWeights = [
  { key: "rom", label: "Range of motion", weight: 0.3, color: "var(--cyan)" },
  { key: "symmetry", label: "Bilateral symmetry", weight: 0.25, color: "var(--violet)" },
  { key: "compliance", label: "Session consistency", weight: 0.2, color: "var(--teal)" },
  { key: "cadence", label: "Cadence", weight: 0.15, color: "var(--amber)" },
  { key: "comfort", label: "Reported comfort", weight: 0.1, color: "var(--coral)" },
] as const;

/**
 * Illustrative breakdown, used only in illustrative mode.
 *
 * For recorded sessions the workspace reads the backend's own contributions,
 * which carry the real weights and availability flags. This exists so the
 * demo dataset still has something to draw.
 */
export function contributions(session: Session) {
  const normalized: Record<string, number> = {
    rom: Math.min(100, Math.round((session.rom / 135) * 100)),
    symmetry: plot(session.symmetry),
    compliance: Math.min(100, session.coverage + 4),
    cadence: Math.min(100, Math.round((session.cadence / 110) * 100)),
    comfort: Math.min(100, plot(session.score) + 14),
  };
  return scoreWeights.map((factor) => ({
    ...factor,
    value: normalized[factor.key],
    contribution: Math.round(normalized[factor.key] * factor.weight * 10) / 10,
  }));
}

export type Delta = {
  label: string;
  unit: string;
  from: number;
  to: number;
  change: number;
  /** Higher is better for every metric currently tracked. */
  direction: "up" | "down" | "flat";
  precision: number;
};

export function deltas(from: Session, to: Session): Delta[] {
  const make = (label: string, unit: string, a: number, b: number, precision = 0): Delta => {
    const change = Math.round((b - a) * 10) / 10;
    return {
      label,
      unit,
      from: a,
      to: b,
      change,
      direction: change > 0 ? "up" : change < 0 ? "down" : "flat",
      precision,
    };
  };
  // A comparison needs both sides. Where either is absent the row is omitted
  // rather than shown as a change from or to zero.
  return [
    make("Knee ROM estimate", "°", from.rom, to.rom),
    allPresent(from.symmetry, to.symmetry)
      ? make("Bilateral symmetry", "%", from.symmetry!, to.symmetry!)
      : null,
    make("Cadence estimate", "steps/min", from.cadence, to.cadence),
    allPresent(from.score, to.score)
      ? make("Recovery indicator", "/100", from.score!, to.score!)
      : null,
  ].filter((d): d is Delta => d !== null);
}

/**
 * Plain-language summarisation of what the numbers already say.
 * Deterministic templating over the data — not a model, not a diagnosis.
 */
export function whatChanged(from: Session, to: Session): string[] {
  const lines: string[] = [];
  const rom = to.rom - from.rom;
  const sym = allPresent(from.symmetry, to.symmetry) ? to.symmetry! - from.symmetry! : null;
  const cad = to.cadence - from.cadence;

  if (rom !== 0) {
    lines.push(
      `Estimated knee ROM ${rom > 0 ? "increased" : "decreased"} ${Math.abs(rom)}° compared with ${from.label.toLowerCase()}.`,
    );
  }
  if (sym !== null && sym !== 0) {
    lines.push(
      `Bilateral symmetry is ${Math.abs(sym)} percentage points ${sym > 0 ? "closer to" : "further from"} 100%.`,
    );
  }
  if (cad !== 0) {
    lines.push(
      `Cadence estimate ${cad > 0 ? "rose" : "fell"} by ${Math.abs(cad)} steps per minute.`,
    );
  }
  lines.push(`The later session recorded ${to.reps} repetitions over ${to.duration}.`);
  if (to.coverage < 70) {
    lines.push(
      `Signal confidence is lower here: only ${to.coverage}% of the session had both limbs connected.`,
    );
  }
  return lines;
}

/** The contextual layer: what is worth a human reading. */
export function whatMatters(session: Session): { heading: string; body: string } {
  if (session.coverage < 70) {
    return {
      heading: "Read this session alongside its coverage",
      body: `Only ${session.coverage}% of this session had both limbs connected, so the estimates carry more uncertainty than the surrounding sessions. Treat the shape of the trend as more informative than this single point.`,
    };
  }
  if (session.symmetry !== null && session.symmetry < 85) {
    return {
      heading: "Symmetry is the open question",
      body: `The limbs differ by roughly ${100 - (session.symmetry ?? 0)} percentage points in this session. Bilateral difference is expected during recovery; whether this pattern matters is a conversation for your physiotherapist.`,
    };
  }
  return {
    heading: "Coverage and symmetry both look consistent",
    body: `${session.coverage}% coverage with a symmetry estimate of ${session.symmetry}%. That makes the estimates in this session more dependable than in sessions with partial signal — it does not make them clinical measurements.`,
  };
}

/** Suggested discussion points. Observations, never prescriptions. */
export function nextFocus(session: Session) {
  const focus =
    session.coverage < 70
      ? {
          area: "Signal coverage",
          observed: `One limb was unavailable for part of ${session.label.toLowerCase()}.`,
          discuss: "Check sensor placement and strap fit before the next session.",
        }
      : (session.symmetry ?? 100) < 88
        ? {
            area: "Bilateral symmetry",
            observed: `Symmetry estimate of ${session.symmetry}% — the limbs are not yet moving alike.`,
            discuss: "Worth raising symmetry-focused progression with your physiotherapist.",
          }
        : {
            area: "Range of motion",
            observed: `Estimated peak flexion of ${session.rom}° on the recorded limb.`,
            discuss: "Discuss whether the current range supports progressing the exercise.",
          };
  return focus;
}

/* =========================================================================
 * Workspace data
 * Everything below drives the demo workspace routes. Still invented, still
 * labelled illustrative everywhere it surfaces.
 * ======================================================================= */

export type RepEvent = {
  t: number;          // seconds into the session
  leg: "LEFT" | "RIGHT";
  index: number;
  rom: number;
  quality: number;    // 0–1, illustrative movement-quality score
};

export type RiskEvent = {
  t: number;
  severity: "INFO" | "WARNING";
  message: string;
};

/** Deterministic per-session replay track: reps alternate, quality drifts. */
export function repEvents(session: Session): RepEvent[] {
  const total = session.reps;
  const span = durationSeconds(session);
  return Array.from({ length: total }, (_, i) => {
    const leg = i % 2 === 0 ? "LEFT" : "RIGHT";
    const drift = Math.sin(i * 0.7) * 0.06;
    const limbPeak = leg === "LEFT" ? session.peakLeft : session.peakRight;
    return {
      t: Math.round(((i + 0.6) / total) * span),
      leg: leg as "LEFT" | "RIGHT",
      index: i + 1,
      rom: Math.round(limbPeak - 6 + Math.sin(i * 1.3) * 5),
      quality: Math.min(0.99, Math.max(0.35, plot(session.symmetry, 100) / 100 + drift)),
    };
  });
}

export function riskEvents(session: Session): RiskEvent[] {
  const span = durationSeconds(session);
  const events: RiskEvent[] = [];
  if (session.coverage < 70) {
    events.push({
      t: Math.round(span * 0.42),
      severity: "WARNING",
      message: "One limb stopped reporting — coverage dropped for the remainder.",
    });
  }
  if (session.symmetry !== null && session.symmetry < 85) {
    events.push({
      t: Math.round(span * 0.66),
      severity: "INFO",
      message: `Symmetry estimate held near ${session.symmetry}% through the middle of the session.`,
    });
  }
  events.push({
    t: Math.round(span * 0.08),
    severity: "INFO",
    message: "Calibration window complete. Both segment references established.",
  });
  return events.sort((a, b) => a.t - b.t);
}

export function durationSeconds(session: Session) {
  const [m, s] = session.duration.split(":").map(Number);
  return m * 60 + s;
}

export function formatClock(seconds: number) {
  // Used by the live lab, replay and focus. A non-finite input here would
  // render "NaN:NaN" on screen, so it degrades to a dash instead.
  if (!Number.isFinite(seconds)) return "--:--";
  const total = Math.max(0, seconds);
  const m = Math.floor(total / 60);
  const s = Math.floor(total % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* ----------------------------- Milestones ----------------------------- */

export type Milestone = {
  id: string;
  sessionId: number;
  title: string;
  detail: string;
  kind: "start" | "coverage" | "range" | "consistency" | "trend" | "latest";
};

export const milestones: Milestone[] = [
  { id: "m1", sessionId: 1, title: "Baseline recorded", detail: "First session captured, establishing the reference every later session is compared against.", kind: "start" },
  { id: "m2", sessionId: 2, title: "First full walking capture", detail: "A walking session recorded end to end without dropout.", kind: "coverage" },
  { id: "m3", sessionId: 3, title: "Cleanest signal so far", detail: "92% coverage with both limbs connected throughout.", kind: "coverage" },
  { id: "m4", sessionId: 4, title: "Coverage interruption", detail: "One side dropped out partway through; estimates carry more uncertainty here.", kind: "trend" },
  { id: "m5", sessionId: 5, title: "Highest recorded range", detail: "Estimated peak flexion of 118°, the largest in the recorded set.", kind: "range" },
];

/* -------------------------- Consistency grid -------------------------- */

export type ConsistencyDay = { day: number; date: string; sessionId?: number; intensity: number };

/** 28-day grid. Days with a session carry its indicator as intensity. */
export const consistencyDays: ConsistencyDay[] = Array.from({ length: 28 }, (_, i) => {
  const day = i + 1;
  const session = sessions.find((s) => s.day === day);
  return {
    day,
    date: `Day ${day}`,
    sessionId: session?.id,
    intensity: session ? plot(session.score) / 100 : 0,
  };
});

/* ---------------------------- Exercise library ------------------------ */

export type Exercise = {
  id: ExerciseType;
  name: string;
  focus: string;
  description: string;
  /** Sessions in the demo set that used this exercise. */
  sessionIds: number[];
  segments: string[];
  cue: string;
};

export const exercises: Exercise[] = [
  {
    id: "WALK",
    name: "Walking",
    focus: "Gait symmetry · cadence",
    description: "Level walking is the reference movement for bilateral comparison. Both limbs complete the same cycle, so timing differences between them become measurable.",
    sessionIds: [2, 3, 5],
    segments: ["Heel strike", "Stance", "Toe off", "Swing"],
    cue: "Walk at a comfortable pace. The system compares the two limbs against each other, not against a target.",
  },
  {
    id: "SQUAT",
    name: "Squat",
    focus: "Range of motion · loading",
    description: "A controlled bilateral descent. Knee flexion is estimated from the thigh–shin relationship on each side independently.",
    sessionIds: [],
    segments: ["Descent", "Bottom", "Ascent", "Reset"],
    cue: "Descend only as far as is comfortable. Depth is recorded, not scored against a target.",
  },
  {
    id: "SIT_TO_STAND",
    name: "Sit to stand",
    focus: "Repetition quality",
    description: "A repeated functional movement with clear start and end positions, which makes repetition segmentation straightforward.",
    sessionIds: [1],
    segments: ["Lean", "Lift off", "Extend", "Sit"],
    cue: "Rise without pushing through the arms where possible.",
  },
  {
    id: "STEP_UP",
    name: "Step up",
    focus: "Single-limb loading",
    description: "Loads one limb at a time, which surfaces asymmetry that bilateral movements can mask.",
    sessionIds: [4],
    segments: ["Plant", "Drive", "Stand", "Lower"],
    cue: "Lead with the same limb throughout so the comparison stays consistent.",
  },
  {
    id: "SINGLE_LEG_BALANCE",
    name: "Single-leg balance",
    focus: "Stability · control",
    description: "A quasi-static hold. Small angular corrections are visible in the signal as continuous micro-movement.",
    sessionIds: [],
    segments: ["Lift", "Hold", "Correct", "Lower"],
    cue: "Hold as steadily as possible. Small corrections are expected and are part of the signal.",
  },
];

/* --------------------------- Device assembly -------------------------- */

export type DeviceComponent = {
  id: string;
  name: string;
  code: string;
  role: string;
  detail: string;
  spec: string;
};

export const deviceComponents: DeviceComponent[] = [
  { id: "enclosure", name: "Protective housing", code: "01 / ENCLOSURE", role: "Structure", detail: "A conceptual enclosure for the sensing electronics. Materials, dimensions and ingress rating are not established.", spec: "Concept only" },
  { id: "esp32", name: "ESP32 processing unit", code: "02 / PROCESSING", role: "Compute", detail: "Coordinates sampling of both IMUs over a shared I²C bus, timestamps the readings and streams them over Wi-Fi.", spec: "Dual-core MCU · Wi-Fi" },
  { id: "thigh-imu", name: "Thigh IMU", code: "03 / UPPER SEGMENT", role: "Sense", detail: "Provides the upper-segment orientation reference. Knee angle is the difference between this and the shin.", spec: "MPU6050 · addr 0x68" },
  { id: "shin-imu", name: "Shin IMU", code: "04 / LOWER SEGMENT", role: "Sense", detail: "Provides the lower-segment reference. Because the measurement is relative, no fixed world reference is needed.", spec: "MPU6050 · addr 0x69" },
  { id: "fsr", name: "Foot-pressure sensor", code: "05 / OPTIONAL", role: "Sense", detail: "An optional ground-contact signal. When absent the analytics engine falls back to gyro-only stance detection.", spec: "FSR · optional capability" },
  { id: "battery", name: "Battery & power", code: "06 / POWER", role: "Power", detail: "Conceptual onboard power with charge protection and a boost stage. Runtime requires hardware validation.", spec: "Li-ion · concept" },
  { id: "strap", name: "Wearable strap", code: "07 / INTERFACE", role: "Mount", detail: "Positions the assembly on the thigh or shin. Fit and placement directly affect how the signal should be read.", spec: "Neoprene · concept" },
];

/* ------------------------ Sensor constellation ------------------------ */

export type ConstellationNode = {
  id: string;
  label: string;
  sub: string;
  stage: 0 | 1 | 2 | 3;
  limb?: "LEFT" | "RIGHT";
  status: "active" | "degraded" | "idle";
};

export function constellation(session: Session): ConstellationNode[] {
  const degraded = session.coverage < 70;
  return [
    { id: "l-node", label: "Left node", sub: "ESP32 · 2× IMU", stage: 0, limb: "LEFT", status: "active" },
    { id: "r-node", label: "Right node", sub: "ESP32 · 2× IMU", stage: 0, limb: "RIGHT", status: degraded ? "degraded" : "active" },
    { id: "l-stream", label: "Left stream", sub: "WebSocket ingest", stage: 1, limb: "LEFT", status: "active" },
    { id: "r-stream", label: "Right stream", sub: "WebSocket ingest", stage: 1, limb: "RIGHT", status: degraded ? "degraded" : "active" },
    { id: "fusion", label: "Sensor fusion", sub: "Complementary filter · ZUPT", stage: 2, status: "active" },
    { id: "analytics", label: "Analytics", sub: "Segmentation · symmetry · scoring", stage: 2, status: "active" },
    { id: "workspace", label: "Workspace", sub: "This interface", stage: 3, status: "active" },
  ];
}

/* -------------------------- Movement fingerprint ---------------------- */

/** Six axes describing the character of a session's movement. */
export function fingerprint(session: Session) {
  return [
    { axis: "Range", value: Math.min(100, Math.round((session.rom / 135) * 100)) },
    // The fingerprint is a shape; an unmeasured axis collapses to the centre
    // rather than being dropped, which would change the polygon's meaning.
    { axis: "Symmetry", value: plot(session.symmetry) },
    { axis: "Cadence", value: Math.min(100, Math.round((session.cadence / 110) * 100)) },
    { axis: "Volume", value: Math.min(100, Math.round((session.reps / 30) * 100)) },
    { axis: "Coverage", value: session.coverage },
    { axis: "Steadiness", value: Math.min(100, Math.round(plot(session.symmetry, 100) * 0.6 + session.coverage * 0.4)) },
  ];
}

/* ------------------------- Clinician workspace ------------------------ */

export type PatientRow = {
  id: string;
  initials: string;
  alias: string;
  operatedLeg: "LEFT" | "RIGHT";
  weeksPost: number;
  sessions: number;
  trend: number[];
  score: number;
  attention: "review" | "new" | "confidence" | "steady";
  reason: string;
};

/** Demo roster. No real people; aliases only, no identifying detail. */
export const patients: PatientRow[] = [
  { id: "p1", initials: "A·K", alias: "Patient A", operatedLeg: "LEFT", weeksPost: 3, sessions: 5, trend: [61, 66, 69, 68, 76], score: 76, attention: "review", reason: "Symmetry changed by 12 points since baseline" },
  { id: "p2", initials: "R·M", alias: "Patient B", operatedLeg: "RIGHT", weeksPost: 6, sessions: 9, trend: [58, 63, 67, 71, 74, 74, 78, 79, 81], score: 81, attention: "new", reason: "New session recorded 2 hours ago" },
  { id: "p3", initials: "S·D", alias: "Patient C", operatedLeg: "LEFT", weeksPost: 2, sessions: 3, trend: [54, 59, 57], score: 57, attention: "confidence", reason: "Signal confidence reduced — coverage 58%" },
  { id: "p4", initials: "T·N", alias: "Patient D", operatedLeg: "RIGHT", weeksPost: 9, sessions: 14, trend: [62, 68, 73, 77, 80, 82, 84, 85, 86, 86, 87, 88, 88, 89], score: 89, attention: "steady", reason: "Consistent upward trend across 14 sessions" },
  { id: "p5", initials: "J·P", alias: "Patient E", operatedLeg: "LEFT", weeksPost: 4, sessions: 6, trend: [60, 64, 66, 69, 70, 72], score: 72, attention: "steady", reason: "No change requiring review" },
];
