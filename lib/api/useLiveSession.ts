"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, isPermanentFailure, liveSocketUrl } from "./client";

/**
 * Live session feed with automatic reconnect.
 *
 * A flaky link must degrade to "reconnecting", never a crashed tab — the same
 * requirement the wearable itself has. Backoff is capped so a long outage
 * does not hammer the server.
 */

export type ConnectionState = "CONNECTING" | "CONNECTED" | "DEGRADED" | "DISCONNECTED";

export type LiveLegState = {
  state: ConnectionState;
  device_id: string | null;
  simulated: boolean;
  capabilities: string[];
  fsr_available: boolean;
  packets_received: number;
  packets_dropped: number;
  connected_seconds: number;
};

export type LiveMetrics = {
  t_offset: number;
  left: { knee_angle_deg: number | null; rom_running_deg: number | null; cadence_spm: number | null };
  right: { knee_angle_deg: number | null; rom_running_deg: number | null; cadence_spm: number | null };
  rom_running_deg: number | null;
  cadence_spm: number | null;
  symmetry_index_pct: number | null;
  recovery_score: { value: number; contributions: unknown[] } | null;
  confidence: { percent: number; band: string; explanation: string } | null;
};

export type LiveRep = {
  leg: string;
  rep_index: number;
  rom_deg: number;
  quality_score: number;
  t_offset: number;
};

export type LiveCalibration = {
  complete: boolean;
  overall_progress: number;
  legs: Record<string, { state: string; progress: number; quality: number | null }>;
};

export type LiveRisk = { severity: string; message: string; source_metric?: string };

export type LiveSessionState = {
  socket: "connecting" | "open" | "reconnecting" | "closed";
  sessionMode: string;
  left: LiveLegState | null;
  right: LiveLegState | null;
  calibration: LiveCalibration | null;
  metrics: LiveMetrics | null;
  reps: LiveRep[];
  risks: LiveRisk[];
  lastEventAt: number | null;
  /** Highest event sequence applied; older arrivals are ignored. */
  lastSeq: number;
};

const EMPTY: LiveSessionState = {
  socket: "closed",
  sessionMode: "UNKNOWN",
  left: null,
  right: null,
  calibration: null,
  metrics: null,
  reps: [],
  risks: [],
  lastEventAt: null,
  lastSeq: 0,
};

export function useLiveSession(sessionId: number | null, enabled = true) {
  const [state, setState] = useState<LiveSessionState>(EMPTY);
  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const closedRef = useRef(false);
  // connect() and scheduleReconnect() are mutually recursive; a ref breaks the
  // cycle without disabling the dependency lint.
  const connectRef = useRef<() => void>(() => undefined);

  const scheduleReconnect = useCallback(() => {
    if (closedRef.current) return;
    attemptRef.current += 1;
    // 1s, 2s, 4s … capped at 15s so a long outage does not hammer the server.
    const delay = Math.min(15000, 1000 * 2 ** (attemptRef.current - 1));
    setState((s) => ({ ...s, socket: "reconnecting" }));
    timerRef.current = window.setTimeout(() => connectRef.current(), delay);
  }, []);

  const connect = useCallback(async () => {
    if (sessionId == null || !enabled) return;
    closedRef.current = false;

    setState((s) => ({ ...s, socket: attemptRef.current === 0 ? "connecting" : "reconnecting" }));

    // The socket is authorised by a short-lived ticket rather than the session
    // cookie, which the browser will not attach to a cross-origin WebSocket.
    // A fresh one is fetched per attempt so a reconnect after a long outage
    // never presents an expired ticket.
    let ticket: string;
    try {
      ticket = (await api.liveTicket(sessionId)).ticket;
    } catch (error) {
      // Not signed in, or not permitted to view this session: retrying will
      // not change either, so stop rather than loop against a closed door.
      // A network error or a gateway answering while the API wakes is
      // temporary, so that is retried with the same backoff as a dropped
      // socket.
      if (isPermanentFailure(error)) {
        if (!closedRef.current) setState((s) => ({ ...s, socket: "closed" }));
      } else {
        scheduleReconnect();
      }
      return;
    }
    if (closedRef.current) return;

    let socket: WebSocket;
    try {
      socket = new WebSocket(liveSocketUrl(sessionId, ticket));
    } catch {
      scheduleReconnect();
      return;
    }
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setState((s) => ({ ...s, socket: "open" }));
    };

    socket.onmessage = (event) => {
      let message: { type: string } & Record<string, unknown>;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      setState((s) => {
        // Events carry a per-session sequence assigned in creation order. A
        // snapshot that arrives after a newer one is discarded: applying it
        // would leave the UI showing an older truth (a streaming leg marked
        // disconnected, say) until the next event happened to arrive.
        const seq = typeof message.seq === "number" ? message.seq : 0;
        if (seq > 0 && seq <= s.lastSeq) return s;

        const next: LiveSessionState = {
          ...s,
          lastEventAt: Date.now(),
          lastSeq: seq > 0 ? seq : s.lastSeq,
        };
        switch (message.type) {
          case "connection_status":
            next.left = message.left as LiveLegState;
            next.right = message.right as LiveLegState;
            next.sessionMode = (message.session_mode as string) ?? s.sessionMode;
            break;
          case "calibration_status":
            next.calibration = message as unknown as LiveCalibration;
            break;
          case "metric_update":
            next.metrics = message as unknown as LiveMetrics;
            break;
          case "rep_event":
            next.reps = [message as unknown as LiveRep, ...s.reps].slice(0, 60);
            break;
          case "risk_flag":
            next.risks = [message as unknown as LiveRisk, ...s.risks].slice(0, 20);
            break;
          default:
            break; // heartbeat, session_status, and any future type
        }
        return next;
      });
    };

    socket.onclose = () => {
      if (closedRef.current) return;
      scheduleReconnect();
    };
    socket.onerror = () => socket.close();
  }, [sessionId, enabled, scheduleReconnect]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (sessionId == null || !enabled) {
      setState(EMPTY);
      return;
    }
    connect();
    return () => {
      closedRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
      attemptRef.current = 0;
    };
  }, [sessionId, enabled, connect]);

  return state;
}
