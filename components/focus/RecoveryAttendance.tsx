"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  clock,
  clockTime,
  humanDuration,
  type CalendarPayload,
  type DaySummary,
} from "@/lib/api/focus";
import { exerciseLabels, type ExerciseType } from "@/lib/demo-data";

/**
 * RECOVERY ATTENDANCE
 *
 * A month of rehabilitation days, each carrying its own adherence state. Not
 * a generic habit grid: a cell encodes planned minutes against worked
 * minutes, and selecting one opens that day's real blocks and the times they
 * happened.
 */

const STATE_LABEL: Record<DaySummary["state"], string> = {
  met: "Target met",
  exceeded: "Target exceeded",
  partial: "Partial",
  planned: "Planned, not worked",
  none: "No plan",
  future: "Upcoming",
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function RecoveryAttendance({
  calendar,
  monthLabel,
  onPrev,
  onNext,
  canGoNext,
}: {
  calendar: CalendarPayload | null;
  monthLabel: string;
  onPrev: () => void;
  onNext: () => void;
  canGoNext: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  const { cells, byDate } = useMemo(() => {
    const days = calendar?.days ?? [];
    const map = new Map(days.map((d) => [d.date, d]));
    if (days.length === 0) return { cells: [] as (DaySummary | null)[], byDate: map };

    // Pad to the Monday before the first day so columns line up with weekdays.
    const first = new Date(`${days[0].date}T00:00:00`);
    const lead = (first.getDay() + 6) % 7;
    return { cells: [...Array<null>(lead).fill(null), ...days], byDate: map };
  }, [calendar]);

  const chosen = selected ? byDate.get(selected) ?? null : null;
  const worked = (calendar?.days ?? []).filter((d) => d.engaged_s > 0).length;

  return (
    <section className="ra">
      <header className="ra-head">
        <div>
          <span className="eyebrow">RECOVERY ATTENDANCE</span>
          <h3>{monthLabel}</h3>
        </div>
        <div className="ra-nav">
          <button type="button" onClick={onPrev} aria-label="Previous month">
            <ChevronLeft size={16} />
          </button>
          <button type="button" onClick={onNext} disabled={!canGoNext} aria-label="Next month">
            <ChevronRight size={16} />
          </button>
        </div>
      </header>

      {cells.length === 0 ? (
        <p className="fine-print">No recovery sessions yet. Set your first target above.</p>
      ) : (
        <>
          <div className="ra-weekdays" aria-hidden="true">
            {WEEKDAYS.map((d) => <span key={d}>{d}</span>)}
          </div>

          <div className="ra-grid" role="grid" aria-label="Recovery attendance">
            {cells.map((day, i) =>
              day === null ? (
                <span key={`pad-${i}`} className="ra-cell is-pad" aria-hidden="true" />
              ) : (
                <button
                  key={day.date}
                  type="button"
                  role="gridcell"
                  className={`ra-cell st-${day.state} ${selected === day.date ? "is-selected" : ""}`}
                  aria-label={`${day.date}: ${STATE_LABEL[day.state]}${
                    day.block_count ? `, ${clock(day.engaged_s)} of ${humanDuration(day.planned_s)}` : ""
                  }`}
                  onClick={() => setSelected(selected === day.date ? null : day.date)}
                >
                  <span className="ra-num">{Number(day.date.slice(-2))}</span>
                  {day.block_count > 1 && <i className="ra-multi" aria-hidden="true">{day.block_count}</i>}
                </button>
              ),
            )}
          </div>

          <ul className="ra-legend" aria-hidden="true">
            {(["met", "exceeded", "partial", "planned", "none"] as const).map((s) => (
              <li key={s}><i className={`st-${s}`} />{STATE_LABEL[s]}</li>
            ))}
          </ul>

          <p className="fine-print">
            {worked} day{worked === 1 ? "" : "s"} with recorded movement this period.
            A day is marked met at {calendar?.adherence_threshold_pct ?? 80}% of its own plan.
          </p>
        </>
      )}

      {/* ---- selected day (§10) ---- */}
      {chosen && (
        <div className="ra-day">
          <header>
            <strong>
              {new Date(`${chosen.date}T00:00:00`).toLocaleDateString(undefined, {
                day: "numeric", month: "long",
              })}
            </strong>
            <span className={`ra-chip st-${chosen.state}`}>{STATE_LABEL[chosen.state]}</span>
          </header>

          {chosen.block_count === 0 ? (
            <p className="fine-print">No rehabilitation was planned for this day.</p>
          ) : (
            <>
              <dl className="ra-day-facts">
                <div><dt className="mono">TARGET</dt><dd>{humanDuration(chosen.planned_s)}</dd></div>
                <div><dt className="mono">COMPLETED</dt><dd className="tabular">{clock(chosen.engaged_s)}</dd></div>
                <div><dt className="mono">SESSIONS</dt><dd>{chosen.block_count}</dd></div>
                <div><dt className="mono">EXERCISES</dt><dd>{chosen.exercises.length || "—"}</dd></div>
                <div><dt className="mono">REPETITIONS</dt><dd>{chosen.repetitions || "—"}</dd></div>
                <div><dt className="mono">COMPLETION</dt><dd>{chosen.completion_pct}%</dd></div>
              </dl>

              {/* ---- when it happened (§11) ---- */}
              <div className="ra-timeline">
                <span className="eyebrow">WHEN</span>
                <div className="ra-track" aria-hidden="true">
                  {[0, 6, 12, 18, 24].map((h) => (
                    <i key={h} style={{ left: `${(h / 24) * 100}%` }} data-hour={`${h}:00`} />
                  ))}
                </div>
                <ul>
                  {chosen.entries.map((e) => (
                    <li key={e.focus_id}>
                      <span className="mono ra-when">
                        {e.start_minute !== null ? clockTime(e.start_minute) : "—"}
                      </span>
                      <span className="ra-bar-wrap">
                        <i
                          className="ra-bar"
                          style={{
                            // Width in proportion to the day's longest block,
                            // so short and long sessions stay distinguishable.
                            width: `${Math.max(6, (e.engaged_s / Math.max(...chosen.entries.map((x) => x.engaged_s), 1)) * 100)}%`,
                          }}
                        />
                      </span>
                      <span className="ra-meta">
                        {clock(e.engaged_s)} ·{" "}
                        {exerciseLabels[e.exercise_type as ExerciseType] ?? e.exercise_type}
                        {e.repetitions > 0 && ` · ${e.repetitions} reps`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
