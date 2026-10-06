# RehabSense deployment audit

Audit date: 2026-10-06. Scope: the whole repository (Next.js frontend at the
root, `backend/`, `ml/`, `firmware/`). Status words used throughout:

- **IMPLEMENTED**: the code exists.
- **TESTED**: exercised by an automated test or a recorded local run (named).
- **DEPLOYED**: running on real hosting. **Only the Next.js frontend is DEPLOYED**
  (Vercel, frontend-only, https://rehabsense-platform.vercel.app, 2026-10-06;
  see ../VERCEL_READINESS_REPORT.md). Nothing else is.
- **NOT TESTED**: implemented but never exercised.

Companion documents: [DEPLOYMENT.md](DEPLOYMENT.md) (steps),
[POSTGRESQL_VALIDATION.md](POSTGRESQL_VALIDATION.md),
[HARDWARE_VALIDATION_STATUS.md](HARDWARE_VALIDATION_STATUS.md).

---

## 1. Target architecture

```
 Browser ──HTTPS──▶ VERCEL (Next.js)                          ESP32 + 2×MPU6050 + FSR
   │                 ├─ pages, middleware (session guard)          │
   │                 ├─ /api/contact, /api/events (own routes)     │ WSS (TLS, per-device key)
   │                 └─ /api/*  ──rewrite proxy──┐                 │
   │                                             ▼                 ▼
   └──────WSS (ticket)────────────────▶ PYTHON API HOST (FastAPI, 1 process)
                                          ├─ REST /api/*
                                          ├─ /ws/ingest/v2/{session}  (devices)
                                          ├─ /ws/live/{session}       (dashboards)
                                          ├─ in-memory: live processors, model bundles
                                          └─ simulator subprocesses (only if allowed)
                                             │                    │
                                             ▼                    ▼
                                       POSTGRESQL           OBJECT STORAGE (S3/R2/MinIO)
                                       (all records,        (exports, raw archives)
                                        raw sample chunks)
                                             ▲
                                       WORKER / CRON: retention purge, exports
```

### WebSocket boundaries

| Link | Transport | Auth | Notes |
|---|---|---|---|
| ESP32 → backend | `wss://api…/ws/ingest/v2/{session_id}` (`ws://` only on a bench LAN) | per-device key (SHA-256 hashed server-side), revocation, expiry; production refuses unregistered devices | Firmware `SERVER_USE_TLS 1` + `SERVER_CA_PEM`. Compiles; **not tested on a board**. |
| Frontend → backend (live view) | `wss://api…/ws/live/{session_id}?ticket=…` directly; **cannot** go through Vercel | 60 s single-session ticket from `POST /api/auth/ws-ticket` (via the proxy, cookie-authenticated) | `NEXT_PUBLIC_WS_URL` must be `wss://` on Vercel (build fails otherwise). |
| Frontend → backend (REST) | HTTPS through the Next rewrite `/api/*` → `BACKEND_ORIGIN` | HttpOnly first-party cookie (SameSite=Lax, Secure) or Bearer | Keeps the cookie first-party; no cross-site cookie needed. |
| Backend → DB | PostgreSQL wire protocol (`sslmode=require` in production) | DB credentials from the host's secret store | psycopg 3.3.6. |

### Placement classification

| Piece | Placement |
|---|---|
| Next.js pages, middleware, `/api/contact`, `/api/events`, `/api/*` proxy | **VERCEL** |
| FastAPI REST, both WebSocket endpoints, in-process inference, simulator runner | **PYTHON API** (container host with long-lived connections: e.g. Fly.io, Render, Railway, ECS, a VM) |
| Users, patients, sessions, devices, calibrations, raw sample chunks, results, labels, markers, recordings, audit | **POSTGRESQL** |
| Recording exports (`rs-export-1.0` zip), raw archives | **OBJECT STORAGE** |
| Retention purge (`scripts/purge_raw_samples`), training-dataset export, physical validation report | **WORKER** (scheduled job / one-off task against the same DB) |
| Firmware | **ESP32** |
| SQLite `backend/rehabsense.db`, `/api/dev/*` seed endpoint, `next dev`, ML training (`ml/`) | **LOCAL DEV ONLY** |

---

## 2. Component table

| Component | Current runtime | Dependencies | Storage requirement | Deployment target | Status | Problem | Recommended solution |
|---|---|---|---|---|---|---|---|
| Next.js frontend (pages, workspace, hardware lab) | Node ≥ 20.9, Next 15, React 19 | three.js, recharts, zod | None (stateless) | VERCEL | IMPLEMENTED · TESTED (clean `npm ci` + lint + typecheck + build in an isolated copy; `next start` E2E through the proxy) · **DEPLOYED** to Vercel in frontend-only mode (`BACKEND_ORIGIN=none`) | Vercel build needs the API URLs, which do not exist yet | `BACKEND_ORIGIN=none` until the API is hosted; then `BACKEND_ORIGIN` + `NEXT_PUBLIC_WS_URL` (build refuses an unset value) |
| `/api/*` rewrite proxy | Next rewrites (`next.config.ts`) | `BACKEND_ORIGIN` | None | VERCEL | IMPLEMENTED · TESTED (signup sets cookie through proxy; authenticated `/workspace/hardware` renders) | Proxy adds a hop for REST | Acceptable; WebSockets bypass it |
| `/api/contact`, `/api/events` | Next route handlers | optional delivery URLs | In-memory rate limiter (per instance) | VERCEL | IMPLEMENTED · off by default | Per-instance limiter resets per cold start | WAF / shared limiter in front of a public deployment |
| Workspace guard | `middleware.ts` (edge) | session cookie | None | VERCEL | IMPLEMENTED · TESTED (signed-out redirect) | — | — |
| FastAPI REST API | Python 3.14, uvicorn, 1 worker | FastAPI, SQLAlchemy 2.0.52, pydantic v2, psycopg 3.3.6 | PostgreSQL | PYTHON API | IMPLEMENTED · TESTED (229 tests on SQLite and on PostgreSQL 16.2; production-posture E2E) · NOT DEPLOYED | Startup is strict in production (good) | Run `alembic upgrade head` as a release step before start |
| Device ingest `/ws/ingest/v2` | same process | `hw_registry` (in memory) | Raw chunks to PostgreSQL per flush | PYTHON API | IMPLEMENTED · TESTED (simulated devices, key matrix) · physical: NOT TESTED | Live processor state lives in process memory: a restart ends live sessions (stored chunks survive); more than one worker/instance would split a session | **Exactly one API process.** Scale vertically. A multi-instance design needs session affinity or moving processors into a worker with a shared bus; not built |
| Dashboard live `/ws/live` | same process | ticket auth | None | PYTHON API | IMPLEMENTED · TESTED | Same single-process constraint | Same |
| ML inference | in process; bundles loaded once, SHA-256 verified | scikit-learn 1.9.1 (pinned to training) | Model files read-only (`/app/models` in the image) | PYTHON API | IMPLEMENTED · TESTED (ran on simulated streams; 18 windows in the E2E) | sklearn version must match the bundle | Image pins sklearn and fails the build if a bundle does not verify |
| ML training | `ml/.venv` | numpy, scikit-learn, torch (training only) | Datasets (GBs, local) | LOCAL DEV ONLY / training machine | IMPLEMENTED · public-dataset validated only | Must never ship to Vercel or the API image | `.vercelignore` excludes `ml/`; Dockerfile copies only the two deployed bundles |
| Hardware simulator | subprocess spawned by the API (`sim_runner`) | `app/simulator` | via the normal ingest path | PYTHON API (dev/staging) | IMPLEMENTED · TESTED · always labelled SIMULATED | Was addressing `request.url` host (public name behind a proxy) | **Fixed**: targets `127.0.0.1:<listening port>`. In production refused unless `ALLOW_SIMULATED_DEVICES=true` |
| `/api/dev/*` seed endpoint | API | — | — | LOCAL DEV ONLY | IMPLEMENTED | Spawns processes | Disabled unless `DEBUG=true`; production requires `DEBUG=false` |
| PostgreSQL | — | — | All persistent records + raw sample chunks | POSTGRESQL (managed: Neon, Supabase, RDS, Cloud SQL…) | TESTED on PostgreSQL 16.2 (local pgserver) · NOT DEPLOYED | Two PG-only bugs found and fixed | See POSTGRESQL_VALIDATION.md |
| Raw sensor chunks | `sensor_sample_chunks` (zlib, `rs-raw-v2`) | — | Grows with recording time | POSTGRESQL | IMPLEMENTED · TESTED | Unbounded growth | `RAW_SAMPLE_RETENTION_DAYS` + scheduled `scripts.purge_raw_samples` (deletes expired chunks unless retained under training consent). It does **not** archive first: export a recording to object storage before its chunks expire if it must be kept |
| Exports / archives | `app/services/storage.py` (Local / S3) + `recording_artifacts` | boto3 1.43.108 | Object storage | OBJECT STORAGE | IMPLEMENTED · TESTED (LocalStorage; S3 path against **moto** only) · real bucket NOT TESTED | — | `STORAGE_BACKEND=s3` in production; SHA-256 stored and returned in `X-RehabSense-Artifact-SHA256` |
| Migrations | Alembic, single head `6025cd723cb5` | — | — | Release step | TESTED (upgrade / check / downgrade base / re-upgrade on PG 16.2) | Original downgrades leaked enum types | **Fixed** (drop enum types on downgrade) |
| Health checks | `/api/health`, `/api/health/ready` | — | — | PYTHON API | TESTED (no internals exposed; detail endpoints need auth) | — | Point the host's health check at `/api/health/ready` |
| Docker image | `backend/Dockerfile` (python:3.14-slim, non-root) | — | — | PYTHON API | IMPLEMENTED · **NOT TESTED** (Docker daemon unavailable in this environment) | Unbuilt | First action on a machine with Docker: `docker build -f backend/Dockerfile .` |
| `docker-compose.yml` | postgres:16 + API | Docker | Named volumes | LOCAL DEV ONLY (prod-like) | IMPLEMENTED · **NOT TESTED** | Same | Same |
| Firmware | ESP32 Arduino core 3.3.12 | WebSockets 2.7.2 | — | ESP32 | IMPLEMENTED · compiles (ws and wss variants) · **NOT TESTED on hardware** | Plain ws only before this audit | **Fixed**: optional certificate-verified WSS |

---

## 3. SQLite and local data classification

SQLite is a **development convenience only**. The production configuration
refuses to start without a PostgreSQL `DATABASE_URL` and there is no fallback
path to SQLite (`backend/app/core/config.py`, `assert_production_safe`).

| File / location | Contents (inspected) | Classification | Action |
|---|---|---|---|
| `backend/rehabsense.db` (12.6 MB, at old revision `d0a86de72a63`) | 76 users (all `@example.com` test accounts), 127 sessions: 116 SIMULATED, 10 labelled LIVE, 1 UNKNOWN; 24 devices from v1 test scripts (`sim-*`, `load-*`, `bad-01`, `nan-01`; 22 under the v1 `HARDWARE` kind) | **DEVELOPMENT / TEST DATA.** The 10 "LIVE" sessions come from v1 test scripts that omitted `simulated: true`, not from a physical board (see HARDWARE_VALIDATION_STATUS.md). Migration `d1c0cc763b9e` relabels such sessions `UNVERIFIED` if this file is ever upgraded. | Keep locally (it is the developer's working DB; gitignored, `.vercelignore`d, `.dockerignore`d). **Never import into production.** Not deleted: it is not provably unused. |
| `backend/var/storage/` | Local exports from development | DEVELOPMENT DATA | Gitignored. Production uses object storage. |
| `ml/data/`, `ml datadets/` | Public datasets (UCI HAR, PAMAP2, Daily & Sports) | PUBLIC DATASETS, training only | Gitignored and excluded from Vercel and the image. |
| `ml/artifacts/activity_bilateral`, `activity_single_side` | Deployed model bundles | MODEL ARTIFACTS | Copied into the image at build; hash-verified. |
| Browser storage | `localStorage`: theme and display preferences (density, date format, units); `sessionStorage`: a one-shot error-reload guard | Not data storage | No recordings, patient data or credentials are kept in the browser. |
| `/tmp`, process memory | Live processors, model cache | EPHEMERAL | Nothing relies on them for persistence: chunks flush to PostgreSQL, exports go to `storage`. |

---

## 4. Problems found and fixed during this audit

1. **Migration downgrade left PostgreSQL enum types behind** (re-upgrade failed with `type devicekind already exists`). Fixed in `9e47091dbc5f` and `d0a86de72a63`.
2. **`max(boolean)` is not valid on PostgreSQL** in `GET /sessions/{id}/recording`. Fixed with a cast.
3. **Production client bundle contained `localhost`** via shared config. Split into `lib/config.ts` (browser) and `lib/config.server.ts` (server-only, fails the Vercel build on missing/insecure values).
4. **Detail health endpoints were public.** `/health/websocket` and `/health/analytics` now require authentication; `/health/ready` reports `ok`/`error` per subsystem without versions, paths or exception text.
5. **A device handshake that sent no data created an empty recording** (left a PHYSICAL_REGISTERED/integrity FAIL row during the deployment check). Recordings are now created with the first stored samples; test `test_a_handshake_without_data_creates_no_recording`.
6. **Simulator subprocess addressed the public host name** (broken behind TLS/proxy). Now uses loopback + the listening port; verified with a foreign `Host` header.
7. **Firmware had no TLS**; device keys would have crossed the internet in cleartext. Optional certificate-verified WSS added.
8. **Deployment check reused one session for the device probe and the simulator**, which `DEVICE_MISMATCH` correctly refused in development posture. The check now gives each probe its own session.
9. **Request size was unbounded.** `MAX_REQUEST_BYTES` middleware returns 413; WebSocket frames capped with `--ws-max-size 1048576`.

## 5. Known remaining constraints (not fixed, by design or out of scope)

- **Single API process.** Required by in-memory live sessions. Documented in the Dockerfile and DEPLOYMENT.md.
- **Deployment check side effects.** `scripts/deployment_check.py` creates accounts, a synthetic patient, sessions and a device named `deploycheck-*`. A session that completed a registered-device handshake is labelled PHYSICAL_REGISTERED even though it holds 0 samples; it has no recording and no samples, so it is not counted as evidence. Run the check against staging, not the production database.
- **Not executed here:** Docker build, API hosting, a real S3 bucket, a managed PostgreSQL instance, a physical ESP32. (The Vercel frontend deployment was executed; see VERCEL_READINESS_REPORT.md.)
