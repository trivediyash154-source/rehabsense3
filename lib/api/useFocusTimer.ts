"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { focusApi, localDate, type FocusBlock, type TodayPayload } from "./focus";

/**
 * The Focus clock.
 *
 * The backend owns every duration; this hook only decides what to paint
 * between server reads. It keeps the last authoritative snapshot, projects
 * forward from the wall clock while a block is running, and re-reads the
 * server periodically so drift, a sleeping tab, a refresh or a backend
 * restart all resolve back to the truth. A paused block is never projected --
 * paused time is not worked time.
 */

const POLL_RUNNING_MS = 5_000;
const POLL_IDLE_MS = 30_000;
const TICK_MS = 250;

export type FocusTimerState = {
  today: TodayPayload | null;
  block: FocusBlock | null;
  /** Engaged seconds to display, projected from the last server snapshot. */
  engagedS: number;
  remainingS: number;
  completionPct: number;
  loading: boolean;
  error: string | null;
  busy: boolean;
};

export function useFocusTimer(patientId: number | null, enabled = true) {
  const [today, setToday] = useState<TodayPayload | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [, forceTick] = useState(0);

  // When the last snapshot was taken, so projection measures from there.
  const snapshotAt = useRef<number>(Date.now());

  const refresh = useCallback(async () => {
    if (patientId == null || !enabled) return null;
    try {
      const payload = await focusApi.today(patientId, localDate());
      snapshotAt.current = Date.now();
      setToday(payload);
      setError(null);
      return payload;
    } catch (cause) {
      // A failed read must not blank a running timer; keep the last snapshot
      // and say the connection is the problem.
      setError(cause instanceof Error ? cause.message : "Could not load today's focus.");
      return null;
    } finally {
      setLoading(false);
    }
  }, [patientId, enabled]);

  useEffect(() => {
    if (patientId == null || !enabled) {
      setToday(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    void refresh();
  }, [patientId, enabled, refresh]);

  const block = today?.active_block ?? null;
  const running = block?.status === "ACTIVE";

  // Re-read from the server: often while running, rarely when idle.
  useEffect(() => {
    if (patientId == null || !enabled) return;
    const every = running ? POLL_RUNNING_MS : POLL_IDLE_MS;
    const id = window.setInterval(() => void refresh(), every);
    return () => window.clearInterval(id);
  }, [patientId, enabled, running, refresh]);

  // Repaint between reads. This advances the *display* only.
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => forceTick((n) => n + 1), TICK_MS);
    return () => window.clearInterval(id);
  }, [running]);

  // A tab that was hidden gets a fresh read the moment it returns, rather
  // than projecting across however long the machine was asleep.
  useEffect(() => {
    if (patientId == null || !enabled) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [patientId, enabled, refresh]);

  const projected = (() => {
    if (!block) return { engagedS: 0, remainingS: 0, completionPct: 0 };
    const since = running ? (Date.now() - snapshotAt.current) / 1000 : 0;
    const engagedS = block.engaged_s + Math.max(0, since);
    const target = Math.max(1, block.target_duration_s);
    return {
      engagedS,
      remainingS: Math.max(0, target - engagedS),
      completionPct: Math.min(400, (engagedS / target) * 100),
    };
  })();

  const act = useCallback(
    async (fn: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await fn();
        await refresh();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "That action did not complete.");
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  return {
    today,
    block,
    ...projected,
    loading,
    error,
    busy,
    refresh,
    start: (id: number) => act(() => focusApi.start(id)),
    pause: (id: number) => act(() => focusApi.pause(id)),
    resume: (id: number) => act(() => focusApi.resume(id)),
    complete: (id: number) => act(() => focusApi.complete(id)),
    cancel: (id: number) => act(() => focusApi.cancel(id)),
    create: (input: { target_duration_s: number; exercise_type: string; notes?: string | null }) =>
      act(async () => {
        if (patientId == null) return;
        await focusApi.create({ patient_id: patientId, ...input });
      }),
  };
}
