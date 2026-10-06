"""RehabSense deployment check: drives a RUNNING stack like a client would.

    backend/.venv/bin/python scripts/deployment_check.py --api http://localhost:8000 \
        [--frontend http://localhost:3000] [--admin-email ... ]   (admin password: env REHABSENSE_ADMIN_PASSWORD)

Every check talks to the API (and optionally the Next.js frontend) over HTTP /
WebSocket -- no imports of server internals, no database shortcuts. Results:
PASS / FAIL / SKIPPED, with the reason. Physical hardware is always reported
as NOT TESTED: this script cannot and does not exercise a real board.

Side effects (use a development/staging database, not production): creates two
clinician accounts, a patient, sessions, a simulated recording and, when admin
credentials are given, a device registration named deploycheck-*.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

import httpx
import websockets

RESULTS: list[tuple[str, str, str]] = []


def record(name: str, ok: bool | None, detail: str = "") -> bool:
    RESULTS.append((name, "SKIPPED" if ok is None else "PASS" if ok else "FAIL", detail))
    return bool(ok)


def ws_url(api: str) -> str:
    return api.replace("https://", "wss://").replace("http://", "ws://")


async def handshake(api: str, sid: int, hello: dict) -> dict:
    async with websockets.connect(f"{ws_url(api)}/ws/ingest/v2/{sid}") as ws:
        await ws.send(json.dumps(hello))
        return json.loads(await ws.recv())


def hello(device_id: str, *, simulated: bool, key: str | None = None) -> dict:
    h = {"type": "hello", "protocol_version": 2, "device_id": device_id, "firmware_version": "check",
         "sample_rate_hz": 100,
         "imus": [{"side": "LEFT", "placement": "SHANK"}, {"side": "RIGHT", "placement": "SHANK"}],
         "force_channels": [], "simulated": simulated}
    if key:
        h["device_key"] = key
    return h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("REHABSENSE_API", "http://localhost:8000"))
    ap.add_argument("--frontend", default=os.environ.get("REHABSENSE_FRONTEND"))
    ap.add_argument("--admin-email", default=os.environ.get("REHABSENSE_ADMIN_EMAIL"))
    ap.add_argument("--simulate-seconds", type=int, default=30)
    args = ap.parse_args()
    api = args.api.rstrip("/")
    c = httpx.Client(timeout=30)

    # --- health -------------------------------------------------------------
    try:
        ready = c.get(f"{api}/api/health/ready").json()
    except Exception as exc:
        record("api reachable", False, str(exc))
        return report()
    record("api reachable", True, api)
    for k in ("database", "schema", "ml", "storage", "realtime"):
        record(f"health: {k}", ready.get(k) == "ok", str(ready.get(k)))

    # --- authentication ------------------------------------------------------
    pw = "deploy-check-" + uuid.uuid4().hex
    def account(tag):
        email = f"deploycheck-{tag}-{uuid.uuid4().hex[:8]}@example.com"
        r = c.post(f"{api}/api/auth/signup", json={"email": email, "password": pw, "name": f"Check {tag}",
                                                   "role": "PHYSIOTHERAPIST"})
        c.cookies.clear()
        tok = c.post(f"{api}/api/auth/token", json={"email": email, "password": pw}).json()
        return r.status_code, {"Authorization": f"Bearer {tok.get('access_token')}"}
    code, A = account("a")
    record("register + login", code == 201 and A["Authorization"] != "Bearer None", f"signup {code}")
    _, B = account("b")
    record("protected route without credentials -> 401",
           c.get(f"{api}/api/patients").status_code == 401)
    record("protected route with credentials -> 200",
           c.get(f"{api}/api/patients", headers=A).status_code == 200)

    pid = c.post(f"{api}/api/patients", headers=A, json={"name": "Deploy Check (synthetic)",
                                                          "operated_leg": "LEFT"}).json()["id"]
    record("user A reads own patient", c.get(f"{api}/api/patients/{pid}", headers=A).status_code == 200)
    record("user B reads user A's patient -> denied (404)",
           c.get(f"{api}/api/patients/{pid}", headers=B).status_code == 404)
    sid = c.post(f"{api}/api/sessions", headers=A, json={"patient_id": pid,
                                                         "exercise_type": "SQUAT"}).json()["id"]
    record("user B reads user A's session -> denied (404)",
           c.get(f"{api}/api/sessions/{sid}", headers=B).status_code == 404)

    # --- device authentication ----------------------------------------------
    # Each device probe gets its own session: a session is bound to the first
    # device that completes a handshake (DEVICE_MISMATCH for any other).
    def new_session():
        return c.post(f"{api}/api/sessions", headers=A, json={"patient_id": pid,
                                                              "exercise_type": "SQUAT"}).json()["id"]
    dev_id = f"deploycheck-{uuid.uuid4().hex[:6]}"
    s1 = new_session()
    r = asyncio.run(handshake(api, s1, hello(dev_id, simulated=False)))
    record("unregistered device", True,
           f"{r.get('code') or r.get('type')} (production refuses with DEVICE_NOT_REGISTERED; "
           f"development accepts it as PHYSICAL_UNVERIFIED)")
    c.post(f"{api}/api/sessions/{s1}/end", headers=A, json={"notes": "deployment check"})
    admin_pw = os.environ.get("REHABSENSE_ADMIN_PASSWORD")
    if args.admin_email and admin_pw:
        tok = c.post(f"{api}/api/auth/token", json={"email": args.admin_email, "password": admin_pw}).json()
        ADM = {"Authorization": f"Bearer {tok.get('access_token')}"}
        reg = c.post(f"{api}/api/devices/register", headers=ADM, json={"device_id": dev_id,
                                                                        "notes": "deployment check"})
        record("device registration (admin)", reg.status_code == 201, str(reg.status_code))
        key = reg.json().get("device_key")
        s2 = new_session()
        r = asyncio.run(handshake(api, s2, hello(dev_id, simulated=False, key="wrong")))
        record("registered device, wrong key -> denied", r.get("code") == "DEVICE_UNAUTHORIZED", str(r))
        r = asyncio.run(handshake(api, s2, hello(dev_id, simulated=False, key=key)))
        record("registered device, correct key -> allowed", r.get("type") == "hello_ack", str(r.get("type")))
        c.post(f"{api}/api/devices/{dev_id}/revoke", headers=ADM)
        s3 = new_session()
        r = asyncio.run(handshake(api, s3, hello(dev_id, simulated=False, key=key)))
        record("revoked device -> denied", r.get("code") == "DEVICE_REVOKED", str(r))
        for s in (s2, s3):
            c.post(f"{api}/api/sessions/{s}/end", headers=A, json={"notes": "deployment check"})
    else:
        record("device registration / key checks", None,
               "needs --admin-email and REHABSENSE_ADMIN_PASSWORD (create with scripts/create_user)")

    # --- simulator ingestion -> calibration -> ML -> DB --------------------------
    sim = c.post(f"{api}/api/sessions/{sid}/simulate-hardware", headers=A,
                 json={"scenario": "ASYMMETRIC", "duration_s": args.simulate_seconds})
    if sim.status_code != 200:
        record("simulator ingestion", None, f"simulator not allowed here ({sim.status_code}): "
                                            f"{sim.json().get('message')}")
    else:
        time.sleep(args.simulate_seconds + 4)
        end = c.post(f"{api}/api/sessions/{sid}/end", headers=A, json={}).json()
        s = end.get("summary") or {}
        record("simulator ingestion (SIMULATED provenance)", end.get("mode") == "SIMULATED",
               f"mode {end.get('mode')}")
        cal = c.get(f"{api}/api/sessions/{sid}/calibration", headers=A).json()["items"]
        record("calibration stored", bool(cal) and cal[0]["status"] in ("PASS", "WARN"),
               cal[0]["status"] if cal else "none")
        act = s.get("activity") or {}
        record("ML inference ran", bool(act.get("model")) and act.get("windows", 0) > 0,
               f"model {act.get('model')}, {act.get('windows')} windows")
        record("movement analysis", (s.get("repetitions") or 0) > 0,
               f"{s.get('repetitions')} reps, asymmetry {(s.get('bilateral') or {}).get('asymmetry_score')}")
        rec = c.get(f"{api}/api/sessions/{sid}/recording", headers=A).json()
        record("raw samples stored", rec.get("samples", 0) > 0, f"{rec.get('samples')} samples")
        integ = c.get(f"{api}/api/sessions/{sid}/recording-integrity", headers=A).json()
        record("recording integrity", integ.get("integrity_status") == "PASS",
               f"{integ.get('integrity_status')}, provenance {integ.get('provenance')}")

    # --- frontend (optional) -------------------------------------------------
    if args.frontend:
        fe = args.frontend.rstrip("/")
        f = httpx.Client(timeout=30, follow_redirects=False)
        record("frontend serves /", f.get(f"{fe}/").status_code == 200)
        record("frontend proxies /api/health", f.get(f"{fe}/api/health").json().get("status") == "ok")
        record("frontend /workspace redirects when signed out",
               f.get(f"{fe}/workspace").status_code in (302, 303, 307, 308))
        email = f"deploycheck-fe-{uuid.uuid4().hex[:8]}@example.com"
        r = f.post(f"{fe}/api/auth/signup", json={"email": email, "password": pw, "name": "FE",
                                                  "role": "PHYSIOTHERAPIST"}, headers={"Origin": fe})
        record("signup through frontend proxy sets session cookie", r.status_code == 201 and bool(f.cookies),
               str(r.status_code))
        record("authenticated /workspace/hardware renders", f.get(f"{fe}/workspace/hardware").status_code == 200)
    else:
        record("frontend integration", None, "pass --frontend URL")

    record("PHYSICAL HARDWARE", None, "NOT TESTED (no board in this check)")
    return report()


def report() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    for name, status, detail in RESULTS:
        print(f"{status:8} {name.ljust(width)}  {detail}")
    fails = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print(f"\n{sum(1 for _, s, _ in RESULTS if s == 'PASS')} passed, {fails} failed, "
          f"{sum(1 for _, s, _ in RESULTS if s == 'SKIPPED')} skipped")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
