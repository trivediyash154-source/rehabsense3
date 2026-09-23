"use client";

import { Flame } from "lucide-react";
import { clockTime, type FocusAnalytics as Analytics } from "@/lib/api/focus";
import { exerciseLabels, type ExerciseType } from "@/lib/demo-data";

/**
 * Period summary, computed server-side.
 *
 * Rehabilitation language throughout: minutes worked against minutes planned,
 * not "calories" or "workouts". Every figure arrives from `/focus/history`.
 */
export function FocusAnalyticsStrip({ analytics, periodLabel }: {
  analytics: Analytics | null;
  periodLabel: string;
}) {
  if (!analytics) return null;
  const s = analytics.streak;
  const noPlan = analytics.blocks_planned === 0;

  return (
    <section className="fa">
      <header className="fa-head">
        <span className="eyebrow">RECOVERY RHYTHM · {periodLabel.toUpperCase()}</span>
        <span className={`fa-streak ${s.current_days > 0 ? "is-on" : ""}`} title={s.rule}>
          <Flame size={14} aria-hidden="true" />
          {s.current_days} DAY{s.current_days === 1 ? "" : "S"} OF CONSISTENCY
        </span>
      </header>

      {noPlan ? (
        <p className="fine-print">
          No recovery sessions planned in this period yet. Set a target to begin building a record.
        </p>
      ) : (
        <>
          <dl className="fa-grid">
            <div>
              <dt className="mono">PLANNED</dt>
              <dd>{analytics.planned_minutes}<em> min</em></dd>
            </div>
            <div>
              <dt className="mono">COMPLETED</dt>
              <dd>{analytics.completed_minutes}<em> min</em></dd>
            </div>
            <div>
              <dt className="mono">MOVEMENT RECORDED</dt>
              <dd>{analytics.active_movement_minutes}<em> min</em></dd>
            </div>
            <div>
              <dt className="mono">GOAL COMPLETION</dt>
              <dd>
                {analytics.goal_completion_rate_pct === null
                  ? "—"
                  : <>{analytics.goal_completion_rate_pct}<em>%</em></>}
              </dd>
            </div>
            <div>
              <dt className="mono">DAYS WORKED</dt>
              <dd>{analytics.days_worked}<em> / {analytics.days_with_a_plan} planned</em></dd>
            </div>
            <div>
              <dt className="mono">REPETITIONS</dt>
              <dd>{analytics.repetitions || "—"}</dd>
            </div>
            <div>
              <dt className="mono">TYPICAL BLOCK</dt>
              <dd>
                {analytics.mean_block_minutes === null
                  ? "—"
                  : <>{analytics.mean_block_minutes}<em> min</em></>}
              </dd>
            </div>
            <div>
              <dt className="mono">USUAL START</dt>
              <dd>
                {analytics.mean_start_minute === null
                  ? "—"
                  : clockTime(analytics.mean_start_minute)}
              </dd>
            </div>
          </dl>

          <p className="fine-print fa-rule">
            {s.rule} Longest run so far: {s.best_days} day{s.best_days === 1 ? "" : "s"}.
            {analytics.most_common_exercise && (
              <>
                {" "}Most frequent exercise:{" "}
                {exerciseLabels[analytics.most_common_exercise as ExerciseType] ??
                  analytics.most_common_exercise}.
              </>
            )}
          </p>
        </>
      )}
    </section>
  );
}
