"""Launches the sensor simulator as a client of the real ingestion socket.

The Live Lab needs a sensor source, and a browser cannot start one. Rather
than inventing a second, privileged ingestion path for the UI, this spawns the
*same* simulator a developer runs from a terminal: it connects to
`/ws/ingest/{session_id}` and speaks the documented protocol. Everything
downstream -- calibration, fusion, segmentation, persistence, the live
broadcast -- is exercised exactly as physical hardware would exercise it.

Constraints are deliberate: one run per session, a bounded duration, and a
hard cap on concurrent processes, because this endpoint starts an OS process
on behalf of an authenticated caller.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass

from app.core.logging import get_logger, log_event

logger = get_logger("rehabsense.simrunner")

MAX_CONCURRENT = 8
MAX_DURATION_S = 900
DEFAULT_DURATION_S = 60


@dataclass
class Run:
    session_id: int
    process: subprocess.Popen
    scenario: str


_runs: dict[int, Run] = {}
_lock = threading.Lock()


def _reap() -> None:
    """Drop finished processes so the concurrency cap reflects reality."""
    for session_id in [s for s, r in _runs.items() if r.process.poll() is not None]:
        _runs.pop(session_id, None)


def is_running(session_id: int) -> bool:
    with _lock:
        _reap()
        return session_id in _runs


def active_count() -> int:
    with _lock:
        _reap()
        return len(_runs)


def start(
    session_id: int,
    *,
    host: str,
    scenario: str = "ASYMMETRY",
    operated_leg: str = "LEFT",
    exercise: str = "WALK",
    duration_s: int = DEFAULT_DURATION_S,
    fsr: bool = True,
    seed: int | None = None,
) -> Run:
    """Start a simulated stream for one session. Raises on refusal."""
    duration = max(5, min(int(duration_s), MAX_DURATION_S))

    with _lock:
        _reap()
        if session_id in _runs:
            raise RuntimeError("A simulated stream is already running for this session.")
        if len(_runs) >= MAX_CONCURRENT:
            raise RuntimeError("Too many simulated streams are running. Try again shortly.")

        argv = [
            sys.executable, "-m", "app.simulator.sensor_simulator",
            "--session-id", str(session_id),
            "--host", host,
            "--exercise", exercise,
            "--operated-leg", operated_leg,
            "--scenario", scenario,
            "--duration", str(duration),
        ]
        if fsr:
            argv.append("--fsr")
        if seed is not None:
            argv += ["--seed", str(seed)]

        process = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        run = Run(session_id=session_id, process=process, scenario=scenario)
        _runs[session_id] = run

    log_event(logger, "simulator_started", session_id=session_id,
              scenario=scenario, duration_s=duration, pid=process.pid)
    return run


def stop(session_id: int) -> bool:
    """Terminate a running stream. Safe to call when nothing is running."""
    with _lock:
        run = _runs.pop(session_id, None)
    if run is None:
        return False
    if run.process.poll() is None:
        run.process.terminate()
        try:
            run.process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            run.process.kill()
    log_event(logger, "simulator_stopped", session_id=session_id)
    return True


def stop_all() -> None:
    """Used at shutdown so no simulator outlives the server."""
    for session_id in list(_runs):
        stop(session_id)
