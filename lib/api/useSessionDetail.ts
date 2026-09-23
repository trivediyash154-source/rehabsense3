"use client";

import { useEffect, useState } from "react";
import { api } from "./client";
import { adaptContributions, type ApiContribution } from "./adapters";

/**
 * The backend's own scoring for one session.
 *
 * The recovery indicator is a weighted composite, and the weights and
 * normalisation live in the analytics layer. Recomputing the breakdown in
 * React would give a second answer that drifts from the stored one the moment
 * either changes, so the frontend asks for it instead.
 *
 * Returns null while loading, or when the session was never scored.
 */
export type SessionScoring = {
  contributions: ApiContribution[];
  recoveryValue: number | null;
  confidence: { percent: number; band: string; explanation: string } | null;
  analyticsVersion: string | null;
  mode: string | null;
};

export function useSessionDetail(sessionId: number | null, enabled = true) {
  const [scoring, setScoring] = useState<SessionScoring | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (sessionId == null || !enabled) {
      setScoring(null);
      return;
    }
    let cancelled = false;
    setLoading(true);

    api
      .session(sessionId)
      .then((detail) => {
        if (cancelled) return;
        const contributions = adaptContributions(detail.summary);
        setScoring(
          contributions
            ? {
                contributions,
                recoveryValue:
                  (detail.summary as { recovery?: { value?: number } } | null)?.recovery?.value ??
                  null,
                confidence: detail.confidence
                  ? {
                      percent: detail.confidence.percent,
                      band: detail.confidence.band,
                      explanation: detail.confidence.explanation,
                    }
                  : null,
                analyticsVersion: detail.analytics_version ?? null,
                mode: detail.mode ?? null,
              }
            : null,
        );
      })
      .catch(() => {
        // Not permitted, or not reachable. The caller falls back to its
        // documented illustrative breakdown and labels it as such.
        if (!cancelled) setScoring(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, enabled]);

  return { scoring, loading };
}
