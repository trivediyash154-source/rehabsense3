"""Sensor simulator.

A *client* of the production ingestion protocol, not a mock of the backend.
It opens the same WebSocket, sends the same handshake and the same packet
shape real ESP32 firmware will. Swapping it for hardware means pointing the
device at this host instead of running this script — nothing downstream
changes.

Deterministic: the same --seed reproduces the same session exactly.

    python -m app.simulator.sensor_simulator --session-id 1 --scenario ASYMMETRY

Scenarios exercise the paths that are hard to produce on demand with real
hardware: dropped packets, a limb disconnecting mid-session, a late join.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import time

import websockets

from app.simulator.movement import LimbModel

PROTOCOL_VERSION = 1
DEFAULT_RATE = 100.0
BATCH = 10  # samples per WebSocket message


SCENARIOS: dict[str, dict] = {
    "RECOVERY_STABLE": {"severity": 0.25, "desc": "Consistent movement, both limbs reporting."},
    "IMPROVING": {"severity": 0.12, "desc": "Near-symmetric movement with good range."},
    "ASYMMETRY": {"severity": 0.55, "desc": "Operated limb clearly restricted."},
    "SEVERE_ASYMMETRY": {"severity": 0.8, "desc": "Marked restriction on the operated limb."},
    "NOISY_SENSOR": {"severity": 0.3, "noise": 3.0, "desc": "Elevated sensor noise."},
    "SENSOR_DROP": {"severity": 0.3, "drop_rate": 0.12, "desc": "Packets intermittently lost."},
    "LOW_CONFIDENCE": {"severity": 0.4, "drop_rate": 0.08, "noise": 2.2,
                       "disconnect_at": 18.0, "desc": "Poor coverage and noisy signal."},
    "LEFT_DISCONNECTED": {"severity": 0.3, "legs": ["RIGHT"], "desc": "Only the right node connects."},
    "RIGHT_DISCONNECTED": {"severity": 0.3, "legs": ["LEFT"], "desc": "Only the left node connects."},
    "RECONNECT": {"severity": 0.3, "disconnect_at": 12.0, "reconnect_after": 5.0,
                  "desc": "One limb drops out and returns."},
    "DELAYED_START": {"severity": 0.3, "join_delay": 6.0, "desc": "Second limb joins late."},
    "RISK_EVENT": {"severity": 0.35, "fatigue": True, "desc": "Range declines through the session."},
}


class LegStream:
    """One leg node's connection lifecycle."""

    def __init__(self, *, host: str, session_id: int, leg: str, severity: float,
                 exercise: str, seed: int, config: dict, duration: float, fsr: bool,
                 speed: float = 1.0):
        self.host = host
        self.session_id = session_id
        self.leg = leg
        self.exercise = exercise
        self.speed = max(1.0, float(speed))
        self.duration = duration
        self.config = config
        self.fsr = fsr
        self.rng = random.Random(seed)
        self.model = LimbModel(
            exercise=exercise,
            severity=severity,
            phase_offset=0.0 if leg == "LEFT" else 0.42,
            noise_deg=config.get("noise", 0.35),
            rng=self.rng,
        )
        self.seq = 0
        self.sent = 0
        self.dropped = 0

    @property
    def uri(self) -> str:
        return f"ws://{self.host}/ws/ingest/{self.session_id}?leg={self.leg}"

    def capabilities(self) -> list[str]:
        caps = ["thigh_imu", "shin_imu"]
        if self.fsr:
            caps.append("fsr")
        return caps

    async def run(self) -> None:
        join_delay = self.config.get("join_delay", 0.0) if self.leg == "RIGHT" else 0.0
        if join_delay:
            await asyncio.sleep(join_delay)

        disconnect_at = self.config.get("disconnect_at")
        reconnect_after = self.config.get("reconnect_after")

        t = 0.0
        while t < self.duration:
            end_at = self.duration
            if disconnect_at is not None and t < disconnect_at and self.leg == "RIGHT":
                end_at = disconnect_at

            t = await self._stream_window(start=t, end=end_at)

            if end_at >= self.duration:
                break
            if reconnect_after:
                print(f"[{self.leg}] disconnected at {t:.1f}s, reconnecting in {reconnect_after}s")
                await asyncio.sleep(reconnect_after)
                disconnect_at = None
            else:
                print(f"[{self.leg}] disconnected at {t:.1f}s (stays offline)")
                return

    async def _stream_window(self, *, start: float, end: float) -> float:
        dt = 1.0 / DEFAULT_RATE
        drop_rate = self.config.get("drop_rate", 0.0)
        fatigue = self.config.get("fatigue", False)
        t = start

        async with websockets.connect(self.uri, max_size=2**20) as ws:
            await ws.send(json.dumps({
                "type": "hello",
                "protocol_version": PROTOCOL_VERSION,
                "device_id": f"sim-{self.leg.lower()}-01",
                "leg": self.leg,
                "firmware_version": "sim-1.0.0",
                "sensors": self.capabilities(),
                # Declared honestly: the backend labels the session SIMULATED
                # because of this flag, never because it guessed.
                "simulated": True,
                "scenario": self.config.get("name"),
            }))
            ack = json.loads(await ws.recv())
            if ack.get("type") != "hello_ack":
                raise RuntimeError(f"handshake refused: {ack}")
            if t == 0.0:
                print(f"[{self.leg}] handshake accepted · session {ack['session_id']} · "
                      f"caps {','.join(self.capabilities())}")

            batch: list[dict] = []
            wall_start = time.perf_counter()

            while t < end:
                # Calibration window: the limb is held still, which is what
                # the backend's gyro-bias estimation needs.
                if t < 2.6:
                    thigh, shin = self.model.still_imu()
                    stance_fsr = 1.0
                else:
                    mt = t - 2.6
                    if fatigue:
                        # Range decays through the session, which should raise
                        # a ROM-regression risk flag server-side.
                        self.model.peak = self.model.peak * (1.0 - 0.0009)
                    thigh, shin = self.model.imu(mt, dt)
                    stance_fsr = 1.0 if self.model.stance(mt) else 0.02

                sample = {"ts": round(t, 4), "seq": self.seq, "thigh": thigh, "shin": shin}
                if self.fsr:
                    sample["fsr"] = round(stance_fsr, 3)
                batch.append(sample)
                self.seq += 1
                t += dt

                if len(batch) >= BATCH:
                    if drop_rate and self.rng.random() < drop_rate:
                        # Simply not sent: the gap in `seq` is what the backend
                        # detects as packet loss.
                        self.dropped += 1
                    else:
                        await ws.send(json.dumps(
                            {"type": "data", "leg": self.leg, "seq": self.seq, "samples": batch}
                        ))
                        self.sent += 1
                    batch = []
                    # Pace to roughly real time so the dashboard animates.
                    # `speed` only compresses the wall-clock gap between
                    # packets; sample timestamps, ordering and count are
                    # unchanged, so a fast run stores exactly what a real-time
                    # run would. Seeding a demo history does not need to take
                    # as long as the sessions it represents.
                    target = wall_start + (t - start) / self.speed
                    delay = target - time.perf_counter()
                    if delay > 0:
                        await asyncio.sleep(delay)

            if batch:
                await ws.send(json.dumps(
                    {"type": "data", "leg": self.leg, "seq": self.seq, "samples": batch}
                ))
        return t


async def run_simulation(args) -> None:
    config = dict(SCENARIOS.get(args.scenario, SCENARIOS["RECOVERY_STABLE"]))
    config["name"] = args.scenario
    severity = args.severity if args.severity is not None else config.get("severity", 0.3)
    legs = config.get("legs", ["LEFT", "RIGHT"])

    print(f"RehabSense simulator · scenario {args.scenario} · seed {args.seed}")
    print(f"  {config.get('desc', '')}")
    print(f"  session {args.session_id} · {args.exercise} · severity {severity:.2f} · "
          f"{args.duration:.0f}s · legs {','.join(legs)} · fsr={'on' if args.fsr else 'off'}")

    streams = []
    for index, leg in enumerate(legs):
        # The operated limb carries the severity; the other moves normally.
        leg_severity = severity if leg == args.operated_leg else max(0.0, severity * 0.15)
        streams.append(
            LegStream(
                host=args.host, session_id=args.session_id, leg=leg,
                severity=leg_severity, exercise=args.exercise,
                speed=args.speed,
                # Distinct but deterministic per leg.
                seed=args.seed + index * 1000,
                config=config, duration=args.duration, fsr=args.fsr,
            )
        )

    await asyncio.gather(*(s.run() for s in streams))

    for s in streams:
        print(f"[{s.leg}] sent {s.sent} packets, deliberately dropped {s.dropped}")
    print("simulation complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="RehabSense sensor simulator")
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--host", default="localhost:8000")
    parser.add_argument("--exercise", default="SQUAT",
                        choices=["WALK", "SQUAT", "SIT_TO_STAND", "STEP_UP",
                                 "SINGLE_LEG_BALANCE", "KNEE_EXTENSION"])
    parser.add_argument("--operated-leg", default="LEFT", choices=["LEFT", "RIGHT"])
    parser.add_argument("--severity", type=float, default=None,
                        help="0 = unaffected, 1 = severely restricted. Overrides the scenario.")
    parser.add_argument("--scenario", default="RECOVERY_STABLE", choices=sorted(SCENARIOS))
    parser.add_argument("--duration", type=float, default=40.0)
    parser.add_argument("--seed", type=int, default=42, help="Same seed reproduces the session.")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Wall-clock speed-up. Sample timestamps and count are "
                             "unchanged, so the stored session is identical.")
    parser.add_argument("--fsr", action="store_true", help="Declare and stream a foot-pressure sensor.")
    parser.add_argument("--list-scenarios", action="store_true")
    args = parser.parse_args()

    if args.list_scenarios:
        for name, cfg in sorted(SCENARIOS.items()):
            print(f"{name:20s} {cfg.get('desc','')}")
        return

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_simulation(args))


if __name__ == "__main__":
    main()
