"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "./client";

/**
 * The backend's authoritative old-vs-new comparison.
 *
 * The receipt used to subtract two demo sessions in React. Every figure here
 * now comes from `/progress/compare`, so the receipt, the progress page and
 * any generated report quote the same delta — which is the whole point of a
 * document a clinician might act on.
 */
export type Delta = {
  label: string;
  unit: string;
  from: number | null;
  to: number | null;
  change: number | null;
  direction: "up" | "down" | "flat" | "unknown";
};

export type ComparisonBrief = {
  id: number;
  started_at: string | null;
  day_label: string | null;
  exercise_type: string;
  duration_s: number | null;
  rom_deg: number | null;
  symmetry_index_pct: number | null;
  cadence_spm: number | null;
  recovery_score: number | null;
  repetitions: number | null;
  confidence: number | null;
  confidence_band: string | null;
  coverage_pct: number | null;
  peak_angle_left_deg: number | null;
  peak_angle_right_deg: number | null;
  mode: string;
};

export type Comparison = {
  patient_id: number;
  baseline: ComparisonBrief;
  current: ComparisonBrief;
  deltas: Record<string, Delta>;
  trends: Record<string, { slope: number | null; direction: string; n: number }>;
  confidence: Record<string, unknown> | null;
  session_count: number;
  elapsed_days: number | null;
  summary: string[];
  analytics_version: string | null;
  responsible_use?: string;
};

export function useComparison(
  patientId: number | null,
  baselineId: number | null,
  currentId: number | null,
  enabled = true,
) {
  const [data, setData] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (patientId == null || !enabled) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (baselineId != null) params.set("baseline_session_id", String(baselineId));
    if (currentId != null) params.set("current_session_id", String(currentId));
    const query = params.toString() ? `?${params}` : "";
    try {
      setData(await apiFetch<Comparison>(`/patients/${patientId}/progress/compare${query}`));
    } catch (cause) {
      // A comparison that cannot be produced says so; it does not fall back to
      // subtracting whatever happens to be on screen.
      setData(null);
      setError(cause instanceof Error ? cause.message : "Could not build the comparison.");
    } finally {
      setLoading(false);
    }
  }, [patientId, baselineId, currentId, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  return { comparison: data, loading, error, reload: load };
}
