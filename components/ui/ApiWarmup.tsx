"use client";

import { useEffect } from "react";

let warmed = false;

/**
 * Start waking the API while the visitor reads the landing page.
 *
 * The API runs on a host that stops idle instances after five minutes, and a
 * stopped one takes several seconds to start. Asking it something cheap as
 * soon as the landing page is idle means it is usually awake by the time the
 * visitor reaches "Sign in". The request needs no database, sets nothing,
 * carries no identifier and its answer is discarded; the sign-in page still
 * says "Waking the RehabSense API…" if the API is not ready yet.
 */
export function ApiWarmup() {
  useEffect(() => {
    if (warmed) return;
    warmed = true;
    const warm = () => {
      void fetch("/api/auth/providers", { cache: "no-store" }).catch(() => {});
    };
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void) => number })
      .requestIdleCallback;
    if (idle) idle(warm);
    else setTimeout(warm, 1500);
  }, []);
  return null;
}
