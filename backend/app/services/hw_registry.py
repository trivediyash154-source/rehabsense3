"""In-memory registry of active hardware-v2 sessions.

    packet -> DualSessionProcessor (worker thread) -> events
           -> broadcast (hw_* events) on /ws/live/{id}
           -> persist (worker thread, one transaction per packet)

Mirrors `live_registry.LiveRegistry` for v1 deliberately: same per-session
lock, same monotonic event sequence so a dashboard can discard stale
snapshots, same "persistence failure never stops the stream" rule.

Measured here (not estimated): DB write latency and broadcast latency per
packet, plus everything the processor measures per stage.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.core.logging import get_logger, log_event
from app.db.database import SessionLocal
from app.db.models.sensing import AssessmentKind
from app.realtime import live_events
from app.realtime.ws_manager import manager
from app.sensing.processor import DualSessionProcessor, Event, LatencyStats
from app.services import sensing_service

logger = get_logger("rehabsense.hw")


@dataclass
class HwSession:
    session_id: int
    processor: DualSessionProcessor
    device_pk: int | None = None
    calibration_id: int | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    seq: int = 0
    attached: bool = False
    retain_raw: bool | None = None   # decided once from the DB (research + LIVE + consent)
    recording_created: bool = False  # recordings start with the first stored samples
    model_version_ids: dict = field(default_factory=dict)


class HardwareRegistry:
    def __init__(self) -> None:
        self._sessions: dict[int, HwSession] = {}
        self._guard = asyncio.Lock()
        self.latency = LatencyStats()

    def get(self, session_id: int) -> HwSession | None:
        return self._sessions.get(session_id)

    async def open(self, session_id: int, exercise_type: str, hello, device_pk: int | None,
                   baseline_rom: dict | None, provenance: str) -> HwSession:
        async with self._guard:
            hw = self._sessions.get(session_id)
            if hw is None:
                processor = await asyncio.to_thread(
                    DualSessionProcessor, session_id, exercise_type, hello,
                    baseline_rom=baseline_rom, provenance=provenance,
                )
                hw = HwSession(session_id=session_id, processor=processor, device_pk=device_pk)
                self._sessions[session_id] = hw
                log_event(logger, "hw_session_opened", session_id=session_id,
                          device_id=hello.device_id, simulated=hello.simulated)
            return hw

    async def close(self, session_id: int) -> None:
        async with self._guard:
            self._sessions.pop(session_id, None)
        log_event(logger, "hw_session_closed", session_id=session_id)

    # ------------------------------------------------------------------ #

    def _stamp(self, hw: HwSession, events: list[Event]) -> None:
        for e in events:
            hw.seq += 1
            e.seq = hw.seq

    async def _dispatch(self, hw: HwSession, events: list[Event]) -> None:
        if not events:
            return
        t0 = time.perf_counter()
        for e in events:
            if e.broadcast:
                msg = live_events.from_processor_event(e)
                await manager.broadcast(hw.session_id, msg)
        self.latency.add("broadcast", (time.perf_counter() - t0) * 1000)
        to_persist = [e for e in events if e.persist]
        if to_persist:
            t1 = time.perf_counter()
            await asyncio.to_thread(self._persist, hw, to_persist)
            self.latency.add("db_write", (time.perf_counter() - t1) * 1000)

    def _persist(self, hw: HwSession, events: list[Event]) -> None:
        db = SessionLocal()
        try:
            for e in events:
                if e.persist == "calibration":
                    hw.calibration_id = sensing_service.persist_calibration(
                        db, hw.session_id, hw.device_pk, e.payload)
                elif e.persist == "marker":
                    sensing_service.persist_marker(db, hw.session_id, e.payload)
                elif e.persist == "calibration_invalidated":
                    sensing_service.invalidate_calibration(
                        db, hw.session_id, e.payload["sequence"], e.payload["reason"])
                elif e.persist == "raw_chunk":
                    if not hw.recording_created:
                        from app.db.models.device import Device

                        device = db.get(Device, hw.device_pk) if hw.device_pk else None
                        if device is not None:
                            sensing_service.ensure_recording(
                                db, hw.session_id, device, hw.processor.hello, hw.processor.provenance)
                            db.flush()
                        hw.recording_created = True
                    if hw.retain_raw is None:
                        hw.retain_raw = sensing_service.research_retention(db, hw.session_id)
                    sensing_service.persist_chunk(
                        db, hw.session_id, hw.device_pk, hw.calibration_id, e.payload,
                        retain=hw.retain_raw)
                elif e.persist == "activity":
                    ref = e.payload.get("model")
                    if ref not in hw.model_version_ids:
                        hw.model_version_ids[ref] = sensing_service.model_version_id(db, ref)
                    sensing_service.persist_activity(
                        db, hw.session_id, e.payload, hw.model_version_ids[ref])
                elif e.persist == "assessment":
                    sensing_service.persist_assessment(db, hw.session_id, e.payload)
                elif e.persist == "rep":
                    sensing_service.persist_rep(db, hw.session_id, e.payload)
            db.commit()
        except Exception:  # pragma: no cover - defensive
            db.rollback()
            logger.exception("failed to persist hardware events")
        finally:
            db.close()

    # ------------------------------------------------------------------ #

    async def attach(self, session_id: int, hello) -> None:
        hw = self._sessions[session_id]
        async with hw.lock:
            events = hw.processor.on_connect(hello)
            hw.attached = True
            self._stamp(hw, events)
        await self._dispatch(hw, events)

    async def detach(self, session_id: int) -> None:
        hw = self._sessions.get(session_id)
        if hw is None:
            return
        async with hw.lock:
            events = hw.processor.on_disconnect()
            hw.attached = False
            self._stamp(hw, events)
        await self._dispatch(hw, events)

    async def process(self, session_id: int, samples, arrival: float,
                      sent_ts: float | None = None) -> bool:
        """Returns False when the session is no longer live (it was ended)."""
        hw = self._sessions.get(session_id)
        if hw is None:
            return False
        async with hw.lock:
            events = await asyncio.to_thread(hw.processor.process, samples, arrival, sent_ts)
            self._stamp(hw, events)
        await self._dispatch(hw, events)
        return True

    async def recalibrate(self, session_id: int, reason: str) -> bool:
        hw = self._sessions.get(session_id)
        if hw is None:
            return False
        async with hw.lock:
            events = hw.processor.start_recalibration(reason)
            self._stamp(hw, events)
        await self._dispatch(hw, events)
        return True

    async def marker(self, session_id: int, payload: dict, server_now: float):
        """Map a user/server marker onto DEVICE_TIME and broadcast it.

        Returns (t_session, uncertainty_s); both None without a live stream.
        """
        hw = self._sessions.get(session_id)
        if hw is None:
            return None, None
        async with hw.lock:
            t, unc = hw.processor.map_server_time(server_now)
            ev = Event("hw_marker", {**payload, "t_session": t, "t_uncertainty_s": unc})
            self._stamp(hw, [ev])
        await self._dispatch(hw, [ev])
        return t, unc

    async def device_event(self, session_id: int, ev) -> None:
        hw = self._sessions.get(session_id)
        if hw is None:
            return
        async with hw.lock:
            events = hw.processor.device_event(ev)
            self._stamp(hw, events)
        await self._dispatch(hw, events)

    def calibration_phase(self, session_id: int) -> str | None:
        hw = self._sessions.get(session_id)
        return None if hw is None else hw.processor.calibrator.phase.value

    async def status(self, session_id: int, status: dict) -> None:
        hw = self._sessions.get(session_id)
        if hw is None:
            return
        async with hw.lock:
            events = hw.processor.on_status(status)
            self._stamp(hw, events)
        if hw.device_pk is not None:
            def _save():
                db = SessionLocal()
                try:
                    sensing_service.update_device_status(db, hw.device_pk, status)
                    db.commit()
                finally:
                    db.close()
            await asyncio.to_thread(_save)
        await self._dispatch(hw, events)

    async def finalize(self, session_id: int) -> dict | None:
        hw = self._sessions.get(session_id)
        if hw is None:
            return None
        async with hw.lock:
            tail = hw.processor.flush()
            summary = await asyncio.to_thread(hw.processor.finalize)
            # Reps closed during finalisation are persisted too.
            reps = [Event("hw_rep", r.as_dict() | {"kind": (
                        "gait_cycle" if summary["repetition_kind"] == "GAIT_CYCLE" else "repetition")},
                          broadcast=False, persist="rep")
                    for side in ("LEFT", "RIGHT") for r in hw.processor.reps[side]]
            self._stamp(hw, tail)
        await self._dispatch(hw, tail + reps)

        def _session_row():
            db = SessionLocal()
            try:
                sensing_service.persist_assessment(db, session_id, {
                    "t_start": 0.0, "t_end": summary["duration_s"],
                    "bilateral": summary["bilateral"], "force_motion": summary["force_motion"],
                    "movement_quality": summary["movement_quality"],
                }, kind=AssessmentKind.SESSION)
                db.commit()
            finally:
                db.close()
        await asyncio.to_thread(_session_row)
        summary["latency"]["db_write"] = self.latency.as_dict().get("db_write")
        summary["latency"]["broadcast"] = self.latency.as_dict().get("broadcast")
        return summary

    def stats(self) -> dict:
        return {
            "active_sessions": sorted(self._sessions),
            "server": self.latency.as_dict(),
            "sessions": {
                sid: {"pipeline": hw.processor.latency.as_dict(),
                      "stream": hw.processor.monitor.as_dict(),
                      "attached": hw.attached}
                for sid, hw in self._sessions.items()
            },
        }


hw_registry = HardwareRegistry()
