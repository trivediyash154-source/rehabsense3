"use client";

import { useEffect } from "react";

/**
 * Route-level boundary for the workspace.
 *
 * This catches a crash inside a workspace page while leaving the shell and
 * navigation mounted, so a single broken panel cannot take the whole
 * application down to a blank screen. Stale-chunk errors self-recover once;
 * anything else is reported honestly rather than disguised as empty data.
 */

const STALE = /ChunkLoadError|Loading chunk|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;
const RELOAD_GUARD = "rehabsense-chunk-reload";

export default function WorkspaceError({
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
      if (sessionStorage.getItem(RELOAD_GUARD)) return;
      sessionStorage.setItem(RELOAD_GUARD, "1");
      window.location.reload();
    } catch {
      /* ignore */
    }
  }, [stale]);

  return (
    <section className="panel" style={{ margin: "2rem", padding: "2rem", maxWidth: "40rem" }}>
      <p className="eyebrow">{stale ? "Recovering" : "Panel error"}</p>
      <h1 style={{ margin: "0.5rem 0 0", fontSize: "1.4rem" }}>
        {stale ? "Reloading the latest build." : "This panel could not be displayed."}
      </h1>
      <p style={{ marginTop: "0.9rem", lineHeight: 1.6, opacity: 0.8 }}>
        {stale
          ? "This tab was running an earlier build of the interface. Refreshing to pick up the current one."
          : "The rest of the workspace is still usable. Recorded sessions are stored on the server and are not affected by this error."}
      </p>
      <div style={{ display: "flex", gap: "0.6rem", marginTop: "1.5rem", flexWrap: "wrap" }}>
        <button type="button" className="btn btn-primary" onClick={() => reset()}>
          Try again
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => {
            try {
              sessionStorage.removeItem(RELOAD_GUARD);
            } catch {
              /* ignore */
            }
            window.location.reload();
          }}
        >
          Reload page
        </button>
      </div>
      {error.digest ? (
        <p style={{ marginTop: "1.2rem", fontSize: "0.72rem", opacity: 0.55 }}>
          Reference: {error.digest}
        </p>
      ) : null}
    </section>
  );
}
