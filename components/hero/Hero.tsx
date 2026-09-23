"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUpRight, MoveUpRight } from "lucide-react";
import { Reveal, Eyebrow } from "@/components/ui/Primitives";
import { ProductStageFallback } from "@/components/three/ProductStageFallback";
import { useSceneStatus } from "@/components/three/SceneContext";
import { track } from "@/lib/analytics";

type NodeId = "thigh" | "shin" | "sync" | "score";

const nodes: { id: NodeId; name: string; detail: string; code: string }[] = [
  { id: "thigh", name: "Thigh sensor", detail: "Upper-segment motion reference", code: "IMU / 01" },
  { id: "shin", name: "Shin sensor", detail: "Lower-segment motion reference", code: "IMU / 02" },
  { id: "sync", name: "Bilateral signal", detail: "Both limbs, aligned in time", code: "L ↔ R" },
  { id: "score", name: "Recovery ring", detail: "An indicator you can question", code: "INSIGHT" },
];

export function Hero() {
  const { glActive } = useSceneStatus();
  const [selected, setSelected] = useState<NodeId>("sync");
  const node = nodes.find((item) => item.id === selected)!;
  const lastSent = useRef<NodeId | null>(null);

  // The 3D scene lives outside this tree; a custom event keeps them in sync
  // without threading state through the whole app.
  useEffect(() => {
    if (lastSent.current === selected) return;
    lastSent.current = selected;
    window.dispatchEvent(new CustomEvent("rehab:focus", { detail: selected }));
  }, [selected]);

  return (
    <section id="product" className="hero" data-scene="hero">
      <div className="container hero-inner">
        <div className="hero-overline">
          <span className="status-dot" aria-hidden="true" />
          LOWER-LIMB REHABILITATION INTELLIGENCE
          <span className="hero-edition">RESEARCH EDITION / 01</span>
        </div>

        <div className="hero-grid">
          <Reveal className="hero-copy">
            <Eyebrow>MAKE RECOVERY VISIBLE.</Eyebrow>
            <h1>
              Recovery
              <br />
              is not a
              <br />
              <em>snapshot.</em>
            </h1>
            <p className="hero-subhead">
              RehabSense turns lower-limb movement into measurable, explainable recovery
              intelligence.
            </p>
            <p className="hero-description">
              Wearable motion sensing helps patients and physiotherapists understand knee
              movement, gait symmetry, exercise quality and progress between clinical visits.
            </p>
            <div className="hero-actions">
              <a
                className="button"
                href="#idea"
                onClick={() => track("hero_cta_clicked", { action: "explore_system" })}
              >
                Explore the system
                <ArrowUpRight size={18} />
              </a>
              <Link
                className="button button-outline"
                href="/contact"
                onClick={() => track("demo_requested", { action: "hero" })}
              >
                Request a demonstration
              </Link>
            </div>
            <a className="hero-text-link" href="#how-it-works">
              See how movement becomes insight
              <ArrowDown size={14} />
            </a>
          </Reveal>

          <div className="hero-visual">
            {/* Always rendered. When WebGL is live the 3D product takes over and
                this fades to a faint scaffold; otherwise it *is* the product. */}
            <ProductStageFallback active={!glActive} chrome={false} />
            <div className="visual-corner">
              <span className="mono">PROTOTYPE SENSING SYSTEM</span>
              <MoveUpRight size={15} />
            </div>
            <span className="visual-cross cross-one" aria-hidden="true" />
            <span className="visual-cross cross-two" aria-hidden="true" />

            <div className="telemetry telemetry-top">
              <span className="mono">THIGH / REFERENCE</span>
              <span className="telemetry-line" aria-hidden="true" />
            </div>
            <div className="telemetry telemetry-bottom">
              <span className="telemetry-line" aria-hidden="true" />
              <span className="mono">SHIN / RELATIVE MOTION</span>
            </div>

            <div className="hero-instrument">
              <span className="instrument-pulse" aria-hidden="true" />
              <span className="mono instrument-code">{node.code}</span>
              <div aria-live="polite" className="instrument-readout">
                <strong>{node.name}</strong>
                <p>{node.detail}</p>
              </div>
            </div>

            <div className="sensor-controls" role="group" aria-label="Explore the sensing system">
              {nodes.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelected(item.id)}
                  onMouseEnter={() => setSelected(item.id)}
                  onFocus={() => setSelected(item.id)}
                  aria-pressed={selected === item.id}
                >
                  <span className="mono">{String(index + 1).padStart(2, "0")}</span>
                  <span className="control-name">{item.name}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="hero-bottom">
          <a href="#gap" className="scroll-cue">
            <span aria-hidden="true">
              <ArrowDown size={14} />
            </span>
            SCROLL TO FOLLOW THE SIGNAL
          </a>
          <p className="hero-focus">
            Designed around movement.
            <br />
            <span>Initially focused on ACL rehabilitation.</span>
          </p>
          <span className="mono hero-note">
            ESTIMATED INSIGHTS.
            <br />
            HUMAN INTERPRETATION.
          </span>
        </div>
      </div>
    </section>
  );
}
