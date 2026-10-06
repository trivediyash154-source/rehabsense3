"use client";

import { useState } from "react";
import { CloudOff, Database, LogIn, LoaderCircle, FlaskConical, Sparkles } from "lucide-react";
import Link from "next/link";
import { useData } from "@/lib/api/DataProvider";
import { api } from "@/lib/api/client";

/**
 * What the workspace shows when there is no recorded data to show.
 *
 * These states exist so a backend problem stays visible. The alternative --
 * quietly rendering the illustrative dataset -- produces a screen that looks
 * like a working product and reports numbers belonging to nobody.
 */
export function DataState() {
  const { mode, error, refresh, enterIllustrative } = useData();
  const [seeding, setSeeding] = useState(false);
  const [seedNote, setSeedNote] = useState<string | null>(null);

  /**
   * Populate this account by streaming real sessions through the simulator.
   *
   * Not a fixture: the backend runs the same simulator a developer runs from
   * a terminal, so the resulting sessions were calibrated, segmented and
   * scored by the analytics layer. Takes a couple of minutes because the
   * sensor data is generated in real time.
   */
  async function generate() {
    setSeeding(true);
    setSeedNote("Streaming sessions through the simulator — this takes a few minutes.");
    try {
      const result = await api.generateDemoData(3);
      setSeedNote(
        `Recorded ${result.sessions} sessions for ${result.patient_count} patients — ` +
          `${result.reps} repetitions, ${result.metrics} metric snapshots.`,
      );
      await refresh();
    } catch (cause) {
      setSeedNote(
        cause instanceof Error
          ? `Could not generate data: ${cause.message}`
          : "Could not generate data.",
      );
    } finally {
      setSeeding(false);
    }
  }

  if (mode === "loading") {
    return (
      <section className="ds" aria-live="polite">
        <LoaderCircle className="spin" size={22} aria-hidden="true" />
        <h2>Checking for recorded data…</h2>
      </section>
    );
  }

  if (mode === "offline") {
    return (
      <section className="ds" role="alert">
        <CloudOff size={24} aria-hidden="true" />
        <h2>The API is not responding.</h2>
        <p>
          Recorded data cannot be loaded, so none is shown. Nothing on this screen has been
          replaced with substitute figures.
        </p>
        {error && <p className="ds-detail mono">{error}</p>}
        <div className="ds-actions">
          <button type="button" className="button button-small" onClick={() => void refresh()}>
            Try again
          </button>
          <button type="button" className="button button-outline button-small" onClick={enterIllustrative}>
            <FlaskConical size={14} aria-hidden="true" />
            Explore illustrative data instead
          </button>
        </div>
        <span className="fine-print">
          Illustrative mode is a separate, clearly labelled mode. It is never entered
          automatically.
        </span>
      </section>
    );
  }

  if (mode === "unauthenticated") {
    return (
      <section className="ds">
        <LogIn size={24} aria-hidden="true" />
        <h2>Sign in to see recorded data.</h2>
        <p>The API is reachable, but this browser has no session.</p>
        <div className="ds-actions">
          <Link className="button button-small" href="/login?next=/workspace">
            Sign in
          </Link>
        </div>
      </section>
    );
  }

  // mode === "empty"
  return (
    <section className="ds">
      <Database size={24} aria-hidden="true" />
      <h2>No analysable sessions yet.</h2>
      <p>
        Once a session records movement from at least one limb, the workspace fills with that
        patient&apos;s own figures. Until then there is nothing to plot, and nothing is invented
        to fill the space.
      </p>
      <div className="ds-actions">
        {/* The generator is a development endpoint (/api/dev/*, disabled
            unless the API runs with DEBUG); production builds do not offer it. */}
        {process.env.NODE_ENV !== "production" && (
          <button type="button" className="button button-small" onClick={() => void generate()} disabled={seeding}>
            {seeding ? <LoaderCircle className="spin" size={14} /> : <Sparkles size={14} aria-hidden="true" />}
            {seeding ? "Recording sessions…" : "Generate demo sessions"}
          </button>
        )}
        <Link className="button button-outline button-small" href="/workspace/live">
          Record one yourself
        </Link>
        <button type="button" className="button button-outline button-small" onClick={enterIllustrative}>
          <FlaskConical size={14} aria-hidden="true" />
          Explore illustrative data
        </button>
      </div>

      {seedNote && <p className="fine-print ds-detail" aria-live="polite">{seedNote}</p>}

      {process.env.NODE_ENV !== "production" && (
        <span className="fine-print">
          Generated sessions are streamed through the sensor simulator into the same ingestion
          socket hardware uses, so they carry real analytics and are labelled as a simulated
          stream. Nothing is inserted directly.
        </span>
      )}
    </section>
  );
}

/** True when the workspace has data worth rendering a full page for. */
export function useHasData() {
  const { mode, sessions } = useData();
  return (mode === "live" || mode === "illustrative") && sessions.length > 0;
}
