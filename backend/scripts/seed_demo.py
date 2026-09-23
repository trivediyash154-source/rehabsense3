"""Create a reproducible demo dataset by driving the real pipeline.

This does not insert metrics directly. It registers a clinician, creates a
patient, then runs the simulator against the live ingestion endpoint for each
session — so every stored figure was produced by the actual analytics chain,
exactly as real hardware would produce it.

    python -m scripts.seed_demo --host localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request

from app.simulator.sensor_simulator import SCENARIOS, LegStream

# Decreasing severity across sessions tells an improving recovery story.
SESSIONS = [
    {"exercise": "WALK", "severity": 0.62, "duration": 18, "pain": 6},
    {"exercise": "SIT_TO_STAND", "severity": 0.50, "duration": 18, "pain": 5},
    {"exercise": "WALK", "severity": 0.38, "duration": 18, "pain": 4},
    {"exercise": "STEP_UP", "severity": 0.30, "duration": 18, "pain": 3},
    {"exercise": "WALK", "severity": 0.18, "duration": 18, "pain": 2},
]


def call(host: str, path: str, payload=None, token: str | None = None, method: str | None = None):
    url = f"http://{host}/api{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method or ("POST" if data else "GET")
    )
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path} -> {exc.code}: {exc.read().decode()[:200]}") from exc


async def stream_session(host: str, session_id: int, config: dict, seed: int) -> None:
    scenario = dict(SCENARIOS["RECOVERY_STABLE"])
    scenario["name"] = "SEED"
    streams = [
        LegStream(
            host=host, session_id=session_id, leg=leg,
            # The operated limb carries the restriction.
            severity=config["severity"] if leg == "LEFT" else config["severity"] * 0.15,
            exercise=config["exercise"], seed=seed + index * 1000,
            config=scenario, duration=config["duration"], fsr=True,
        )
        for index, leg in enumerate(["LEFT", "RIGHT"])
    ]
    await asyncio.gather(*(s.run() for s in streams))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost:8000")
    # example.com is reserved for documentation; ".local" is a special-use
    # TLD that email validation correctly refuses.
    parser.add_argument("--email", default="demo@example.com")
    parser.add_argument("--password", default="a-very-long-demo-passphrase")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    try:
        call(args.host, "/health")
    except Exception:
        print(f"Backend not reachable at {args.host}. Start it first:", file=sys.stderr)
        print("  uvicorn app.main:app --reload --port 8000", file=sys.stderr)
        raise SystemExit(1)

    # Register, or sign in if the account already exists.
    try:
        auth = call(args.host, "/auth/signup", {
            "email": args.email, "password": args.password,
            "name": "Dr Demo", "role": "PHYSIOTHERAPIST",
        })
        print(f"registered clinician {args.email}")
    except RuntimeError as exc:
        # Only an existing account is recoverable; anything else should surface.
        if "EMAIL_ALREADY_REGISTERED" not in str(exc):
            raise
        auth = call(args.host, "/auth/token", {"email": args.email, "password": args.password})
        print(f"signed in as {args.email}")
    # /auth/signup starts a browser session; this script is a program, so it
    # always takes an explicit bearer pair.
    if "access_token" not in auth:
        auth = call(args.host, "/auth/token", {"email": args.email, "password": args.password})
    token = auth["access_token"]

    existing = call(args.host, "/patients", token=token)
    if existing["items"]:
        patient = existing["items"][0]
        print(f"using existing patient {patient['id']} ({patient['name']})")
    else:
        patient = call(args.host, "/patients", {
            "name": "Demo Patient", "age": 24, "operated_leg": "LEFT",
            "surgery_date": "2026-05-10",
            "notes": "Demo record. Clinician-only note, never shown to a patient account.",
        }, token=token)
        print(f"created patient {patient['id']}")

    for index, config in enumerate(SESSIONS, start=1):
        session = call(args.host, "/sessions", {
            "patient_id": patient["id"], "exercise_type": config["exercise"],
            "idempotency_key": f"seed-{patient['id']}-{index}",
        }, token=token)
        sid = session["id"]
        if session["status"] == "COMPLETED":
            print(f"  session {sid}: already seeded, skipping")
            continue

        print(f"  session {sid}: streaming {config['exercise']} "
              f"severity {config['severity']:.2f} …", flush=True)
        asyncio.run(stream_session(args.host, sid, config, args.seed + index))

        ended = call(args.host, f"/sessions/{sid}/end",
                     {"reported_pain": config["pain"]}, token=token)
        s = ended["summary"]
        print(f"    ROM {s['rom_deg']}° | LSI {s['symmetry_index_pct']}% | "
              f"recovery {s['recovery_score']}/100 | reps {s['repetitions']} | "
              f"confidence {s['confidence']['percent']}%")

    progress = call(args.host, f"/patients/{patient['id']}/progress", token=token)
    print()
    print(f"seeded {progress['session_count']} sessions for patient {patient['id']}")
    print("trends:", {k: v["direction"] for k, v in progress["trends"].items()})
    print()
    print("Sign in to the workspace with:")
    print(f"  email    {args.email}")
    print(f"  password {args.password}")


if __name__ == "__main__":
    main()
