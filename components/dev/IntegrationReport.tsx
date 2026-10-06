"use client";

import { publicWsOrigin } from "@/lib/config";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/client";

/**
 * Exercises each integration point in turn and reports what actually answered.
 *
 * Every row is a real request, not a configuration check: the point is to
 * separate "the code exists" from "the data flows" — the distinction that let
 * the workspace look healthy while showing fiction.
 */
type Status = "pending" | "ok" | "unavailable" | "failed";
type Row = { key: string; label: string; status: Status; detail: string };

const INITIAL: Row[] = [
  { key: "health", label: "REST API", status: "pending", detail: "" },
  { key: "auth", label: "Authentication", status: "pending", detail: "" },
  { key: "patients", label: "Patients", status: "pending", detail: "" },
  { key: "sessions", label: "Sessions", status: "pending", detail: "" },
  { key: "analytics", label: "Analytics (summary)", status: "pending", detail: "" },
  { key: "reps", label: "Repetitions", status: "pending", detail: "" },
  { key: "replay", label: "Replay", status: "pending", detail: "" },
  { key: "progress", label: "Progress", status: "pending", detail: "" },
  { key: "devices", label: "Devices", status: "pending", detail: "" },
  { key: "notifications", label: "Notifications", status: "pending", detail: "" },
  { key: "exercises", label: "Exercise catalogue", status: "pending", detail: "" },
  { key: "ws", label: "Live WebSocket", status: "pending", detail: "" },
];

function count(body: unknown): number {
  if (Array.isArray(body)) return body.length;
  const items = (body as { items?: unknown[] } | null)?.items;
  return Array.isArray(items) ? items.length : 0;
}

export function IntegrationReport() {
  const [rows, setRows] = useState<Row[]>(INITIAL);
  const [running, setRunning] = useState(false);

  const run = useCallback(async () => {
    setRunning(true);
    setRows(INITIAL);
    const set = (key: string, status: Status, detail: string) =>
      setRows((cur) => cur.map((r) => (r.key === key ? { ...r, status, detail } : r)));

    const probe = async (key: string, fn: () => Promise<string>) => {
      try {
        set(key, "ok", await fn());
      } catch (error) {
        const message = error instanceof Error ? error.message : "failed";
        // A 401 is a state ("not signed in"), not a broken subsystem.
        set(key, /401|Unauthor|sign in/i.test(message) ? "unavailable" : "failed", message);
      }
    };

    let patientId: number | null = null;
    let sessionId: number | null = null;

    await probe("health", async () => `status ${(await apiFetch<{ status: string }>("/health")).status}`);

    await probe("auth", async () => {
      const me = await apiFetch<{ user: { email: string; role: string } }>("/auth/me");
      return `${me.user.email} · ${me.user.role}`;
    });

    await probe("patients", async () => {
      const body = await apiFetch<{ items: { id: number }[] }>("/patients?limit=5");
      patientId = body.items[0]?.id ?? null;
      return `${body.items.length} visible`;
    });

    await probe("sessions", async () => {
      const body = await apiFetch<{ items: { id: number }[] }>("/sessions?limit=5");
      sessionId = body.items[0]?.id ?? null;
      return `${body.items.length} listed`;
    });

    await probe("analytics", async () => {
      if (sessionId == null) throw new Error("no session to inspect");
      const s = await apiFetch<{
        summary: { rom_deg: number | null; symmetry_index_pct: number | null } | null;
        analytics_version?: string | null;
      }>(`/sessions/${sessionId}`);
      const rom = s.summary?.rom_deg;
      return rom == null
        ? "session not scored (no usable movement)"
        : `ROM ${rom}° · LSI ${s.summary?.symmetry_index_pct ?? "—"}% · ${s.analytics_version ?? "?"}`;
    });

    await probe("reps", async () => {
      if (sessionId == null) throw new Error("no session to inspect");
      return `${(await apiFetch<unknown[]>(`/sessions/${sessionId}/reps`)).length} recorded`;
    });

    await probe("replay", async () => {
      if (sessionId == null) throw new Error("no session to inspect");
      const r = await apiFetch<{ frames: unknown[]; repetitions: unknown[] }>(`/sessions/${sessionId}/replay`);
      return `${r.frames.length} frames · ${r.repetitions.length} reps`;
    });

    await probe("progress", async () => {
      if (patientId == null) throw new Error("no patient to inspect");
      const p = await apiFetch<{ session_count: number; analytics_version: string | null }>(
        `/patients/${patientId}/progress`,
      );
      return `${p.session_count} sessions · ${p.analytics_version ?? "?"}`;
    });

    await probe("devices", async () => `${count(await apiFetch("/devices"))} known`);
    await probe("notifications", async () => `${count(await apiFetch("/notifications"))} listed`);
    await probe("exercises", async () => `${count(await apiFetch("/exercises"))} in catalogue`);

    await probe("ws", async () => {
      if (sessionId == null) throw new Error("no session to subscribe to");
      const t = await apiFetch<{ ticket: string }>("/auth/ws-ticket", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      });
      const origin = publicWsOrigin();
      return await new Promise<string>((resolve, reject) => {
        const socket = new WebSocket(`${origin}/ws/live/${sessionId}?ticket=${t.ticket}`);
        const timer = setTimeout(() => {
          socket.close();
          reject(new Error("no event within 4s"));
        }, 4000);
        socket.onmessage = (event) => {
          clearTimeout(timer);
          const kind = (JSON.parse(event.data) as { type?: string }).type ?? "event";
          socket.close();
          resolve(`connected · first event "${kind}"`);
        };
        socket.onerror = () => {
          clearTimeout(timer);
          reject(new Error("socket error"));
        };
      });
    });

    setRunning(false);
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  return (
    <main id="main" className="dev-report">
      <header>
        <span className="eyebrow">DEVELOPMENT DIAGNOSTIC</span>
        <h1>Integration status</h1>
        <p>
          Each row is a live request against the API, so a tick means data actually flowed.
          This route is not available in a production build.
        </p>
        <button type="button" className="button button-small" onClick={() => void run()} disabled={running}>
          {running ? "Running…" : "Run again"}
        </button>
      </header>

      <ol className="dev-rows">
        {rows.map((row) => (
          <li key={row.key} className={`dev-row is-${row.status}`}>
            <span className="dev-mark" aria-hidden="true">
              {row.status === "ok" ? "✓" : row.status === "pending" ? "·" : "×"}
            </span>
            <span className="dev-label">{row.label}</span>
            <span className="dev-detail mono">{row.detail || row.status}</span>
          </li>
        ))}
      </ol>
    </main>
  );
}
