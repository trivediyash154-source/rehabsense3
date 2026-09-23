"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceShell";
import { FocusPanel } from "@/components/focus/FocusPanel";
import { RecoveryAttendance } from "@/components/focus/RecoveryAttendance";
import { FocusAnalyticsStrip } from "@/components/focus/FocusAnalytics";
import { FocusReminders } from "@/components/focus/FocusReminders";
import { useData } from "@/lib/api/DataProvider";
import { useFocusTimer } from "@/lib/api/useFocusTimer";
import { focusApi, clock, humanDuration, type CalendarPayload } from "@/lib/api/focus";

/** First and last day of a month, as the API's date strings. */
function monthRange(anchor: Date) {
  const start = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { start: iso(start), end: iso(end) };
}

export default function FocusPage() {
  const { patient, mode } = useData();
  const patientId = patient?.id ?? null;
  const enabled = mode === "live" || mode === "empty";

  const timer = useFocusTimer(patientId, enabled);
  const [anchor, setAnchor] = useState(() => new Date());
  const [calendar, setCalendar] = useState<CalendarPayload | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);

  const range = useMemo(() => monthRange(anchor), [anchor]);

  const loadCalendar = useCallback(async () => {
    if (patientId == null || !enabled) return;
    try {
      setCalendar(await focusApi.calendar(patientId, range.start, range.end));
      setCalendarError(null);
    } catch (cause) {
      setCalendarError(cause instanceof Error ? cause.message : "Could not load attendance.");
    }
  }, [patientId, enabled, range.start, range.end]);

  useEffect(() => { void loadCalendar(); }, [loadCalendar]);

  // The attendance grid must reflect a block the moment it finishes.
  const refreshAll = useCallback(async () => {
    await timer.refresh();
    await loadCalendar();
  }, [timer, loadCalendar]);

  const today = timer.today;
  const analytics = calendar?.analytics ?? null;
  const monthLabel = anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const now = new Date();
  const canGoNext =
    anchor.getFullYear() < now.getFullYear() ||
    (anchor.getFullYear() === now.getFullYear() && anchor.getMonth() < now.getMonth());

  const lastFinished = useMemo(
    () => (today?.blocks ?? []).filter((b) => b.status === "COMPLETED").at(-1) ?? null,
    [today],
  );

  return (
    <>
      <WorkspaceHeader
        eyebrow="RECOVERY FOCUS"
        title="Set a target. Do the work. Watch the record build."
        lede="A focus block plans how long you intend to rehabilitate. The timer is kept by the server, so refreshing, navigating away or closing the tab cannot change what was actually worked."
        stats={[
          { label: "TODAY", value: today ? clock(today.summary.engaged_s) : "—" },
          {
            label: "TARGET",
            value: today?.summary.planned_s ? humanDuration(today.summary.planned_s) : "Not set",
            tone: "violet",
          },
          {
            label: "STREAK",
            value: analytics ? `${analytics.streak.current_days} d` : "—",
            tone: "teal",
          },
        ]}
        actions={
          <Link className="button button-small" href="/workspace/live">
            Open live lab <ArrowUpRight size={14} />
          </Link>
        }
      />

      {timer.error && (
        <p className="fine-print fx-warn" role="alert">{timer.error}</p>
      )}

      <FocusPanel
        today={today}
        block={timer.block}
        engagedS={timer.engagedS}
        remainingS={timer.remainingS}
        completionPct={timer.completionPct}
        busy={timer.busy}
        onCreate={(input) => void timer.create(input).then(loadCalendar)}
        onStart={(id) => void timer.start(id).then(loadCalendar)}
        onPause={(id) => void timer.pause(id)}
        onResume={(id) => void timer.resume(id)}
        onComplete={(id) => void timer.complete(id).then(loadCalendar)}
        onCancel={(id) => void timer.cancel(id).then(loadCalendar)}
      />

      {/* ---- end-of-session summary (§18) ---- */}
      {lastFinished && (
        <section className="fs">
          <span className="eyebrow">LAST COMPLETED BLOCK</span>
          <dl className="fs-grid">
            <div><dt className="mono">TARGET</dt><dd className="tabular">{clock(lastFinished.target_duration_s)}</dd></div>
            <div><dt className="mono">COMPLETED</dt><dd className="tabular">{clock(lastFinished.engaged_s)}</dd></div>
            <div><dt className="mono">ACTIVE MOVEMENT</dt><dd className="tabular">{clock(lastFinished.active_movement_s)}</dd></div>
            <div><dt className="mono">PAUSED</dt><dd className="tabular">{clock(lastFinished.paused_s)}</dd></div>
            <div><dt className="mono">EXERCISES</dt><dd>{lastFinished.exercise_count || "—"}</dd></div>
            <div><dt className="mono">REPETITIONS</dt><dd>{lastFinished.repetitions || "—"}</dd></div>
            <div>
              <dt className="mono">BEST ROM</dt>
              <dd>{lastFinished.best_rom_deg === null ? "—" : `${Math.round(lastFinished.best_rom_deg)}°`}</dd>
            </div>
            <div><dt className="mono">COMPLETION</dt><dd>{lastFinished.completion_pct}%</dd></div>
          </dl>
          <p className="fine-print">
            Repetitions and range come from the {lastFinished.session_count} recorded
            session{lastFinished.session_count === 1 ? "" : "s"} inside this block — the same
            figures the session pages and reports use.
          </p>
          <div className="fs-links">
            {lastFinished.session_ids.length > 0 && (
              <Link className="text-link" href="/workspace/sessions">
                View session <ArrowUpRight size={14} />
              </Link>
            )}
            <Link className="text-link" href="/workspace/progress">
              View progress <ArrowUpRight size={14} />
            </Link>
          </div>
        </section>
      )}

      <FocusAnalyticsStrip analytics={analytics} periodLabel={monthLabel} />

      {calendarError && <p className="fine-print fx-warn" role="alert">{calendarError}</p>}

      <RecoveryAttendance
        calendar={calendar}
        monthLabel={monthLabel}
        canGoNext={canGoNext}
        onPrev={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))}
        onNext={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))}
      />

      {patientId != null && (
        <FocusReminders
          patientId={patientId}
          reminders={today?.reminders ?? []}
          onChanged={() => void refreshAll()}
        />
      )}
    </>
  );
}
