# RehabSense on Vercel (free Hobby plan)

Everything runs on free tiers with no payment card:

| Piece | Where | Project / ID |
|---|---|---|
| Next.js website | Vercel | `rehabsense-platform` (`prj_ohl5XWEARZ5eXHeFMtvBTX6SUJyS`), https://rehabsense-platform.vercel.app |
| FastAPI backend (REST, WebSockets, ML inference, simulator) | Vercel container image (`backend/Dockerfile`, Fluid compute, region `cle1`) | `rehabsense-api` (`prj_ylHGtJbAT868yeCW1LtrslhN0Wz6`), https://rehabsense-api.vercel.app |
| PostgreSQL 17 | Neon free plan, AWS us-east-2 | project `little-unit-00095075` |

```
Browser ──HTTPS──▶ rehabsense-platform.vercel.app (Next.js)
   │                  └─ /api/*  ──rewrite──▶ rehabsense-api.vercel.app (FastAPI container)
   └──WSS + 60 s ticket──────────────────────▶ rehabsense-api.vercel.app/ws/live/{session}
ESP32 ──WSS + device key──────────────────────▶ rehabsense-api.vercel.app/ws/ingest/v2/{session}
                                               FastAPI ──▶ Neon PostgreSQL (all records,
                                                           raw samples, ML results)
                                                       └─▶ LISTEN/NOTIFY live relay
```

## Keep the database: claim it before 2026-10-09 17:41 UTC

The Neon project was created without an account and is deleted at that time
unless it is claimed into a Neon account (free; `trivediyash154@gmail.com`
already has one). In a terminal on this Mac:

```bash
npx neonctl@latest claim accept little-unit-00095075
```

It prints a link (valid 15 minutes): open it while signed in to Neon and
confirm. The connection string does not change, so nothing else needs updating.

## Free-plan behaviour (stated plainly)

- Every request and WebSocket lasts at most 300 s; dashboards and the ESP32
  firmware reconnect automatically.
- The API scales to zero after 5 minutes without traffic; the next request
  waits a few seconds while it starts (the website re-checks the session
  instead of showing a signed-in user as signed out).
- Several API instances may run at once. Live dashboard messages cross
  instances through PostgreSQL LISTEN/NOTIFY (`LIVE_RELAY=postgres`); session
  summaries are rebuilt from stored rows when the ending request reaches
  another instance. Commands such as "Recalibrate" act only if they reach the
  instance holding the device's stream.
- The container disk is temporary (`/tmp`): stored export files do not
  survive a restart; database data does.
- Hobby usage limits apply; when exceeded, Vercel pauses functions until the
  next cycle. Nothing is ever charged.

## Environment variables

Website (`rehabsense-platform`): `BACKEND_ORIGIN=https://rehabsense-api.vercel.app`,
`NEXT_PUBLIC_WS_URL=wss://rehabsense-api.vercel.app`,
`NEXT_PUBLIC_SITE_URL=https://rehabsense-platform.vercel.app`.

API (`rehabsense-api`): `DATABASE_URL` (sensitive), `SECRET_KEY` (sensitive),
`ENVIRONMENT=production`, `DEBUG=false`, `CORS_ORIGINS=https://rehabsense-platform.vercel.app`,
`COOKIE_SECURE=true`, `STORAGE_BACKEND=local`, `STORAGE_LOCAL_DIR=/tmp/rehabsense-storage`,
`ALLOW_SIMULATED_DEVICES=true`, `LIVE_RELAY=postgres`, `PORT=8000`,
`RUN_MIGRATIONS_ON_START=false`, `LOG_LEVEL=INFO`.

No secret is a `NEXT_PUBLIC_` variable, and secrets never appear in git.

## Redeploy

```bash
npx vercel@latest login
# website (repository root; .vercelignore keeps backend/ml/firmware out)
VERCEL_ORG_ID=team_2sBcwmlki2DTOyMtbjFvI4pi VERCEL_PROJECT_ID=prj_ohl5XWEARZ5eXHeFMtvBTX6SUJyS \
  npx vercel@latest deploy --prod
# API container (builds backend/Dockerfile on Vercel)
VERCEL_ORG_ID=team_2sBcwmlki2DTOyMtbjFvI4pi VERCEL_PROJECT_ID=prj_ylHGtJbAT868yeCW1LtrslhN0Wz6 \
  bash scripts/deploy_api_vercel.sh --prod
```

Database migrations run before an API deploy that changes the schema:
`cd backend && DATABASE_URL='<neon direct URL>' .venv/bin/python -m alembic upgrade head`
(the API refuses to start if the schema is behind).

Checks: `bash scripts/vercel_readiness_check.sh` (website build) and
`backend/.venv/bin/python scripts/deployment_check.py --api https://rehabsense-api.vercel.app --frontend https://rehabsense-platform.vercel.app`
(creates clearly labelled test accounts).

## Connecting an ESP32

Register the board (admin or technician account: create one with
`python -m scripts.create_user` against the Neon URL), then in `config.h`:
`SERVER_HOST "rehabsense-api.vercel.app"`, `SERVER_PORT 443`,
`SERVER_USE_TLS 1`, the issuing CA's PEM in `SERVER_CA_PEM`, and the device
key. Not yet tested on a physical board.
