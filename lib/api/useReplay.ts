"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "./client";
import type { RepEvent, RiskEvent } from "@/lib/demo-data";

/**
 * A session's recorded repetitions and events, from the backend.
 *
 * Repetitions are produced by the segmentation stage from actual movement
 * cycles. Generating a plausible-looking rep list in React would put a second,
 * fictional answer next to the real one -- and it is the sort of fiction that
 * looks entirely convincing, because the count and the timing are both
 * arithmetically reasonable.
 */
export type ApiRep = {
  ts: string;
  t_offset: number;
  leg: "LEFT" | "RIGHT";
  rep_index: number;
  rom_deg: number;
  peak_angle_deg: number | null;
  min_angle_deg: number | null;
  duration_s: number | null;
  smoothness: number | null;
  quality_score: number | null;
};

export type ApiReplayEvent = {
  t_offset?: number;
  severity?: string;
  message?: string;
  kind?: string;
};

export type ApiReplay = {
  session_id: number;
  duration_s: number | null;
  exercise_type: string;
  sample_interval_s: number | null;
  frames: { t_offset: number; left: number | null; right: number | null }[];
  repetitions: ApiRep[];
  events: ApiReplayEvent[];
};

export type ReplayData = {
  durationSeconds: number;
  reps: RepEvent[];
  risks: RiskEvent[];
  frames: ApiReplay["frames"];
  /** True once the backend has answered; false while loading or on failure. */
  loaded: boolean;
};

function toRep(rep: ApiRep): RepEvent {
  return {
    // A rep without an offset would put the playhead at NaN when jumped to.
    t: Number.isFinite(rep.t_offset) ? rep.t_offset : 0,
    leg: rep.leg,
    index: rep.rep_index,
    rom: Math.round(rep.rom_deg),
    // The backend scores quality 0..1; keep its number rather than deriving one.
    quality: rep.quality_score ?? 0,
  };
}

function toRisk(event: ApiReplayEvent): RiskEvent {
  const severity = event.severity === "WARNING" ? "WARNING" : "INFO";
  return {
    t: Math.round(event.t_offset ?? 0),
    severity,
    message: event.message ?? "Recorded event.",
  };
}

export function useReplay(sessionId: number | null, enabled = true): ReplayData {
  const [data, setData] = useState<ReplayData>({
    durationSeconds: 0, reps: [], risks: [], frames: [], loaded: false,
  });

  useEffect(() => {
    if (sessionId == null || !enabled) {
      setData({ durationSeconds: 0, reps: [], risks: [], frames: [], loaded: false });
      return;
    }
    let cancelled = false;

    apiFetch<ApiReplay>(`/sessions/${sessionId}/replay`)
      .then((body) => {
        if (cancelled) return;
        setData({
          durationSeconds: Math.round(body.duration_s ?? 0),
          reps: (body.repetitions ?? []).map(toRep),
          risks: (body.events ?? []).map(toRisk),
          frames: body.frames ?? [],
          loaded: true,
        });
      })
      .catch(() => {
        // Stays unloaded: the caller shows "no recorded repetitions" rather
        // than inventing a list.
        if (!cancelled) {
          setData({ durationSeconds: 0, reps: [], risks: [], frames: [], loaded: false });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, enabled]);

  return data;
}
