# PostgreSQL validation

Date: 2026-10-06. What was run, against what, and what it showed. Nothing
here was run against a managed/cloud PostgreSQL instance.

## Server

```
PostgreSQL 16.2 on aarch64-apple-darwin23.5.0, compiled by Apple clang version 15.0.0 (clang-1500.0.40.1), 64-bit
```

A real PostgreSQL server (not SQLite, not a mock), started without Docker via
the `pgserver` Python package in an isolated interpreter, listening on a Unix
socket:

```bash
uv run --python 3.12 --with pgserver python -c \
  "import pgserver; s = pgserver.get_server('<data-dir>', cleanup_mode=None); print(s.get_uri())"
```

Drivers: psycopg 3.3.6, SQLAlchemy 2.0.52, Alembic 1.19.2.

Reproducible alternative on any machine with Docker (not executed here: the
Docker daemon was unavailable):

```bash
docker compose up -d db
cd backend && DATABASE_URL=postgresql+psycopg://rehabsense:rehabsense-dev-only@localhost:5432/rehabsense \
  .venv/bin/python -m alembic upgrade head
```

## 1. Migration cycle (fresh database `rehabsense_cycle`)

```bash
cd backend
export DATABASE_URL="postgresql+psycopg://postgres@/rehabsense_cycle?host=<socket-dir>"
alembic upgrade head      # -> tables=33 (incl. alembic_version), enum types=28, revision 6025cd723cb5
alembic check             # -> No new upgrade operations detected.
alembic downgrade base    # -> tables=1 (alembic_version), enum types=0
alembic upgrade head      # -> tables=33, enum types=28
alembic heads             # -> 6025cd723cb5 (head)   (single head)
```

Chain: `9e47091dbc5f` initial → `fbafc9e00f74` → `d0a86de72a63` →
`75b9b8c873bd` hardware v2 → `d1c0cc763b9e` provenance → `5e144fc9d453`
recordings → `6025cd723cb5` device revocation/expiry + recording artifacts.

## 2. Backend test suite on PostgreSQL

```bash
cd backend
DATABASE_URL="postgresql+psycopg://postgres@/rehabsense_test?host=<socket-dir>" \
  .venv/bin/python -m pytest -q tests -p no:cacheprovider
# 229 passed
```

The same suite on SQLite: 229 passed.

## 3. Production-posture end-to-end (database `rehabsense_e2e`)

API started with `ENVIRONMENT=production`, `DEBUG=false`, PostgreSQL URL,
`COOKIE_SECURE=true`, explicit `CORS_ORIGINS`, `STORAGE_BACKEND=local` with an
explicit directory, `ALLOW_SIMULATED_DEVICES=true` (for the simulated stream).

1. Before `alembic upgrade head`, startup was **refused** (schema not at head).
2. After migrating, `scripts/deployment_check.py --admin-email …`:
   **23 passed, 0 failed, 2 skipped** (frontend not given; physical hardware
   NOT TESTED). This covered health, auth, IDOR (user B denied A's patient
   and session), unregistered device refused (`DEVICE_NOT_REGISTERED`), wrong
   key refused, correct key accepted, revoked device refused, then a SIMULATED
   stream through calibration (PASS), ML inference (18 windows), movement
   analysis (6 reps), raw samples (2000) and recording integrity PASS.
3. Rows read back from PostgreSQL afterwards (cumulative over the runs):
   users 5, sessions 9, devices 3, device_calibrations 3,
   sensor_sample_chunks 57, activity_results 56, movement_assessments 11,
   repetition_results 18, recordings 4, session_markers 18, audit_logs 52.

Frontend integration was run against a development-posture API on the same
PostgreSQL server (database `rehabsense_validation`; development posture
because the test client talks plain http to `next start`, and production
cookies are `Secure`): **24 passed, 0 failed, 2 skipped**, including signup
through the Next proxy and an authenticated `/workspace/hardware` render.

## 4. PostgreSQL-only defects found and fixed

| Defect | Symptom on PostgreSQL | Fix |
|---|---|---|
| Original migrations' downgrades did not drop enum types | Re-upgrade after downgrade: `type "devicekind" already exists` | `DROP TYPE IF EXISTS` for every enum in `9e47091dbc5f` (21) and `d0a86de72a63` (2) downgrades |
| `func.max(SensorSampleChunk.simulated)` | `function max(boolean) does not exist` on `GET /sessions/{id}/recording` | `max(cast(simulated, Integer))` |

SQLite accepted both silently, which is why the suite had to be run on a real
server.

## 5. Caveats

- One recording in `rehabsense_e2e` is PHYSICAL_REGISTERED with 0 samples and
  integrity FAIL. It was created by the deployment check's key handshake
  **before** the fix that creates recordings only with the first samples. It
  is a test artifact in a scratch database, not hardware evidence.
- Not validated: a managed PostgreSQL service, `sslmode=require`, connection
  pooling (PgBouncer), backups/restore, and load.
