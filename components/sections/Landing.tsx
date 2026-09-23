"use client";

import { useState, type CSSProperties } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Download,
  Radio,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { Header, Footer } from "@/components/navigation/Header";
import { Hero } from "@/components/hero/Hero";
import { ContactForm } from "@/components/contact/ContactForm";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { Signal, MotionArc, RepetitionTrace, ConfidenceWave } from "@/components/charts/Signals";
import { DemoBadge, Eyebrow, Reveal, SectionHeading } from "@/components/ui/Primitives";

const journey = [
  { title: "Wear", text: "Place sensing assemblies on the thigh and shin of each leg.", annotation: "THIGH + SHIN / LEFT + RIGHT" },
  { title: "Move", text: "Walk or perform an exercise in the context of your rehabilitation plan.", annotation: "MOVEMENT / IN CONTEXT" },
  { title: "Capture", text: "IMU sensors capture motion signals that can be time-stamped.", annotation: "ACCELERATION + ANGULAR VELOCITY" },
  { title: "Synchronize", text: "Align both limbs in time so their movement can be compared.", annotation: "BILATERAL TIME ALIGNMENT" },
  { title: "Analyze", text: "Estimate knee motion, segment repetitions and examine gait timing.", annotation: "ESTIMATED / NOT DIAGNOSTIC" },
  { title: "Understand", text: "Bring explainable indicators into a conversation about recovery.", annotation: "DECISION SUPPORT / HUMAN INTERPRETATION" },
];

const parts = [
  { name: "Protective housing", code: "01 / ENCLOSURE", description: "A conceptual enclosure for the sensing electronics. Final materials, dimensions and protection rating are not established." },
  { name: "IMU module", code: "02 / MOTION", description: "An MPU6050 IMU may capture acceleration and angular velocity for estimating segment orientation." },
  { name: "ESP32 processing unit", code: "03 / PROCESSING", description: "An ESP32 may coordinate signal capture, timestamps and wireless communication." },
  { name: "Battery", code: "04 / POWER", description: "Conceptual onboard power. Capacity, charging implementation and runtime require hardware validation." },
  { name: "Wearable strap", code: "05 / INTERFACE", description: "A wearable attachment concept for positioning the assembly on the thigh or shin. Fit and placement affect signal interpretation." },
];

const extraParts = [
  { name: "Thigh sensor", code: "06 / UPPER SEGMENT", description: "Provides an upper-segment motion reference for relative knee flexion and extension estimates." },
  { name: "Shin sensor", code: "07 / LOWER SEGMENT", description: "Provides a lower-segment reference. Comparing segment orientations supports estimated knee motion." },
  { name: "Optional pressure or flex sensor", code: "08 / EXPLORATORY", description: "An optional research extension, not a confirmed component of the current sensing assembly." },
];

const allParts = [...parts, ...extraParts];

/* ---------------- 01 · The gap: editorial split ---------------- */
function Gap() {
  return (
    <section id="gap" className="section gap-section" data-scene="gap">
      <div className="container">
        <div className="gap-editorial">
          <Reveal>
            <Eyebrow index="01">THE SPACE BETWEEN</Eyebrow>
            <h2>
              Recovery continues
              <br />
              after the
              <br />
              <span className="muted-heading">appointment ends.</span>
            </h2>
          </Reveal>
          <Reveal className="gap-copy" delay={0.1}>
            <span className="large-quote" aria-hidden="true">
              &ldquo;
            </span>
            <p className="gap-pull">
              A clinical visit captures a moment.
              <br />
              Recovery happens in the movement between them.
            </p>
            <p className="body-copy">
              RehabSense explores how wearable sensing can make that in-between movement more
              understandable — without replacing the clinician&apos;s view.
            </p>
          </Reveal>
        </div>

        <Reveal className="appointment-timeline">
          <div className="timeline-node">
            <span aria-hidden="true" />
            <p>
              Clinical assessment
              <small>A moment of context</small>
            </p>
          </div>
          <div className="missing-signal" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
            <i />
            <span className="mono">THE MOVEMENT BETWEEN</span>
          </div>
          <div className="timeline-node timeline-node-end">
            <span aria-hidden="true" />
            <p>
              Follow-up assessment
              <small>Another moment of context</small>
            </p>
          </div>
        </Reveal>

        <div className="gap-observations">
          {[
            ["01", "Periodic assessment", "Appointments offer valuable context, but not a continuous picture of movement."],
            ["02", "Limited objective data", "Between visits, progress can be difficult to describe with comparable movement indicators."],
            ["03", "Difficult bilateral comparison", "Understanding both legs together calls for aligned signals, not isolated observations."],
          ].map(([n, title, text], i) => (
            <Reveal key={n} delay={i * 0.08}>
              <span className="mono">{n}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------- 02 · The idea: signal pipeline ---------------- */
function Idea() {
  return (
    <section id="idea" className="section idea-section" data-scene="flow">
      <div className="container">
        <SectionHeading
          index="02"
          label="THE REHABSENSE IDEA"
          title="Make movement measurable."
          copy="One continuous thread — from a physical movement to an explanation you can explore."
        />
        <Reveal className="signal-pipeline">
          <div className="pipeline-input">
            <span className="mono">01 / MOVEMENT SIGNAL</span>
            <Signal paired />
            <p>
              Left + right
              <br />
              <strong>Captured together.</strong>
            </p>
          </div>
          <div className="pipeline-core" aria-hidden="true">
            <div>
              <Radio size={26} />
              <span className="mono">REHABSENSE</span>
            </div>
            <i />
            <i />
          </div>
          <div className="pipeline-output">
            {[
              ["Knee angle", "Relative flexion & extension"],
              ["Gait symmetry", "Bilateral movement comparison"],
              ["Exercise repetition", "Segmented movement cycles"],
              ["Recovery trend", "Estimated indicators over time"],
            ].map(([title, copy], i) => (
              <div key={title} style={{ "--i": i } as CSSProperties}>
                <span className="mono">0{i + 1}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{copy}</p>
                </div>
                <ArrowUpRight size={16} />
              </div>
            ))}
          </div>
        </Reveal>
        <p className="section-footnote">
          Conceptual signal pipeline · No live sensor stream is connected to this website.
        </p>
      </div>
    </section>
  );
}

/* ---------------- 03 · Journey timeline ---------------- */
function HowItWorks() {
  const [step, setStep] = useState(0);
  return (
    <section id="how-it-works" className="section" data-scene="flow">
      <div className="container">
        <SectionHeading index="03" label="FROM BODY TO UNDERSTANDING" title="Six steps. One connected story." />
        <Reveal className="journey">
          <div
            className="journey-track"
            style={{ "--progress": `${(step / (journey.length - 1)) * 100}%` } as CSSProperties}
            role="tablist"
            aria-label="How RehabSense works"
          >
            {journey.map((item, i) => (
              <button
                key={item.title}
                type="button"
                role="tab"
                id={`journey-tab-${i}`}
                aria-selected={step === i}
                aria-controls="journey-detail"
                className={step === i ? "active" : step > i ? "complete" : ""}
                onClick={() => setStep(i)}
              >
                <span className="journey-node">
                  {step > i ? <Check size={15} aria-hidden="true" /> : `0${i + 1}`}
                </span>
                <strong>{item.title}</strong>
              </button>
            ))}
          </div>
          <div
            className="journey-detail"
            id="journey-detail"
            role="tabpanel"
            aria-labelledby={`journey-tab-${step}`}
            aria-live="polite"
          >
            <span className="journey-number" aria-hidden="true">
              0{step + 1}
            </span>
            <div>
              <span className="eyebrow">{journey[step].annotation}</span>
              <h3>{journey[step].title}.</h3>
              <p>{journey[step].text}</p>
            </div>
            <button
              type="button"
              className="icon-button journey-next"
              onClick={() => setStep((step + 1) % journey.length)}
              aria-label="Show next step"
            >
              <ArrowRight size={20} />
            </button>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------------- 04 · Exploded device anatomy ---------------- */
function Anatomy() {
  const [selected, setSelected] = useState(1);
  const layerCount = 5;

  return (
    <section id="anatomy" className="section anatomy-section" data-scene="flow">
      <div className="container anatomy-grid">
        <div>
          <SectionHeading
            index="04"
            label="SENSOR ANATOMY"
            title="Small assembly. Connected perspective."
            copy="Explore a conceptual sensing assembly, from its wearable interface to the signals it captures."
          />
          <div className="part-selector" role="group" aria-label="Sensing assembly components">
            {allParts.map((part, i) => (
              <button
                key={part.name}
                type="button"
                aria-pressed={selected === i}
                onClick={() => setSelected(i)}
              >
                <span className="mono">0{i + 1}</span>
                {part.name}
                <ArrowUpRight size={13} />
              </button>
            ))}
          </div>
        </div>

        <Reveal className="anatomy-stage">
          <span className="mono stage-label">EXPLODED VIEW / CONCEPTUAL ASSEMBLY</span>
          <div className={`exploded-assembly focus-${Math.min(selected, layerCount - 1)}`}>
            {Array.from({ length: layerCount }, (_, i) => (
              <button
                key={i}
                type="button"
                className={`device-layer device-layer-${i} ${selected === i ? "active" : ""}`}
                onClick={() => setSelected(i)}
                aria-label={`Inspect ${parts[i].name}`}
                aria-pressed={selected === i}
                style={{ "--layer": i } as CSSProperties}
              >
                {i === 0 && (
                  <span className="device-wordmark" aria-hidden="true">
                    rs<span>◦</span>
                  </span>
                )}
                {i === 1 && (
                  <span className="chip imu-chip" aria-hidden="true">
                    <i />
                    MPU6050
                  </span>
                )}
                {i === 2 && (
                  <span className="chip esp-chip" aria-hidden="true">
                    <i />
                    ESP32
                  </span>
                )}
                {i === 3 && (
                  <span className="battery-lines" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                )}
                {i === 4 && <span className="strap-texture" aria-hidden="true" />}
              </button>
            ))}
          </div>
          <div className="part-detail" aria-live="polite">
            <span className="eyebrow">{allParts[selected].code}</span>
            <h3>{allParts[selected].name}</h3>
            <p>{allParts[selected].description}</p>
          </div>
          <span className="fine-print">
            Prototype visualization · Not a manufacturing specification.
          </span>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------------- 05 · Irregular feature bento ---------------- */
function Features() {
  const [aligned, setAligned] = useState(false);

  return (
    <section id="features" className="section" data-scene="features">
      <div className="container">
        <SectionHeading
          index="05"
          label="MOVEMENT, MADE LEGIBLE"
          title="More than motion. Meaning."
          copy="Different perspectives on the same recovery process. All metrics are estimated decision-support indicators."
        />
        <div className="feature-bento">
          <Reveal className="feature-module feature-symmetry">
            <div className="feature-top">
              <span className="mono">01 / BILATERAL</span>
              <span className="tiny-label">L ↔ R</span>
            </div>
            <h3>
              Two legs.
              <br />
              A shared timeline.
            </h3>
            <p>Analyze bilateral gait symmetry using synchronized movement signals.</p>
            <Signal paired aligned={aligned} />
            <div className="feature-caption">
              <span>
                <i className="legend-left" />
                LEFT LEG
              </span>
              <span>
                <i className="legend-right" />
                RIGHT LEG
              </span>
              <button
                type="button"
                className="align-toggle"
                onClick={() => setAligned(!aligned)}
                aria-pressed={aligned}
              >
                {aligned ? "Show offset" : "Align signals"}
              </button>
            </div>
          </Reveal>

          <Reveal className="feature-module feature-rom">
            <span className="mono">02 / RANGE OF MOTION</span>
            <MotionArc />
            <h3>See the arc of movement.</h3>
            <p>Estimate relative knee flexion and extension.</p>
            <DemoBadge />
          </Reveal>

          <Reveal className="feature-module feature-reps">
            <span className="mono">03 / EXERCISE QUALITY</span>
            <RepetitionTrace />
            <h3>Every repetition, in context.</h3>
            <p>Segment exercise repetitions and explore movement quality.</p>
            <DemoBadge />
          </Reveal>

          <Reveal className="feature-module feature-cadence">
            <span className="mono">04 / GAIT TIMING</span>
            <Signal />
            <h3>Find the rhythm.</h3>
            <p>Explore cadence estimates and segmented gait cycles.</p>
          </Reveal>

          <Reveal className="feature-module feature-trend">
            <span className="mono">05 / LONGITUDINAL</span>
            <div>
              <h3>Progress is a pattern.</h3>
              <p>Follow estimated recovery trends across sessions — including the flat weeks.</p>
            </div>
            <Signal calm />
            <DemoBadge />
          </Reveal>

          <Reveal className="feature-module feature-score">
            <span className="mono">06 / EXPLAINABILITY</span>
            <div className="factor-orbit" aria-hidden="true">
              <i />
              <i />
              <i />
              <span>
                WHY
                <br />
                <strong>matters.</strong>
              </span>
            </div>
            <h3>A score you can question.</h3>
            <p>Explore the factors behind a composite recovery indicator.</p>
          </Reveal>

          <Reveal className="feature-module feature-confidence">
            <span className="mono">07 / SIGNAL CONFIDENCE</span>
            <ConfidenceWave />
            <h3>Know what the signal can say.</h3>
            <p>
              Where coverage drops, the waveform thins out — and the estimate becomes less
              dependable.
            </p>
          </Reveal>

          <Reveal className="feature-module feature-report">
            <span className="mono">08 / SHAREABLE CONTEXT</span>
            <div className="report-preview" aria-hidden="true">
              <span className="mono">REHABSENSE / SESSION SUMMARY</span>
              <div />
              <div />
              <Signal calm />
            </div>
            <h3>Carry the story forward.</h3>
            <p>Export an illustrative progress report for discussion.</p>
            <Link href="/dashboard" className="text-link">
              Explore reporting
              <Download size={14} />
            </Link>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* ---------------- 06 · Recovery score instrument ---------------- */
/**
 * Mirrors the documented composite-score model (ALGORITHMS.md §7): ROM 0.30,
 * symmetry 0.25, compliance 0.20, cadence 0.15, inverse pain 0.10. The values
 * are invented for the interface; the weights are the real proposed ones, so
 * the site and the spec stay in step.
 */
const factors = [
  { name: "Range of motion", short: "ROM", value: 82, weight: 0.3, color: "var(--cyan)", patient: "A view of the estimated movement available at your knee.", technical: "Normalized against a configurable target ROM for the exercise and recovery stage. Weight 0.30." },
  { name: "Bilateral symmetry", short: "Symmetry", value: 76, weight: 0.25, color: "var(--violet)", patient: "How movement patterns compare between your left and right legs.", technical: "Limb Symmetry Index proximity to 100%. Weight 0.25. Time alignment and data coverage qualify this figure." },
  { name: "Session consistency", short: "Compliance", value: 78, weight: 0.2, color: "var(--teal)", patient: "How regularly sessions were recorded — context, not a judgment of your effort.", technical: "Sessions completed / sessions prescribed. Weight 0.20. Defaults to neutral until a prescription module exists, so this figure is illustrative only." },
  { name: "Cadence", short: "Cadence", value: 74, weight: 0.15, color: "var(--amber)", patient: "A little context about the rhythm of your walking.", technical: "Session cadence against a healthy reference cadence. Weight 0.15. Not a universal clinical target." },
  { name: "Reported comfort", short: "Inverse pain", value: 90, weight: 0.1, color: "var(--coral)", patient: "Room for how you actually felt during the session, in your own words.", technical: "1 − (reported pain / 10). Weight 0.10. No patient-reported pain input is connected in this demo, so this contribution is illustrative." },
];

function RecoveryScore() {
  const [technical, setTechnical] = useState(false);
  const [selected, setSelected] = useState(0);
  const factor = factors[selected];
  const score = Math.round(factors.reduce((total, f) => total + f.value * f.weight, 0));

  return (
    <section id="recovery-score" className="section score-section" data-scene="score">
      <div className="container">
        <SectionHeading
          index="06"
          label="EXPLAINABLE RECOVERY"
          title="Not just a score. A recovery story."
          copy="A score is only useful when you can understand it. Explore each weighted contribution — and what still needs a human reading."
        />
        <Reveal className="score-layout">
          <div className="score-instrument">
            <div className="score-orbit-grid" aria-hidden="true" />
            <svg
              viewBox="0 0 360 360"
              role="img"
              aria-label={`Illustrative composite indicator of ${score} out of 100, built from five weighted factors: range of motion 82, bilateral symmetry 76, session consistency 78, cadence 74 and reported comfort 90.`}
            >
              {factors.map((f, i) => {
                const radius = 150 - i * 17;
                const length = 2 * Math.PI * radius;
                return (
                  <g key={f.name} transform="rotate(-90 180 180)">
                    <circle cx="180" cy="180" r={radius} fill="none" stroke="var(--line)" strokeWidth="6" />
                    <circle
                      cx="180"
                      cy="180"
                      r={radius}
                      fill="none"
                      stroke={f.color}
                      strokeWidth={selected === i ? 9 : 5}
                      strokeDasharray={`${(length * f.value) / 100} ${length}`}
                      strokeLinecap="round"
                      opacity={selected === i ? 1 : 0.5}
                      className="score-factor-arc"
                    />
                  </g>
                );
              })}
            </svg>
            <div className="score-center">
              <span className="eyebrow">RECOVERY INDICATOR</span>
              <strong>
                {score}
                <small>/100</small>
              </strong>
              <span className="score-sub">Estimated composite</span>
              <i aria-hidden="true" />
            </div>
            <span className="score-coordinate coord-one mono">L / R</span>
            <span className="score-coordinate coord-two mono">CONTEXT FIRST</span>
          </div>

          <div className="score-explanation">
            <DemoBadge variant="interface" />
            <div className="segmented" role="group" aria-label="Explanation depth">
              <button type="button" aria-pressed={!technical} onClick={() => setTechnical(false)}>
                Patient explanation
              </button>
              <button type="button" aria-pressed={technical} onClick={() => setTechnical(true)}>
                Technical explanation
              </button>
            </div>
            <div className="factor-list">
              {factors.map((f, i) => (
                <button
                  key={f.name}
                  type="button"
                  aria-pressed={selected === i}
                  onClick={() => setSelected(i)}
                >
                  <i style={{ background: f.color }} aria-hidden="true" />
                  <span>{technical ? f.short : f.name}</span>
                  <strong>
                    {f.value}
                    <small>/100</small>
                  </strong>
                  <ArrowUpRight size={14} />
                </button>
              ))}
            </div>
            <div className="factor-explanation" aria-live="polite">
              <h3>{factor.name}</h3>
              <p>{technical ? factor.technical : factor.patient}</p>
            </div>
            <div className="confidence-note">
              <SlidersHorizontal size={17} aria-hidden="true" />
              <p>
                <strong>Confidence is part of the story.</strong>
                <br />
                {technical
                  ? "Confidence is derived from data coverage and signal quality — how much of the session had both legs connected, and how much filtering correction was needed. The weights shown are the proposed model, not a clinically validated one."
                  : "Incomplete or noisy signals can make an estimate less dependable. Your physiotherapist adds essential context."}
              </p>
            </div>
          </div>
        </Reveal>
        <p className="section-footnote">
          Illustrative formula only. Not a clearance criterion, diagnosis, prognosis or
          return-to-sport recommendation.
        </p>
      </div>
    </section>
  );
}

/* ---------------- 07 · Workspace preview ---------------- */
function WorkspacePreview() {
  return (
    <section id="dashboard-preview" className="section dashboard-section" data-scene="features">
      <div className="container">
        <SectionHeading
          index="07"
          label="THE REHABSENSE WORKSPACE"
          title="The bigger picture. Without the noise."
          copy="Explore an illustrative session, compare both limbs, and follow the story across time."
        />
        <Reveal>
          <Dashboard />
        </Reveal>
      </div>
    </section>
  );
}

/* ---------------- 08 · Two audience panels ---------------- */
function Audiences() {
  return (
    <section className="section audience-section" data-scene="features">
      <div className="container">
        <div className="audience-panels">
          <Reveal className="audience-panel patient-panel">
            <div id="patients" className="anchor-target" />
            <Eyebrow index="08A">FOR PATIENTS</Eyebrow>
            <h2>
              Understand the work
              <br />
              your body is doing.
            </h2>
            <p>
              Clearer summaries. A longer view. Questions worth bringing to your next appointment.
            </p>
            <div className="patient-story">
              <span className="mono">A SESSION, EXPLAINED</span>
              {[
                ["Movement captured", true],
                ["Patterns organized", true],
                ["Context for a conversation", false],
              ].map(([label, done]) => (
                <div className="story-pulse" key={String(label)}>
                  <i aria-hidden="true" />
                  <span>{label}</span>
                  {done ? <Check size={14} aria-hidden="true" /> : <ArrowUpRight size={14} aria-hidden="true" />}
                </div>
              ))}
            </div>
            <ul className="audience-list">
              {["Session summaries", "Progress history", "Guided exercise concepts", "Movement feedback", "Simple explanations"].map((t) => (
                <li key={t}>
                  <Check size={13} aria-hidden="true" />
                  {t}
                </li>
              ))}
            </ul>
            <Link href="/dashboard" className="text-link">
              Explore the patient perspective
              <ArrowUpRight size={15} />
            </Link>
          </Reveal>

          <Reveal className="audience-panel physio-panel" delay={0.1}>
            <div id="physiotherapists" className="anchor-target" />
            <Eyebrow index="08B">FOR PHYSIOTHERAPISTS</Eyebrow>
            <h2>
              See the pattern
              <br />
              behind the session.
            </h2>
            <p>
              Bring bilateral movement and longitudinal context into your own clinical reasoning.
            </p>
            <div className="physio-story">
              <span className="mono">BILATERAL REVIEW / CONCEPT</span>
              <Signal paired />
              <div className="physio-legend">
                <span>LEFT LEG</span>
                <span>RIGHT LEG</span>
                <span>ALIGNED IN TIME</span>
              </div>
            </div>
            <ul className="audience-list">
              {["Patient overview concept", "Bilateral comparison", "Trend analysis", "Session quality", "Exportable reports", "Confidence indicators"].map((t) => (
                <li key={t}>
                  <Check size={13} aria-hidden="true" />
                  {t}
                </li>
              ))}
            </ul>
            <Link href="/contact" className="text-link">
              Discuss the clinical perspective
              <ArrowUpRight size={15} />
            </Link>
          </Reveal>
        </div>
        <p className="section-footnote">
          Conceptual product views. Exercise guidance must be set by an appropriate clinician; this
          demo does not prescribe a rehabilitation plan.
        </p>
      </div>
    </section>
  );
}

/* ---------------- 09 · Architecture network ---------------- */
function Foundation() {
  const architecture: [string, string][] = [
    ["Wearable sensors", "ESP32 · MPU6050"],
    ["Wireless stream", "Bluetooth / Wi-Fi"],
    ["API layer", "FastAPI"],
    ["Data store", "PostgreSQL"],
    ["Analytics engine", "Python analytics"],
    ["Your perspective", "RehabSense dashboard"],
  ];

  return (
    <section id="research" className="section foundation-section" data-scene="flow">
      <div className="container">
        <SectionHeading
          index="09"
          label="TECHNICAL FOUNDATION"
          title="A considered path from signal to insight."
          copy="A proposed research architecture. Every layer has a role, and every estimate should retain its context."
        />
        <Reveal className="architecture-network">
          {architecture.map(([title, technology], i) => (
            <div className="architecture-node" key={title} style={{ "--i": i } as CSSProperties}>
              <span className="mono">0{i + 1}</span>
              <div className="architecture-symbol" aria-hidden="true">
                {i === 0 ? <Radio size={19} /> : <span />}
              </div>
              <h3>{title}</h3>
              <p className="mono">{technology}</p>
              {i < architecture.length - 1 && (
                <span className="network-connector" aria-hidden="true">
                  <i />
                </span>
              )}
            </div>
          ))}
        </Reveal>
        <div className="foundation-principles">
          <span>Sensor fusion</span>
          <span>Time synchronization</span>
          <span>Bilateral comparison</span>
          <span>Explainable indicators</span>
        </div>
        <p className="section-footnote">
          The website demonstrates the interface layer. It does not include a deployed FastAPI
          service, PostgreSQL store or live sensor analytics pipeline.
        </p>
      </div>
    </section>
  );
}

/* ---------------- 10 · Responsible-use editorial ---------------- */
function Responsible() {
  const rows: [string, string][] = [
    ["A research prototype", "RehabSense is a prototype/research system, initially designed for ACL rehabilitation and related lower-limb recovery use cases. It is not presented as a certified or clinically validated medical device."],
    ["Estimates, not diagnoses", "Knee motion, symmetry, cadence, repetition quality and recovery indicators are estimates. RehabSense does not diagnose conditions or replace clinical evaluation."],
    ["People interpret the pattern", "The system is intended to support patients and physiotherapists outside specialized motion-capture laboratories. Clinical context and professional judgment remain essential."],
    ["Privacy with clear boundaries", "Data you record is stored in this deployment's own database and is readable only by your account and clinicians assigned to that patient. Optional event collection excludes passwords, codes, tokens, contact messages and medical data — only allowlisted event names and allowlisted property values can be sent. Contact details are transmitted only to a configured delivery service so the team can respond; hosting infrastructure may also process standard request metadata. Do not submit health records. Controller details, retention periods and user-rights processes must be established before public data collection."],
    ["Accounts are real; delivery is not connected", "Sign-in and sign-up create a real account on the RehabSense backend. Passwords are stored only as Argon2id hashes and the session is held in a cookie no page script can read. Social sign-in, password-reset email and SMS verification are not configured, so those screens send nothing."],
    ["Validation is a next step", "Future work should evaluate measurement reliability, repeatability, placement sensitivity, signal quality and clinical usefulness. No completed clinical validation or measured patient outcomes are claimed."],
  ];

  return (
    <section id="responsible" className="section responsible-section" data-scene="contact">
      <div className="container">
        <Reveal className="responsible-intro">
          <ShieldCheck size={26} aria-hidden="true" />
          <Eyebrow index="10">RESPONSIBLE BY DESIGN</Eyebrow>
          <h2>
            Advanced sensing.
            <br />
            <span className="muted-heading">Grounded expectations.</span>
          </h2>
          <p>Trust begins with being clear about what the system is — and what it isn&apos;t.</p>
        </Reveal>
        <div className="responsibility-list">
          {rows.map(([title, body], i) => (
            <Reveal key={title} className="responsibility-row">
              <span className="mono">0{i + 1}</span>
              <div>
                <h3>{title}</h3>
                <p>{body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------- 11 · Team roster ---------------- */
function Team() {
  const members: [string, string][] = [
    ["YT", "Yash Trivedi"],
    ["DZ", "Darshil Zade"],
    ["YM", "Yukta Myadam"],
    ["TS", "Tejal Sapkale"],
  ];

  return (
    <section id="team" className="section team-section" data-scene="contact">
      <div className="container">
        <div className="team-heading">
          <SectionHeading
            index="11"
            label="THE PEOPLE BEHIND THE SIGNAL"
            title="Built with curiosity. Guided by care."
          />
          <p>
            A project by the RehabSense team.
            <br />
            Vishwakarma Institute of Technology
          </p>
        </div>
        <div className="team-roster">
          {members.map(([initials, name], i) => (
            <Reveal key={name} className="team-member" delay={i * 0.06}>
              <span className="team-initials" aria-hidden="true">
                {initials}
              </span>
              <span className="mono">TEAM / 0{i + 1}</span>
              <h3>{name}</h3>
            </Reveal>
          ))}
        </div>
        <p className="team-guide">
          Faculty guide <span>Prof. Naina Kokate</span>
        </p>
      </div>
    </section>
  );
}

/* ---------------- 12 · Contact ---------------- */
export function ContactSection({ standalone = false }: { standalone?: boolean }) {
  const headline = (
    <>
      Let&apos;s make
      <br />
      rehabilitation
      <br />
      <em>more measurable.</em>
    </>
  );

  return (
    <section
      id="contact"
      className={`section contact-section ${standalone ? "contact-standalone" : ""}`}
      data-scene="contact"
    >
      <div className="container contact-grid">
        <Reveal className="contact-editorial">
          <Eyebrow index={standalone ? undefined : "12"}>START A CONVERSATION</Eyebrow>
          {standalone ? <h1>{headline}</h1> : <h2>{headline}</h2>}
          <p>For physiotherapists, researchers, rehabilitation teams and curious collaborators.</p>
          <div className="contact-signature" aria-hidden="true">
            <span />
            <i />
            <span />
          </div>
          <p className="fine-print">
            Demonstrations explore a research prototype, not a production clinical service.
          </p>
        </Reveal>
        <Reveal className="contact-surface" delay={0.08}>
          <ContactForm />
        </Reveal>
      </div>
    </section>
  );
}

export function Landing() {
  return (
    <>
      <Header />
      <main id="main">
        <Hero />
        <Gap />
        <Idea />
        <HowItWorks />
        <Anatomy />
        <Features />
        <RecoveryScore />
        <WorkspacePreview />
        <Audiences />
        <Foundation />
        <Responsible />
        <Team />
        <ContactSection />
      </main>
      <Footer />
    </>
  );
}
