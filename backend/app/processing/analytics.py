"""SessionProcessor — the per-session analytics state machine.

Owns one pipeline per leg:

    calibrate -> filter -> fuse -> segment -> score

and emits events the realtime layer broadcasts and the persistence layer
writes. It performs no I/O itself, which is what makes it unit-testable
without a database or a socket.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.config import get_settings
from app.db.models.patient import Leg
from app.hardware.connection_state import ConnectionState, LegConnection
from app.hardware.protocol import Capability, Hello, Sample
from app.processing.calibration import CalibrationState, LegCalibrator
from app.processing.confidence import compute_confidence
from app.processing.recovery import compute_recovery
from app.processing.segmentation import (
    EXERCISE_MOVEMENT,
    GaitSegmenter,
    MovementType,
    RepetitionSegmenter,
)
from app.processing.signal_processing import LegTracker
from app.processing.symmetry import compute_symmetry

EventType = Literal[
    "calibration_status",
    "metric_update",
    "rep_event",
    "risk_flag",
    "connection_status",
    "signal_quality",
]


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any]
    # Assigned by LiveRegistry in creation order, so a client can discard a
    # snapshot that arrives after a newer one.
    seq: int = 0


@dataclass
class LegPipeline:
    leg: Leg
    tracker: LegTracker
    calibrator: LegCalibrator
    reps: RepetitionSegmenter
    gait: GaitSegmenter
    connection: LegConnection

    knee_angle: float | None = None
    rom_running: float = 0.0
    peak_angle: float = 0.0
    min_angle: float = 0.0
    _seen_any: bool = field(default=False, init=False)

    def peak_roms(self) -> list[float]:
        """Comparable per-repetition ROMs, used for symmetry."""
        return [r.rom for r in self.reps.completed]

    def stance_times(self) -> list[float]:
        return [c.stance_s for c in self.gait.cycles]


class SessionProcessor:
    """One instance per active session."""

    def __init__(
        self,
        session_id: int,
        exercise_type: str,
        operated_leg: Leg | None,
        *,
        started_at: float | None = None,
        expected_reps: int | None = None,
    ) -> None:
        settings = get_settings()
        self.settings = settings
        self.session_id = session_id
        self.exercise_type = exercise_type
        self.operated_leg = operated_leg
        self.movement = EXERCISE_MOVEMENT.get(exercise_type, MovementType.REPETITION)
        self.started_at = started_at if started_at is not None else time.time()
        self.expected_reps = expected_reps
        self.analytics_version = settings.analytics_version

        self.legs: dict[Leg, LegPipeline] = {
            leg: LegPipeline(
                leg=leg,
                tracker=LegTracker(
                    alpha=settings.complementary_alpha,
                    cutoff_hz=settings.lowpass_cutoff_hz,
                    sample_rate_hz=settings.sample_rate_hz,
                    fsr_stance_threshold=settings.fsr_stance_threshold,
                ),
                calibrator=LegCalibrator(window_seconds=settings.calibration_seconds),
                reps=RepetitionSegmenter(),
                gait=GaitSegmenter(),
                connection=LegConnection(leg=leg.value),
            )
            for leg in (Leg.LEFT, Leg.RIGHT)
        }

        # Session-relative clock, advanced by incoming sample timestamps.
        # Connection accounting and confidence must share this exact time base
        # as the analytics, or coverage silently computes as zero.
        self._clock: float = 0.0
        self._last_snapshot_t: float = -1.0
        self._risk_emitted: set[str] = set()
        self._degraded_announced = False
        # Calibration progress is emitted at most every 10%, not per sample:
        # at 100 Hz a 2.5 s window would otherwise produce ~250 events and
        # flood every dashboard queue before movement even starts.
        self._calibration_bucket: dict[Leg, int] = {}

    # ------------------------------------------------------------------ #
    # connection lifecycle
    # ------------------------------------------------------------------ #

    def on_hello(self, leg: Leg, hello: Hello) -> list[Event]:
        pipe = self.legs[leg]
        pipe.connection.connect(
            device_id=hello.device_id,
            firmware=hello.firmware_version,
            protocol=hello.protocol_version,
            capabilities=[c.value for c in hello.sensors],
            simulated=hello.simulated,
            now=self._clock,
        )
        return [self.connection_event()]

    def on_disconnect(self, leg: Leg) -> list[Event]:
        pipe = self.legs[leg]
        pipe.connection.disconnect(now=self._clock)
        # Calibration cannot complete for a leg that has gone away.
        if not pipe.calibrator.is_complete():
            pipe.calibrator.force_finalise()
        events = [self.connection_event()]
        risk = self._maybe_flag_coverage()
        if risk:
            events.append(risk)
        return events

    def connection_event(self) -> Event:
        left = self.legs[Leg.LEFT].connection
        right = self.legs[Leg.RIGHT].connection
        for pipe in self.legs.values():
            pipe.connection.tick(now=self._clock)
        return Event(
            "connection_status",
            {
                # Kept for backwards compatibility with the documented contract.
                "left_connected": left.state is ConnectionState.CONNECTED,
                "right_connected": right.state is ConnectionState.CONNECTED,
                # Richer state the workspace uses.
                "left": left.as_dict(self._clock),
                "right": right.as_dict(self._clock),
                "session_mode": self.session_mode,
            },
        )

    @property
    def session_mode(self) -> str:
        """SIMULATED, UNVERIFIED or UNKNOWN — declared, never guessed.

        v1 nodes cannot authenticate, so a non-simulated v1 stream is
        UNVERIFIED rather than LIVE: omitting the simulated flag is not
        evidence of physical hardware.
        """
        connected = [
            pipe.connection
            for pipe in self.legs.values()
            if pipe.connection.device_id is not None
        ]
        if not connected:
            return "UNKNOWN"
        if all(c.simulated for c in connected):
            return "SIMULATED"
        if any(c.simulated for c in connected):
            return "MIXED"
        return "UNVERIFIED"

    # ------------------------------------------------------------------ #
    # sample ingestion
    # ------------------------------------------------------------------ #

    def _session_time(self, ts: float) -> float:
        """Normalise a device timestamp to seconds since session start.

        Firmware may send epoch seconds or a device-relative counter; both are
        accepted, and only monotonicity is required.
        """
        return ts - self.started_at if ts > 1e6 else ts

    def process(self, leg: Leg, samples: list[Sample], seq: int | None = None) -> list[Event]:
        pipe = self.legs[leg]
        if samples:
            self._clock = max(self._clock, self._session_time(samples[-1].ts))
        # Per-sample sequence numbers are the loss signal; a packet-level
        # counter (if any node sends one) is ignored.
        first_seq = samples[0].seq if samples else None
        last_seq = samples[-1].seq if samples else None
        pipe.connection.observe_packet(first_seq, last_seq, len(samples), now=self._clock)
        events: list[Event] = []

        for sample in samples:
            t = self._session_time(sample.ts)
            fsr = sample.fsr if pipe.connection.fsr_available else None

            # --- calibration window ---
            if not pipe.calibrator.is_complete():
                before = pipe.calibrator.state
                pipe.calibrator.observe(sample.ts, sample.thigh, sample.shin)
                bucket = int(pipe.calibrator.progress * 10)
                if (
                    pipe.calibrator.state is not before
                    or bucket != self._calibration_bucket.get(leg)
                ):
                    self._calibration_bucket[leg] = bucket
                    events.append(self.calibration_event())
                if not pipe.calibrator.is_complete():
                    # Do not fuse orientation from uncalibrated samples.
                    continue

            thigh, shin = pipe.calibrator.apply(sample.thigh, sample.shin)
            angle, stance = pipe.tracker.update(sample.ts, thigh, shin, fsr)
            pipe.knee_angle = angle

            if not pipe._seen_any:
                pipe.peak_angle = pipe.min_angle = angle
                pipe._seen_any = True
            pipe.peak_angle = max(pipe.peak_angle, angle)
            pipe.min_angle = min(pipe.min_angle, angle)
            pipe.rom_running = pipe.peak_angle - pipe.min_angle

            # --- segmentation ---
            if self.movement is MovementType.GAIT:
                pipe.gait.update(t, stance)
            rep = pipe.reps.update(t, angle)
            if rep is not None:
                events.append(
                    Event(
                        "rep_event",
                        {
                            "leg": leg.value,
                            "rep_index": rep.index,
                            "t_offset": round(rep.end_t, 3),
                            "rom_deg": round(rep.rom, 2),
                            "peak_angle_deg": round(rep.peak_angle, 2),
                            "min_angle_deg": round(rep.min_angle, 2),
                            "duration_s": round(rep.duration, 3),
                            "smoothness": round(rep.smoothness, 3),
                            "quality_score": rep.quality,
                        },
                    )
                )

            # --- one snapshot per second of session time ---
            if t - self._last_snapshot_t >= 1.0:
                self._last_snapshot_t = t
                events.append(self.metric_event(t))

        for extra in (self._maybe_flag_coverage(), self._maybe_flag_rom_drop()):
            if extra:
                events.append(extra)
        return events

    # ------------------------------------------------------------------ #
    # derived metrics
    # ------------------------------------------------------------------ #

    def current_symmetry(self):
        left = self.legs[Leg.LEFT]
        right = self.legs[Leg.RIGHT]
        # Prefer per-repetition ROM; fall back to stance time for pure gait.
        if left.peak_roms() and right.peak_roms():
            return compute_symmetry(left.peak_roms(), right.peak_roms(), self.operated_leg, "peak_rom")
        if left.stance_times() and right.stance_times():
            return compute_symmetry(left.stance_times(), right.stance_times(), self.operated_leg, "stance_time")
        return compute_symmetry([], [], self.operated_leg, "peak_rom")

    def current_cadence(self) -> float | None:
        if self.movement is not MovementType.GAIT:
            return None
        cadences = [
            c for c in (self.legs[Leg.LEFT].gait.cadence_spm(), self.legs[Leg.RIGHT].gait.cadence_spm())
            if c is not None
        ]
        return round(sum(cadences) / len(cadences), 1) if cadences else None

    def current_rom(self) -> float | None:
        roms = [p.rom_running for p in self.legs.values() if p._seen_any]
        return round(max(roms), 2) if roms else None

    def _recovery(self, reported_pain: float | None = None):
        return compute_recovery(
            rom_deg=self.current_rom(),
            lsi_pct=self.current_symmetry().lsi_pct,
            cadence_spm=self.current_cadence(),
            compliance_ratio=None,
            reported_pain=reported_pain,
        )

    def _confidence(self, now: float | None = None):
        # `now` is session-relative seconds, matching the connection clock.
        now = now if now is not None else self._clock
        elapsed = max(1e-6, now)
        left, right = self.legs[Leg.LEFT], self.legs[Leg.RIGHT]
        corrections = [p.tracker.correction_ratio for p in self.legs.values() if p.tracker.sample_count]
        calibs = [p.calibrator.quality for p in self.legs.values() if p.calibrator.quality is not None]
        return compute_confidence(
            session_seconds=elapsed,
            connected_seconds_left=left.connection.live_connected_seconds(now),
            connected_seconds_right=right.connection.live_connected_seconds(now),
            packets_received=left.connection.packets_received + right.connection.packets_received,
            packets_dropped=left.connection.packets_dropped + right.connection.packets_dropped,
            correction_ratio=sum(corrections) / len(corrections) if corrections else 0.0,
            calibration_quality=sum(calibs) / len(calibs) if calibs else None,
            completed_reps=len(left.reps.completed) + len(right.reps.completed),
            expected_reps=self.expected_reps,
            # Gait spends most of each cycle in stance, so ZUPT fires often
            # by design; repetition work should be mostly free-swinging.
            expected_correction_ratio=0.62 if self.movement is MovementType.GAIT else 0.15,
        )

    def metric_event(self, t_offset: float | None = None) -> Event:
        symmetry = self.current_symmetry()
        recovery = self._recovery()
        confidence = self._confidence()
        left, right = self.legs[Leg.LEFT], self.legs[Leg.RIGHT]
        return Event(
            "metric_update",
            {
                "t_offset": round(t_offset if t_offset is not None else 0.0, 3),
                "left": {
                    "knee_angle_deg": None if left.knee_angle is None else round(left.knee_angle, 2),
                    "rom_running_deg": round(left.rom_running, 2),
                    "cadence_spm": left.gait.cadence_spm(),
                },
                "right": {
                    "knee_angle_deg": None if right.knee_angle is None else round(right.knee_angle, 2),
                    "rom_running_deg": round(right.rom_running, 2),
                    "cadence_spm": right.gait.cadence_spm(),
                },
                "rom_running_deg": self.current_rom(),
                "cadence_spm": self.current_cadence(),
                "symmetry_index_pct": symmetry.lsi_pct,
                "symmetry": symmetry.as_dict(),
                "recovery_score": recovery.as_dict(),
                "confidence": confidence.as_dict(),
            },
        )

    def calibration_event(self) -> Event:
        payload = {"session_id": self.session_id, "legs": {}}
        for leg, pipe in self.legs.items():
            payload["legs"][leg.value] = {
                "state": pipe.calibrator.state.value,
                "progress": round(pipe.calibrator.progress, 3),
                "quality": pipe.calibrator.quality,
            }
        states = [p.calibrator.state for p in self.legs.values()]
        connected = [p for p in self.legs.values() if p.connection.state is ConnectionState.CONNECTED]
        payload["complete"] = bool(connected) and all(
            p.calibrator.state is CalibrationState.COMPLETE for p in connected
        )
        payload["overall_progress"] = round(
            sum(p.calibrator.progress for p in connected) / len(connected), 3
        ) if connected else 0.0
        return Event("calibration_status", payload)

    # ------------------------------------------------------------------ #
    # risk flags
    # ------------------------------------------------------------------ #

    def _maybe_flag_coverage(self) -> Event | None:
        key = "bilateral_coverage"
        if key in self._risk_emitted:
            return None
        states = {leg: pipe.connection.state for leg, pipe in self.legs.items()}
        connected_any = any(s is ConnectionState.CONNECTED for s in states.values())
        missing = [leg.value for leg, s in states.items() if s is not ConnectionState.CONNECTED]
        if connected_any and missing and self.legs[Leg.LEFT].connection.first_connected_at:
            self._risk_emitted.add(key)
            return Event(
                "risk_flag",
                {
                    "severity": "WARNING",
                    "source_metric": "bilateral_coverage",
                    "message": (
                        f"{missing[0]} limb is not reporting — bilateral comparison is paused "
                        "and confidence is reduced for this period."
                    ),
                },
            )
        return None

    def _maybe_flag_rom_drop(self) -> Event | None:
        """Flag a within-session ROM regression across completed repetitions."""
        key = "rom_regression"
        if key in self._risk_emitted:
            return None
        for pipe in self.legs.values():
            reps = pipe.reps.completed
            if len(reps) < 6:
                continue
            early = sum(r.rom for r in reps[:3]) / 3
            late = sum(r.rom for r in reps[-3:]) / 3
            if early > 0 and late < early * (1 - self.settings.trend_deviation_band):
                self._risk_emitted.add(key)
                drop = (1 - late / early) * 100
                return Event(
                    "risk_flag",
                    {
                        "severity": "WARNING",
                        "source_metric": "rom",
                        "message": (
                            f"{pipe.leg.value} limb range dropped {drop:.0f}% between the first and "
                            "last repetitions — consider reviewing fatigue or technique."
                        ),
                    },
                )
        return None

    # ------------------------------------------------------------------ #
    # finalisation
    # ------------------------------------------------------------------ #

    def finalize(self, reported_pain: float | None = None, now: float | None = None) -> dict:
        now = now if now is not None else self._clock
        elapsed = max(0.0, now)
        self._clock = max(self._clock, elapsed)

        for pipe in self.legs.values():
            pipe.reps.flush(elapsed)
            if not pipe.calibrator.is_complete():
                pipe.calibrator.force_finalise()

        symmetry = self.current_symmetry()
        recovery = compute_recovery(
            rom_deg=self.current_rom(),
            lsi_pct=symmetry.lsi_pct,
            cadence_spm=self.current_cadence(),
            compliance_ratio=None,
            reported_pain=reported_pain,
        )
        confidence = self._confidence(now)

        left, right = self.legs[Leg.LEFT], self.legs[Leg.RIGHT]
        all_reps = left.reps.completed + right.reps.completed

        return {
            "analytics_version": self.analytics_version,
            "duration_s": round(elapsed, 2),
            "exercise_type": self.exercise_type,
            "movement_type": self.movement.value,
            "session_mode": self.session_mode,
            "rom_deg": self.current_rom(),
            "peak_angle_left_deg": round(left.peak_angle, 2) if left._seen_any else None,
            "peak_angle_right_deg": round(right.peak_angle, 2) if right._seen_any else None,
            "cadence_spm": self.current_cadence(),
            "symmetry": symmetry.as_dict(),
            "symmetry_index_pct": symmetry.lsi_pct,
            "recovery": recovery.as_dict(),
            "recovery_score": None if recovery.score is None else round(recovery.score, 1),
            "repetitions": len(all_reps),
            "repetitions_left": len(left.reps.completed),
            "repetitions_right": len(right.reps.completed),
            "mean_rep_quality": (
                round(sum(r.quality for r in all_reps) / len(all_reps), 3) if all_reps else None
            ),
            "gait_cycles": len(left.gait.cycles) + len(right.gait.cycles),
            "confidence": confidence.as_dict(),
            "data_quality": {
                "left": left.connection.as_dict(now),
                "right": right.connection.as_dict(now),
                "correction_ratio_left": round(left.tracker.correction_ratio, 3),
                "correction_ratio_right": round(right.tracker.correction_ratio, 3),
                "calibration_left": left.calibrator.state.value,
                "calibration_right": right.calibrator.state.value,
                "calibration_quality_left": left.calibrator.quality,
                "calibration_quality_right": right.calibrator.quality,
            },
            "disclaimer": (
                "All values are estimated decision-support indicators produced by "
                f"analytics {self.analytics_version}. Not a clinical measurement or diagnosis."
            ),
        }
