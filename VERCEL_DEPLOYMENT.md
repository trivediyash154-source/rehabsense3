# RehabSense on Vercel (free Hobby plan)

Everything runs on free tiers with no payment card:

| Piece | Where | Project / ID |
|---|---|---|
| Next.js website | Vercel, functions in `sin1` (Singapore) | `rehabsense-platform` (`prj_ohl5XWEARZ5eXHeFMtvBTX6SUJyS`), https://rehabsense-platform.vercel.app |
| FastAPI backend (REST, WebSockets, ML inference, simulator) | Vercel container image (`backend/Dockerfile`, Fluid compute, region `sin1`) | `rehabsense-api` (`prj_ylHGtJbAT868yeCW1LtrslhN0Wz6`), https://rehabsense-api.vercel.app |
| PostgreSQL 17 | Neon free plan, AWS `ap-southeast-1` (Singapore), in the owner's own Neon account (no expiry) | project `ancient-queen-09719759` ("rehabsense") |

```
Browser ──HTTPS──▶ rehabsense-platform.vercel.app (Next.js, sin1)
   │                  └─ /api/*  ──rewrite──▶ rehabsense-api.vercel.app (FastAPI container, sin1)
   └──WSS + 60 s ticket──────────────────────▶ rehabsense-api.vercel.app/ws/live/{session}
ESP32 ──WSS + device key──────────────────────▶ rehabsense-api.vercel.app/ws/ingest/v2/{session}
                                               FastAPI ──▶ Neon PostgreSQL, Singapore (all records,
                                                           raw samples, ML results)
                                                       └─▶ LISTEN/NOTIFY live relay
```

Website, API and database are in the same region, the closest Neon region to
India, where the users are. Each API round trip from India is about 0.1 s.
When everything was in the US it was 0.25–0.27 s; see
[PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md).

**History.** Until 2026-10-07 the database was a temporary "claimable" Neon project
(`little-unit-00095075`, us-east-2). Starting its claim rotated the database password
and the claim never completed, which took the API down. The current database was
created directly in the owner's Neon account, migrated to the head and connected. The
old project held only test accounts and Neon deletes it automatically.

## Free-plan behaviour (stated plainly)

- Every request and WebSocket lasts at most 300 s; dashboards and the ESP32
  firmware reconnect automatically. A dashboard keeps retrying when the reconnect
  lands on an instance that is still starting; only 401/403/404 stop it. Verified
  live: a socket was cut and the first new ticket failed with 503, the dashboard
  retried and resumed.
- The API scales to zero after 5 minutes without traffic; the next request
  waits a few seconds while it starts (the website re-checks the session
  instead of showing a signed-in user as signed out).
- Several API instances may run at once. Live dashboard messages cross
  instances through PostgreSQL LISTEN/NOTIFY (`LIVE_RELAY=postgres`); session
  summaries are rebuilt from stored rows when the ending request reaches
  another instance; the Hardware Lab's validation panel is answered from a
  snapshot (`live_snapshots`) that the receiving instance writes every 4 s. Commands such as "Recalibrate" act only if they reach the
  instance holding the device's stream.
- The container disk is temporary (`/tmp`): stored export files do not
  survive a restart; database data does.
- **Long live sessions.**
  - Work that runs in the background with no open request, such as the in-process
    simulator, can be suspended by the host. A live 6-minute simulated run stopped
    after 3.6 min; 90 s runs (the UI default) complete.
  - A real device's own socket keeps its instance active, but it is cut every 300 s.
    After the firmware reconnects, processing may resume on another instance, which
    needs a fresh calibration.
  - Untested on a physical board. See [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md).
- Hobby usage limits apply; when exceeded, Vercel pauses functions until the
  next cycle. Nothing is ever charged.

## Environment variables

Website (`rehabsense-platform`): `BACKEND_ORIGIN=https://rehabsense-api.vercel.app`,
`NEXT_PUBLIC_WS_URL=wss://rehabsense-api.vercel.app`,
`NEXT_PUBLIC_SITE_URL=https://rehabsense-platform.vercel.app`.

API (`rehabsense-api`): `DATABASE_URL` (sensitive), `SECRET_KEY` (sensitive),
`DEVICE_INGEST_KEY` (sensitive; the fleet key that unregistered and simulated
streams must present, so nobody can stream into a session anonymously),
`ENVIRONMENT=production`, `DEBUG=false`, `CORS_ORIGINS=https://rehabsense-platform.vercel.app`,
`COOKIE_SECURE=true`, `STORAGE_BACKEND=local`, `STORAGE_LOCAL_DIR=/tmp/rehabsense-storage`,
`ALLOW_SIMULATED_DEVICES=true`, `LIVE_RELAY=postgres`, `PORT=8000`,
`RUN_MIGRATIONS_ON_START=false`, `LOG_LEVEL=INFO`.

Social sign-in (API project only, optional): `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET` (sensitive), `GOOGLE_REDIRECT_URI`, `FACEBOOK_APP_ID`,
`FACEBOOK_APP_SECRET` (sensitive), `FACEBOOK_REDIRECT_URI`. The redirect URIs are on the
**website** origin (`https://rehabsense-platform.vercel.app/api/auth/<provider>/callback`),
so the session cookie stays first-party. `bash scripts/set_oauth_env.sh` stores them with
hidden input. Setup steps are in [GOOGLE_OAUTH_SETUP.md](GOOGLE_OAUTH_SETUP.md) and
[FACEBOOK_OAUTH_SETUP.md](FACEBOOK_OAUTH_SETUP.md); the design is in
[AUTHENTICATION_ARCHITECTURE.md](AUTHENTICATION_ARCHITECTURE.md).

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
(the API refuses to start if the schema is behind). The direct (non-pooled)
connection string comes from the Neon console (project "rehabsense" → Connect)
or `npx neonctl@latest connection-string --project-id ancient-queen-09719759`.
The API itself also uses the direct connection, because the LISTEN/NOTIFY relay
cannot run through a transaction pooler.

Checks: `bash scripts/vercel_readiness_check.sh` (website build) and
`backend/.venv/bin/python scripts/deployment_check.py --api https://rehabsense-api.vercel.app --frontend https://rehabsense-platform.vercel.app`
(creates clearly labelled test accounts).

## Connecting an ESP32

Register the board (admin or technician account: create one with
`python -m scripts.create_user` against the Neon URL), then in `config.h`:
`SERVER_HOST "rehabsense-api.vercel.app"`, `SERVER_PORT 443`,
`SERVER_USE_TLS 1`, the issuing CA's PEM in `SERVER_CA_PEM`, and the device
key. Not yet tested on a physical board.
