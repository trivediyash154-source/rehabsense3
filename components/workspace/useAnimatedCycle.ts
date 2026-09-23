"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A 0→1 cycle driven by rAF, paused for reduced-motion (where it parks at a
 * legible mid-cycle position) and when the tab is hidden.
 */
export function useAnimatedCycle(seconds = 2.6) {
  const [value, setValue] = useState(0.4);
  const raf = useRef(0);

  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(0.5);
      return;
    }
    const start = performance.now();
    const step = (now: number) => {
      if (!document.hidden) setValue((((now - start) / 1000) % seconds) / seconds);
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [seconds]);

  return value;
}
