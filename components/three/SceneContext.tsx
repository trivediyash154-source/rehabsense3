"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type RenderTier = "low" | "high";

export type SceneStatus = {
  /** True only while the WebGL scene is actually mounted and drawing. */
  glActive: boolean;
  tier: RenderTier;
  /** Explicit user choice to run the lightweight visual system. */
  lite: boolean;
  reducedMotion: boolean;
  /** True when the page is visible; the scene parks its frameloop otherwise. */
  documentVisible: boolean;
  setLite: (value: boolean) => void;
  /** Called on context loss or a render error; permanently drops to Lite. */
  reportFailure: () => void;
};

const liteKey = "rehabsense-lite";

const SceneStatusContext = createContext<SceneStatus>({
  glActive: false,
  tier: "high",
  lite: false,
  reducedMotion: false,
  documentVisible: true,
  setLite: () => undefined,
  reportFailure: () => undefined,
});

export function useSceneStatus() {
  return useContext(SceneStatusContext);
}

/**
 * Owns every capability decision for the visual system, so the hero, the auth
 * pages and the WebGL layer all agree on which mode is running. Rendering
 * starts in Lite and only upgrades once the browser has been probed — that
 * way the product visual is present on the very first paint instead of
 * appearing late.
 */
export function SceneStatusProvider({ children }: { children: ReactNode }) {
  const [capable, setCapable] = useState(false);
  const [failed, setFailed] = useState(false);
  const [tier, setTier] = useState<RenderTier>("high");
  const [reducedMotion, setReducedMotion] = useState(false);
  const [documentVisible, setDocumentVisible] = useState(true);
  const [lite, setLiteState] = useState(false);

  useEffect(() => {
    try {
      setLiteState(localStorage.getItem(liteKey) === "true");
    } catch {
      // Storage may be blocked; Lite simply will not persist.
    }
  }, []);

  useEffect(() => {
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    const small = matchMedia("(max-width: 860px)");
    const nav = navigator as Navigator & { connection?: { saveData?: boolean } };

    const update = () => {
      const cores = navigator.hardwareConcurrency ?? 8;
      const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8;
      setTier(small.matches || cores <= 4 || memory <= 4 ? "low" : "high");
      setReducedMotion(motion.matches);

      let supported = false;
      try {
        const canvas = document.createElement("canvas");
        const gl = canvas.getContext("webgl2");
        supported = Boolean(gl);
        gl?.getExtension("WEBGL_lose_context")?.loseContext();
      } catch {
        supported = false;
      }
      setCapable(supported && !motion.matches && !nav.connection?.saveData);
    };

    const visibility = () => setDocumentVisible(!document.hidden);
    update();
    visibility();
    motion.addEventListener("change", update);
    small.addEventListener("change", update);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      motion.removeEventListener("change", update);
      small.removeEventListener("change", update);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);

  const setLite = useCallback((value: boolean) => {
    setLiteState(value);
    try {
      localStorage.setItem(liteKey, String(value));
    } catch {
      // Preference will not persist. Not worth surfacing.
    }
  }, []);

  const reportFailure = useCallback(() => setFailed(true), []);

  const value = useMemo<SceneStatus>(
    () => ({
      glActive: capable && !lite && !failed,
      tier,
      lite,
      reducedMotion,
      documentVisible,
      setLite,
      reportFailure,
    }),
    [capable, lite, failed, tier, reducedMotion, documentVisible, setLite, reportFailure],
  );

  return <SceneStatusContext.Provider value={value}>{children}</SceneStatusContext.Provider>;
}

/** Small control that lets anyone drop to the lightweight visual system. */
export function LiteToggle() {
  const { lite, setLite, glActive } = useSceneStatus();
  return (
    <button
      type="button"
      className={`lite-toggle ${lite ? "is-lite" : ""}`}
      onClick={() => setLite(!lite)}
      aria-pressed={lite}
      title={
        lite
          ? "Lite visuals are on. Switch to the full 3D scene."
          : "Switch to Lite visuals (no WebGL, lower power)."
      }
    >
      <span className="lite-dot" aria-hidden="true" />
      {lite ? "Lite visuals" : glActive ? "Full 3D" : "Lite visuals"}
    </button>
  );
}
