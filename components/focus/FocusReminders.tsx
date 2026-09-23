"use client";

import { useState } from "react";
import { Bell, Trash2, Plus } from "lucide-react";
import { focusApi, humanDuration, type Reminder } from "@/lib/api/focus";

const DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

/**
 * Reminder configuration.
 *
 * Stored and shown, never sent. This deployment has no push or email channel,
 * and the panel says so plainly rather than implying a notification will
 * arrive — a reminder the patient believes in but never receives is worse
 * than no reminder at all.
 */
export function FocusReminders({
  patientId,
  reminders,
  onChanged,
}: {
  patientId: number;
  reminders: Reminder[];
  onChanged: () => void;
}) {
  const [time, setTime] = useState("18:30");
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (d: number) =>
    setDays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort()));

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That did not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="fr">
      <header>
        <span className="eyebrow">REMINDERS</span>
        <p className="fine-print">
          Times are stored with your plan and shown here. This deployment has no push or
          email channel, so nothing is sent to your device.
        </p>
      </header>

      {reminders.length > 0 && (
        <ul className="fr-list">
          {reminders.map((r) => (
            <li key={r.id} className={r.enabled ? "" : "is-off"}>
              <Bell size={14} aria-hidden="true" />
              <strong className="tabular">{r.time_of_day}</strong>
              <span className="fr-days" aria-label="Days">
                {DAY_LABELS.map((label, i) => (
                  <i key={i} className={r.weekdays.includes(i) ? "is-on" : ""}>{label}</i>
                ))}
              </span>
              <span className="fr-target">{humanDuration(r.target_duration_s)}</span>
              <span className="mono fr-next">
                {r.next_occurrence
                  ? `next ${new Date(r.next_occurrence).toLocaleString([], {
                      weekday: "short", hour: "numeric", minute: "2-digit",
                    })}`
                  : "disabled"}
              </span>
              <button type="button" disabled={busy}
                      onClick={() => void run(() => focusApi.updateReminder(r.id, { enabled: !r.enabled }))}>
                {r.enabled ? "Disable" : "Enable"}
              </button>
              <button type="button" className="fr-del" aria-label="Remove reminder" disabled={busy}
                      onClick={() => void run(() => focusApi.deleteReminder(r.id))}>
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="fr-new">
        <label>
          <span className="mono">TIME</span>
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </label>
        <div className="fr-daypick" role="group" aria-label="Days of the week">
          {DAY_LABELS.map((label, i) => (
            <button key={i} type="button" aria-pressed={days.includes(i)}
                    className={days.includes(i) ? "is-on" : ""} onClick={() => toggle(i)}>
              {label}
            </button>
          ))}
        </div>
        <label>
          <span className="mono">TARGET</span>
          <input type="number" min={1} max={360} value={minutes}
                 onChange={(e) => setMinutes(Number(e.target.value) || 30)} />
        </label>
        <button type="button" className="button button-small" disabled={busy || days.length === 0}
                onClick={() => void run(() => focusApi.createReminder({
                  patient_id: patientId, time_of_day: time, weekdays: days,
                  target_duration_s: Math.max(60, minutes * 60),
                }))}>
          <Plus size={13} /> Add reminder
        </button>
      </div>

      {error && <p className="fine-print fr-error" role="alert">{error}</p>}
    </section>
  );
}
