"use client";

import dynamic from "next/dynamic";
import { Component, useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useTheme } from "@/components/ui/Providers";
import { useSceneStatus } from "./SceneContext";

/** Loaded only in the browser, after first paint. Never blocks FCP. */
const KineticScene = dynamic(() => import("./KineticScene"), {
  ssr: false,
  loading: () => null,
});

class SceneBoundary extends Component<
  { children: ReactNode; onFailure: () => void },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFailure();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export type SceneMode = "hero" | "gap" | "flow" | "features" | "score" | "contact";

const MODES: SceneMode[] = ["hero", "gap", "flow", "features", "score", "contact"];

function isMode(value: string | null): value is SceneMode {
  return value !== null && (MODES as string[]).includes(value);
}

export function SceneLayer() {
  const { theme } = useTheme();
  const pathname = usePathname();
  const { glActive, tier, documentVisible, reportFailure } = useSceneStatus();
  const [mode, setMode] = useState<SceneMode>("hero");

  // Scroll-driven scene modes. Sections declare their own atmosphere.
  useEffect(() => {
    setMode(pathname === "/" ? "hero" : pathname === "/contact" ? "contact" : "features");

    const observer = new IntersectionObserver(
      (entries) => {
        // Choose the most visible declared section, so fast scrolls settle
        // on one mode instead of flickering between neighbours.
        let best: { ratio: number; mode: SceneMode } | null = null;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const value = entry.target.getAttribute("data-scene");
          if (!isMode(value)) continue;
          if (!best || entry.intersectionRatio > best.ratio) {
            best = { ratio: entry.intersectionRatio, mode: value };
          }
        }
        if (best) setMode(best.mode);
      },
      { rootMargin: "-18% 0px -45% 0px", threshold: [0.05, 0.25, 0.5, 0.75] },
    );

    document.querySelectorAll("[data-scene]").forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [pathname]);

  return (
    <div className={`scene-layer mode-${mode} ${glActive ? "gl-on" : "gl-off"}`} aria-hidden="true">
      {/* CSS aurora. Always rendered: it is the reduced-motion and no-WebGL
          experience, and it underpaints the canvas when WebGL is live. */}
      <div className="scene-fallback">
        <div className="aurora aurora-one" />
        <div className="aurora aurora-two" />
        <div className="aurora aurora-three" />
        <div className="fallback-strands">
          <span />
          <span />
          <span />
        </div>
        <div className="fallback-grid" />
      </div>
      {glActive && (
        <SceneBoundary onFailure={reportFailure}>
          <KineticScene
            theme={theme}
            tier={tier}
            running={documentVisible}
            mode={mode}
            showProduct={pathname === "/"}
            onFailure={reportFailure}
          />
        </SceneBoundary>
      )}
      <div className="scene-scrim" />
      <div className="scene-vignette" />
      <div className="scene-grain" />
    </div>
  );
}
