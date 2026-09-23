"use client";

import { useEffect } from "react";

/**
 * Last-resort boundary for crashes that escape every route boundary.
 *
 * Without this file Next.js renders its own bare "Application error: a
 * client-side exception has occurred" on a black page, which tells the user
 * nothing and offers no way out.
 *
 * The common cause in this project is a stale chunk: the browser is holding a
 * page from an earlier build whose hashed JS files no longer exist after a
 * rebuild, so every import 404s and hydration dies. That is recoverable by
 * reloading once, which is done here automatically -- guarded by sessionStorage
 * so a genuinely broken build can never turn into a reload loop.
 */

const STALE = /ChunkLoadError|Loading chunk|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;
const RELOAD_GUARD = "rehabsense-chunk-reload";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const stale = STALE.test(error.message) || STALE.test(error.name);

  useEffect(() => {
    if (!stale) return;
    try {
      // Reload at most once per tab. If the fresh build still fails, the user
      // sees the message below rather than an endless refresh.
      if (sessionStorage.getItem(RELOAD_GUARD)) return;
      sessionStorage.setItem(RELOAD_GUARD, "1");
      window.location.reload();
    } catch {
      /* private mode: fall through to the manual controls */
    }
  }, [stale]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#050912",
          color: "#e6ecf7",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          padding: "2rem",
        }}
      >
        <main style={{ maxWidth: "34rem", textAlign: "left" }}>
          <p
            style={{
              margin: 0,
              fontSize: "0.7rem",
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "#7c8db0",
            }}
          >
            {stale ? "Recovering" : "Error"}
          </p>
          <h1 style={{ margin: "0.6rem 0 0", fontSize: "1.6rem", fontWeight: 600 }}>
            {stale ? "Reloading the latest build." : "This screen failed to load."}
          </h1>
          <p style={{ margin: "0.9rem 0 0", lineHeight: 1.6, color: "#a7b5cd" }}>
            {stale
              ? "The page was running code from an earlier build. Refreshing now to pick up the current one."
              : "Something in the interface threw an error. Your recorded data is unaffected — it lives on the server, not in this page."}
          </p>

          <div style={{ display: "flex", gap: "0.6rem", marginTop: "1.6rem", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => reset()}
              style={{
                padding: "0.62rem 1.05rem",
                borderRadius: "0.5rem",
                border: "1px solid #0f7d8c",
                background: "#0f7d8c",
                color: "#fff",
                fontSize: "0.86rem",
                cursor: "pointer",
              }}
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => {
                try {
                  sessionStorage.removeItem(RELOAD_GUARD);
                } catch {
                  /* ignore */
                }
                window.location.href = "/workspace";
              }}
              style={{
                padding: "0.62rem 1.05rem",
                borderRadius: "0.5rem",
                border: "1px solid #1a2740",
                background: "transparent",
                color: "#e6ecf7",
                fontSize: "0.86rem",
                cursor: "pointer",
              }}
            >
              Back to workspace
            </button>
          </div>

          {error.digest ? (
            <p style={{ marginTop: "1.4rem", fontSize: "0.72rem", color: "#5f7192" }}>
              Reference: {error.digest}
            </p>
          ) : null}
        </main>
      </body>
    </html>
  );
}
