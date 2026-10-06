# Deploying RehabSense

Two deployables plus two managed services:

| Piece | Where | Why |
|---|---|---|
| Next.js frontend | **Vercel** | Stateless pages + a `/api/*` proxy |
| FastAPI API (REST, WebSockets, inference) | **A container host that keeps long-lived connections** (Fly.io, Render, Railway, ECS, a VM) | Persistent device and dashboard WebSockets, in-memory live sessions, models held in memory. **Not Vercel.** |
| PostgreSQL 16 | Managed (Neon, Supabase, RDS, Cloud SQL…) | All records and raw sample chunks |
| Object storage | S3-compatible (S3, R2, MinIO) | Exports and archives |

Why each piece sits where it does: [DEPLOYMENT_AUDIT.md](DEPLOYMENT_AUDIT.md).

> **Status as of 2026-10-06:** the frontend is **deployed to Vercel in
> frontend-only mode** (https://rehabsense-platform.vercel.app,
> `BACKEND_ORIGIN=none`; see [../VERCEL_DEPLOYMENT.md](../VERCEL_DEPLOYMENT.md)).
> Steps 1–10 and 12–15 have not been executed against real hosting: no API
> host, managed PostgreSQL or bucket exists yet. Everything up to the image
> build was run locally (see POSTGRESQL_VALIDATION.md); the Docker image
> build is **not tested**.

All commands run from the repository root unless stated.

---

### 1. Provision PostgreSQL

Create a PostgreSQL 16 database and a dedicated role. Note the URL in this form:

```
postgresql+psycopg://USER:PASSWORD@HOST:5432/rehabsense?sslmode=require
```

(The `+psycopg` driver prefix is required.)

### 2. Provision object storage

Create a private bucket (no public access). Create credentials allowed only
`s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on that bucket.

### 3. Generate secrets

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
```

Store it, the DB URL and the storage credentials only in the API host's secret
store. **Never commit them**; `.env*` files are gitignored except the examples.

### 4. Build the API image

```bash
docker build -f backend/Dockerfile -t rehabsense-api .
```

The build context is the repo root because the two deployed model bundles live
in `ml/artifacts/`. The build **fails** if a bundle's SHA-256 or scikit-learn
version does not verify. Datasets and training code are not copied.

### 5. Configure the API environment

Required (startup is refused if any is missing or unsafe):

```
ENVIRONMENT=production
DEBUG=false
DATABASE_URL=postgresql+psycopg://…?sslmode=require
SECRET_KEY=<step 3>
CORS_ORIGINS=https://<your-project>.vercel.app      # exact origins, comma-separated, never *
COOKIE_SECURE=true
STORAGE_BACKEND=s3
STORAGE_S3_BUCKET=<bucket>
STORAGE_S3_REGION=<region>                          # or STORAGE_S3_ENDPOINT_URL for R2/MinIO
AWS_ACCESS_KEY_ID=<…>
AWS_SECRET_ACCESS_KEY=<…>
```

Optional: `ALLOW_SIMULATED_DEVICES=true` (staging/demo only; every simulated
stream is labelled SIMULATED), `RAW_SAMPLE_RETENTION_DAYS`, `MAX_REQUEST_BYTES`.
Production always requires registered devices and a migrated schema.

### 6. Run migrations (release step, before every start of a new version)

```bash
docker run --rm --env-file api.env rehabsense-api alembic upgrade head
```

The API does not migrate on boot and **refuses to start** if the schema is not
at the Alembic head.

### 7. Start the API: exactly one process

```bash
docker run -d --env-file api.env -p 8000:8000 rehabsense-api
```

The image runs `uvicorn --workers 1`. Do not scale to more than one
instance/worker: live sessions are held in process memory, so a second process
would split a device's stream from its dashboard. Scale vertically. The host
must support WebSockets and must not close idle connections faster than the
15 s heartbeat (firmware) allows.

### 8. Put TLS in front of the API

Use the host's HTTPS termination on a stable name, e.g. `api.your-domain`.
It must pass WebSocket upgrades through and forward `X-Forwarded-Proto`
(uvicorn runs with `--proxy-headers`).

### 9. Health check

Point the host's health check at:

```bash
curl -fsS https://api.your-domain/api/health/ready
# {"api":"ok","database":"ok","schema":"ok","ml":"ok","storage":"ok","realtime":"ok","status":"ok"}
```

It returns 503 when any subsystem is not ok, and exposes no versions, paths or
errors. Liveness only: `/api/health`.

### 10. Create the first admin account

Admin and technician accounts cannot self-register:

```bash
docker run --rm -it --env-file api.env rehabsense-api \
  python -m scripts.create_user --email ops@your-domain --role ADMIN --name "Operations"
# password: prompted (or env REHABSENSE_NEW_PASSWORD); never on the command line
```

### 11. Deploy the frontend to Vercel

1. Vercel → **Add New Project** → import this Git repository. Framework:
   Next.js. Root directory: the repository root. `.vercelignore` keeps
   `backend/`, `ml/`, `firmware/` and data out of the upload.
2. Project → Settings → Environment Variables (Production):

   ```
   BACKEND_ORIGIN=https://api.your-domain          # server-only; /api/* is proxied here
   NEXT_PUBLIC_WS_URL=wss://api.your-domain        # browser live socket (cannot use the proxy)
   NEXT_PUBLIC_SITE_URL=https://<your-project>.vercel.app
   ```

   The build **fails on purpose** if any is missing or not https/wss.
   Before the API exists, `BACKEND_ORIGIN=none` deploys the frontend alone
   (this is how `rehabsense-platform` runs today).
3. Deploy. Then make sure the API's `CORS_ORIGINS` (step 5) contains the
   exact deployed origin, and restart the API if you changed it: the API
   refuses cookie-authenticated writes from any other `Origin`.

CLI equivalent and full details: [../VERCEL_DEPLOYMENT.md](../VERCEL_DEPLOYMENT.md).

### 12. Register each ESP32

```bash
curl -X POST https://api.your-domain/api/devices/register \
  -H "Authorization: Bearer <admin or technician token>" -H "Content-Type: application/json" \
  -d '{"device_id": "rehabsense-dual-001", "expires_in_days": 365}'
```

The `device_key` in the response is shown **once**; only its hash is stored.
Put it in the board's `config.h`. Revoke with
`POST /api/devices/{device_id}/revoke`.

### 13. Flash the firmware for the deployed API

In `firmware/rehabsense_dual_imu/config.h`: `SERVER_HOST "api.your-domain"`,
`SERVER_PORT 443`, `SERVER_USE_TLS 1`, the issuing CA's PEM in
`SERVER_CA_PEM`, `DEVICE_KEY` from step 12. Then follow
[PHYSICAL_HARDWARE_CHECKLIST.md](PHYSICAL_HARDWARE_CHECKLIST.md). Plain `ws://`
is for a bench LAN only.

### 14. Schedule the retention job

Daily, against the same database (cron, scheduled container, or host
scheduler):

```bash
docker run --rm --env-file api.env rehabsense-api python -m scripts.purge_raw_samples
```

It deletes expired raw chunks unless they are retained under a training
consent. It does not archive anything first: export a recording to object
storage (`GET /api/sessions/{id}/export.zip`) before its chunks expire if it
must be kept.

### 15. Verify the deployed stack

Against **staging** (the check creates test accounts, a synthetic patient,
sessions and a `deploycheck-*` device):

```bash
backend/.venv/bin/pip install httpx websockets   # if not already installed
REHABSENSE_ADMIN_PASSWORD=… backend/.venv/bin/python scripts/deployment_check.py \
  --api https://api.your-domain --frontend https://<your-project>.vercel.app \
  --admin-email ops@your-domain
```

Static checks (lint, typecheck, build, model bundles, Alembic head, test suite)
run on any machine with `bash scripts/deployment_check.sh`.

The simulator part of the check needs `ALLOW_SIMULATED_DEVICES=true`; without
it that part reports SKIPPED, and the result is still accurate. Physical
hardware is always reported **NOT TESTED** by this script.

---

## Rollback

- **Frontend:** Vercel → Deployments → promote the previous deployment.
- **API:** redeploy the previous image tag. Migrations are additive; only run
  `alembic downgrade <rev>` after taking a database backup, because downgrades
  drop columns and tables.
