"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "./client";
import type { PatientRow } from "@/lib/demo-data";

/**
 * The clinician's patient landscape, assembled by the backend.
 *
 * Trend, latest score and the reason a record wants attention are all
 * computed server-side: the roster must agree with every other view, and one
 * request is cheaper than fetching each patient's history from the browser.
 */
export type ApiRosterRow = {
  id: number;
  name: string;
  initials: string;
  operated_leg: "LEFT" | "RIGHT" | null;
  weeks_post: number | null;
  sessions: number;
  unusable_sessions: number;
  trend: number[];
  score: number | null;
  latest_confidence: number | null;
  attention: PatientRow["attention"];
  reason: string;
};

/** Adapts a roster row into the shape the command centre already renders. */
export function toPatientRow(row: ApiRosterRow): PatientRow {
  return {
    id: String(row.id),
    initials: row.initials,
    // The real name: this clinician is authorised for this record, and the
    // backend has already refused any record they may not see.
    alias: row.name,
    operatedLeg: row.operated_leg ?? "LEFT",
    // 0 means "omit" downstream; the backend sends null when no
    // surgery date is recorded, and week zero is not a real reading.
    weeksPost: row.weeks_post ?? 0,
    sessions: row.sessions,
    trend: row.trend,
    score: row.score ?? 0,
    attention: row.attention,
    reason: row.reason,
  };
}

export function useRoster(enabled = true) {
  const [rows, setRows] = useState<ApiRosterRow[] | null>(null);
  const [loading, setLoading] = useState(enabled);

  useEffect(() => {
    if (!enabled) {
      setRows(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);

    apiFetch<{ items: ApiRosterRow[] }>("/patients/roster")
      .then((body) => {
        if (!cancelled) setRows(body.items);
      })
      .catch(() => {
        if (!cancelled) setRows(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { rows, loading };
}
