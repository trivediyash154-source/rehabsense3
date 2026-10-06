"""Dual-IMU hardware simulator — a client of the v2 ingestion protocol.

    SIMULATED DATA. Declares `simulated: true` in its handshake; the backend
    labels the session SIMULATED and the UI shows that on every view.

Speaks exactly what the ESP32 firmware in firmware/rehabsense_dual_imu
speaks: the same hello, the same batched samples, the same optional status
frames. Swapping it for the real device means pointing the device at this
host instead of running this script.

    python -m app.simulator.dual_imu_simulator --session-id 1 --exercise SQUAT \\
        --scenario ASYMMETRIC --duration 60

Scenarios exercise the failure paths that are hard to produce on demand with
real hardware: an IMU dropping out, packet loss, duplicates, a drifting
device clock, a sensor that freezes, a rate that does not match its
declaration.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import time

import websockets

from app.simulator.dual_imu import DualImuModel, SideConfig

PROTOCOL_VERSION = 2
BATCH = 10

SCENARIOS: dict[str, dict] = {
    "SYMMETRIC": {"desc": "Both sides move alike; full sensor set."},
    "ASYMMETRIC": {"left_severity": 0.35, "desc": "Left side moves through a smaller range, more slowly."},
    "SEVERE_ASYMMETRY": {"left_severity": 0.7, "desc": "Marked left/right difference."},
    "RIGHT_IMU_DROPOUT": {"dropout": ("RIGHT", 20.0, 32.0),
                          "desc": "Right IMU returns null between 20 s and 32 s."},
    "RIGHT_IMU_MISSING": {"right_missing": True, "desc": "Device declares only the left IMU."},
    "NOISY": {"noise": 4.0, "desc": "Four times the nominal sensor noise."},
    "PACKET_LOSS": {"drop_rate": 0.1, "desc": "10% of packets never arrive."},
    "DUPLICATES": {"dup_rate": 0.1, "desc": "10% of packets are sent twice."},
    "CLOCK_DRIFT": {"drift_ppm": 400.0, "desc": "Device clock runs 400 ppm fast."},
    "RATE_MISMATCH": {"true_rate": 90.0, "desc": "Declares 100 Hz, actually samples at 90 Hz."},
    "FROZEN_LEFT": {"frozen": ("LEFT", 25.0), "desc": "Left IMU repeats one reading from 25 s."},
    "NO_FORCE": {"no_force": True, "desc": "Device has no force channels."},
}


def build_hello(*, device_id: str, rate_hz: float, placement: str, right: bool,
                force: bool, scenario: str, device_key: str | None) -> dict:
    """The hello frame, built exactly as the firmware builds it."""
    imus = [{"side": "LEFT", "placement": placement, "model": "MPU6050", "i2c_address": "0x68",
             "accel_range_g": 4, "gyro_range_dps": 500}]
    if right:
        imus.append({"side": "RIGHT", "placement": placement, "model": "MPU6050",
                     "i2c_address": "0x69", "accel_range_g": 4, "gyro_range_dps": 500})
    hello = {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION,
        "device_id": device_id,
        "firmware_version": "sim-2.0.0",
        "sample_rate_hz": rate_hz,
        "imus": imus,
        "force_channels": [
            {"id": fid, "side": side, "location": "HEEL", "sensor": "FSR402", "unit": "adc_norm"}
            for fid, side in ((("heel_left", "LEFT"), ("heel_right", "RIGHT")) if force else ())
        ],
        # Declared, never inferred: this is what labels the session SIMULATED.
        "simulated": True,
        "scenario": scenario,
    }
    if device_key:
        hello["device_key"] = device_key
    return hello


def build_data(samples: list[dict], sent_ts: float) -> dict:
    return {"type": "data", "samples": samples, "sent_ts": round(sent_ts, 6)}


async def run(args) -> None:
    cfg = SCENARIOS[args.scenario]
    rate_declared = args.rate
    rate_true = cfg.get("true_rate", rate_declared)
    rng = random.Random(args.seed)

    force_sides = [] if cfg.get("no_force") else ["LEFT", "RIGHT"]
    uri = f"ws://{args.host}/ws/ingest/v2/{args.session_id}"
    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps(build_hello(
            device_id=args.device_id, rate_hz=rate_declared, placement=args.placement,
            right=not cfg.get("right_missing"), force=not cfg.get("no_force"),
            scenario=args.scenario, device_key=args.device_key)))
        ack = json.loads(await ws.recv())
        # The server may later push calibration_phase frames; this simulator
        # is time-driven and does not need to read them.
        if ack.get("type") != "hello_ack":
            raise SystemExit(f"handshake refused: {ack}")
        print(f"[sim] handshake accepted · session {ack['session_id']} · scenario {args.scenario}")

        model = DualImuModel(
            exercise=args.exercise, rate_hz=rate_true, seed=args.seed,
            left=SideConfig(severity=cfg.get("left_severity", 0.0),
                            noise_scale=cfg.get("noise", 1.0)),
            right=SideConfig(present=not cfg.get("right_missing"),
                             noise_scale=cfg.get("noise", 1.0)),
            force_sides=tuple(force_sides),
            # Hold still long enough for the health check and a *detected*
            # still period, with margin -- like a person following the LED.
            still_s=ack.get("calibration_health_seconds", 1.0) + ack["calibration_still_seconds"] + 1.0,
            calib_move_s=ack["calibration_movement_seconds"],
        )

        drift = 1.0 + cfg.get("drift_ppm", 0.0) * 1e-6
        dropout = cfg.get("dropout")
        frozen = cfg.get("frozen")
        frozen_value = None
        n_total = int(args.duration * rate_true)
        batch: list[dict] = []
        wall0 = time.perf_counter()
        sent = dropped = duplicated = 0

        for i in range(n_total):
            t_true = i / rate_true
            s = model.sample(t_true)
            if dropout and dropout[1] <= t_true < dropout[2]:
                s["imu_right" if dropout[0] == "RIGHT" else "imu_left"] = None
            if frozen and t_true >= frozen[1]:
                key = "imu_left" if frozen[0] == "LEFT" else "imu_right"
                frozen_value = frozen_value or s[key]
                s[key] = frozen_value
            sample = {"ts": round(t_true * drift, 6), "seq": i, **s}
            if cfg.get("right_missing"):
                sample.pop("imu_right", None)
            batch.append(sample)

            if len(batch) >= BATCH or i == n_total - 1:
                packet = json.dumps(build_data(batch, t_true * drift))
                if cfg.get("drop_rate") and rng.random() < cfg["drop_rate"]:
                    dropped += 1
                else:
                    await ws.send(packet)
                    sent += 1
                    if cfg.get("dup_rate") and rng.random() < cfg["dup_rate"]:
                        await ws.send(packet)
                        duplicated += 1
                batch = []
                if i // BATCH % 100 == 0:
                    await ws.send(json.dumps({"type": "status", "battery_pct": 88.0,
                                              "wifi_rssi_dbm": -58.0, "imu_left_ok": True,
                                              "imu_right_ok": not cfg.get("right_missing")}))
                target = wall0 + (t_true / args.speed)
                delay = target - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)

        print(f"[sim] sent {sent} packets, dropped {dropped}, duplicated {duplicated}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RehabSense dual-IMU simulator (SIMULATED DATA)")
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--host", default="localhost:8000")
    parser.add_argument("--exercise", default="SQUAT",
                        choices=["WALK", "SQUAT", "SIT_TO_STAND", "STEP_UP",
                                 "SINGLE_LEG_BALANCE", "KNEE_EXTENSION"])
    parser.add_argument("--scenario", default="SYMMETRIC", choices=sorted(SCENARIOS))
    parser.add_argument("--placement", default="SHANK", choices=["SHANK", "THIGH"])
    parser.add_argument("--rate", type=float, default=100.0)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Wall-clock speed-up. Timestamps are unchanged.")
    parser.add_argument("--device-id", default="sim-dual-01")
    parser.add_argument("--device-key", default=None)
    parser.add_argument("--list-scenarios", action="store_true")
    args = parser.parse_args()
    if args.list_scenarios:
        for name, cfg in sorted(SCENARIOS.items()):
            print(f"{name:20s} {cfg['desc']}")
        return
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
