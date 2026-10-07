"use client";

import { useEffect } from "react";

let warmed = false;

/**
 * Start waking the API while the visitor reads the landing page.
 *
 * The API runs on a host that stops idle instances after five minutes, and a
 * stopped one takes several seconds to start. Asking it something cheap as
 * soon as the landing page mounts gives the boot a head start before the
 * visitor reaches "Sign in". The request needs no database, sets nothing,
 * carries no identifier and its answer is discarded; the sign-in page still
 * says "Waking the RehabSense API…" if the API is not ready yet.
 */
export function ApiWarmup() {
  useEffect(() => {
    if (warmed) return;
    warmed = true;
    // Immediately, not on idle: the landing page's 3D scene keeps the main
    // thread busy, and an idle callback fired ~9 s late in a live measurement.
    // A booting instance does not take other requests, so the earlier the
    // boot starts, the more of it is over before "Sign in".
    void fetch("/api/auth/providers", { cache: "no-store" }).catch(() => {});
  }, []);
  return null;
}
