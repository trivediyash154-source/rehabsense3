"use client";

import { useState } from "react";
import { PhotoPlate } from "@/components/media/PhotoPlate";
import { BiomechanicsStage } from "./BiomechanicsStage";
import { useAnimatedCycle } from "./useAnimatedCycle";
import { exercises, exerciseLabels, type Exercise } from "@/lib/demo-data";
import { useData } from "@/lib/api/DataProvider";

/**
 * EXERCISE STUDIO
 *
 * Each exercise gets a full scene rather than a tile: a photographic plate,
 * an animated movement demonstration driven by the same biomechanics stage
 * the live lab uses, its movement phases, and whatever this demo set actually
 * recorded for it — including "not yet recorded", which several honestly are.
 */
export function ExerciseStudio() {
  const { sessions } = useData();
  const [selected, setSelected] = useState<Exercise>(exercises[0]);
  const cycle = useAnimatedCycle(selected.id === "SINGLE_LEG_BALANCE" ? 6 : 2.6);

  const recorded = sessions.filter((s) => selected.sessionIds.includes(s.id));
  const phaseIndex = Math.floor(cycle * selected.segments.length) % selected.segments.length;

  // Balance holds near-static; the others sweep a full cycle.
  const amplitude = selected.id === "SINGLE_LEG_BALANCE" ? 14 : selected.id === "SQUAT" ? 72 : 62;
  const wave = Math.pow(Math.sin(cycle * Math.PI), 2);

  return (
    <div className="studio">
      <nav className="studio-rail" aria-label="Exercises">
        {exercises.map((ex) => {
          const has = ex.sessionIds.length > 0;
          return (
            <button
              key={ex.id}
              type="button"
              className={selected.id === ex.id ? "is-active" : ""}
              aria-pressed={selected.id === ex.id}
              onClick={() => setSelected(ex)}
            >
              <span className="studio-rail-name">{ex.name}</span>
              <span className="studio-rail-focus">{ex.focus}</span>
              <span className={`studio-rail-count ${has ? "" : "is-empty"}`}>
                {has ? `${ex.sessionIds.length} recorded` : "none recorded"}
              </span>
            </button>
          );
        })}
      </nav>

      <div className="studio-scene">
        <div className="studio-hero">
          <PhotoPlate
            alt={`${selected.name} rehabilitation exercise`}
            caption={`${selected.name} · illustrative photography pending`}
            ratio="16 / 9"
          />
          <div className="studio-hero-copy">
            <span className="eyebrow">{selected.focus}</span>
            <h3>{selected.name}</h3>
            <p>{selected.description}</p>
          </div>
        </div>

        <div className="studio-demo">
          <div className="studio-demo-stage">
            <BiomechanicsStage
              state={{
                left: 8 + wave * amplitude,
                right: 8 + wave * amplitude * 0.86,
                phase: cycle,
                active: true,
              }}
              trails={selected.id !== "SINGLE_LEG_BALANCE"}
            />
            <span className="studio-demo-tag mono">CONCEPTUAL MOVEMENT DEMONSTRATION</span>
          </div>

          <div className="studio-demo-side">
            <span className="eyebrow">MOVEMENT PHASES</span>
            <ol className="studio-phases">
              {selected.segments.map((seg, i) => (
                <li key={seg} className={i === phaseIndex ? "is-active" : ""}>
                  <span className="mono">{String(i + 1).padStart(2, "0")}</span>
                  {seg}
                </li>
              ))}
            </ol>

            <span className="eyebrow">HOW TO PERFORM</span>
            <p className="studio-cue">{selected.cue}</p>
            <p className="fine-print">
              Guidance shown for demonstration. Exercise selection and progression are decisions
              for a qualified clinician — this prototype does not prescribe.
            </p>
          </div>
        </div>

        <div className="studio-history">
          <span className="eyebrow">RECORDED IN THIS DEMO SET</span>
          {recorded.length > 0 ? (
            <ul>
              {recorded.map((s) => (
                <li key={s.id}>
                  <span className="mono">{s.dayLabel}</span>
                  <strong>{s.label}</strong>
                  <span>ROM {s.rom}°</span>
                  <span>LSI {s.symmetry}%</span>
                  <span>{s.reps} reps</span>
                  <span className={`chip conf-${s.confidence.toLowerCase()}`}>{s.confidence}</span>
                </li>
              ))}
            </ul>
          ) : (
            /* A designed empty state — this exercise genuinely has no data. */
            <div className="studio-empty">
              <svg viewBox="0 0 120 60" aria-hidden="true">
                <path d="M6 46 C30 46 34 20 60 20 S90 46 114 46" className="empty-path" />
                <circle cx="60" cy="20" r="4" className="empty-node" />
              </svg>
              <p>
                No {exerciseLabels[selected.id].toLowerCase()} session exists in this demo set yet.
                When one is recorded, its range, symmetry and repetitions appear here.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
