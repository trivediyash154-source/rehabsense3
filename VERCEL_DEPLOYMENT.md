# Deploying the RehabSense frontend to Vercel

Vercel hosts **only the Next.js frontend**. The FastAPI service (REST,
WebSockets, ML inference, simulator), PostgreSQL and object storage run
elsewhere; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for those.

## Current deployment (2026-10-06)

| | |
|---|---|
| Vercel project | `rehabsense-platform` (`prj_ohl5XWEARZ5eXHeFMtvBTX6SUJyS`), scope `trivediyash154-7968s-projects` |
| Production URL | https://rehabsense-platform.vercel.app |
| Mode | **Frontend-only** (`BACKEND_ORIGIN=none`): public pages and the illustrative demo work; sign-in, patients, sessions and live data answer `503 BACKEND_NOT_CONNECTED` because no API is hosted yet |
| Root directory | the repository root (`/`) — that is where `package.json`, `app/` and `next.config.ts` live |
| Framework / Node | Next.js 15.5 (App Router) · Node 24.x · install `npm ci` (`vercel.json`) |
| Upload | 112 files, ~1.3 MB; `.vercelignore` keeps `backend/`, `ml/`, `firmware/`, `docs/`, `scripts/`, databases and env files out |

The old project `rehabsense` (`rehabsense-alpha.vercel.app`, a stale
2026-09-23 upload with no environment variables) is unrelated to this one.

---

## 1. Validate locally (no Vercel account needed)

```bash
cd /path/to/rehabsense          # the repository root
bash scripts/vercel_readiness_check.sh
```

It copies exactly the files Vercel would upload, runs `npm ci`, TypeScript,
ESLint, builds the app the way Vercel does (`VERCEL=1`) in three modes, and
scans the browser bundle. Last line:

- `VERCEL READY` — everything passed and a live API was verified (`REHABSENSE_API=https://…`)
- `VERCEL READY — EXTERNAL BACKEND INFRASTRUCTURE REQUIRED` — frontend ready, no API verified
- `NOT VERCEL READY` — fix the `[FAIL]` lines first

## 2. Deploy with the Vercel CLI

```bash
cd /path/to/rehabsense
npx vercel@latest login                          # browser approval
npx vercel@latest link --project rehabsense-platform --yes
npx vercel@latest                                # preview deployment (protected URL)
npx vercel@latest --prod                         # production: rehabsense-platform.vercel.app
```

Build logs: `npx vercel@latest inspect <deployment-url> --logs`.
Runtime logs: `npx vercel@latest logs --deployment <id> --since 1h`.

Alternatively connect the Git repository in the Vercel dashboard (Project →
Settings → Git); every push to `main` then deploys. Note that
`trivediyash154-source/rehabsense3` is a **public** repository.

## 3. Vercel environment variables

Set in Vercel → Project → Settings → Environment Variables (Production and
Preview). Changing one requires a redeploy.

| Name | Purpose | Read by | When | Public / secret | Required |
|---|---|---|---|---|---|
| `BACKEND_ORIGIN` | API origin that `/api/*` is proxied to and the server-side session check calls. `none` = frontend-only | Next server (build: rewrites; runtime: session, `/backend-unavailable`) | build + runtime | not secret, but server-only (never `NEXT_PUBLIC_`) | **yes**: `https://api.<domain>` or `none` |
| `NEXT_PUBLIC_WS_URL` | API WebSocket origin for the live view (WebSockets cannot go through Vercel) | browser | build (inlined) | public | **yes** when `BACKEND_ORIGIN` is a URL: `wss://api.<domain>` |
| `NEXT_PUBLIC_SITE_URL` | canonical origin (metadata, robots, sitemap) | Next server | build | public | yes; on Vercel defaults to the project's production domain |
| `CONTACT_DELIVERY_URL` / `CONTACT_DELIVERY_TOKEN` | contact-form delivery endpoint / its bearer token | Next server | runtime | URL public, **token secret** | optional (form says delivery is off) |
| `CONTACT_RATE_LIMIT` / `CONTACT_RATE_WINDOW_SECONDS` | per-instance contact limiter | Next server | runtime | public | optional |
| `NEXT_PUBLIC_ANALYTICS_ENABLED` | allow product events at all | browser | build | public | optional (default off) |
| `ANALYTICS_INGEST_URL` / `ANALYTICS_INGEST_TOKEN` | event collector / its token | Next server | runtime | URL public, **token secret** | optional |
| `NEXT_PUBLIC_CONTACT_PREFILL_NAME` | demo convenience | browser | build | public | optional, leave empty |

Currently set on `rehabsense-platform`: `BACKEND_ORIGIN=none`,
`NEXT_PUBLIC_SITE_URL=https://rehabsense-platform.vercel.app`.

The build **fails on purpose** with `RehabSense deployment configuration
invalid` when `BACKEND_ORIGIN` is unset (rather than `none`), when it or
`NEXT_PUBLIC_WS_URL` is not https/wss, or when either points at a local
address. No secret ever needs a `NEXT_PUBLIC_` name.

## 4. Backend environment variables (on the API host, never on Vercel)

Names only; values and meaning in [backend/.env.example](backend/.env.example):
`ENVIRONMENT`, `DEBUG`, `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`,
`COOKIE_SECURE`, `COOKIE_SAMESITE`, `STORAGE_BACKEND`, `STORAGE_LOCAL_DIR`,
`STORAGE_S3_BUCKET`, `STORAGE_S3_PREFIX`, `STORAGE_S3_REGION`,
`STORAGE_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`ALLOW_SIMULATED_DEVICES`, `REQUIRE_REGISTERED_DEVICES`, `DEVICE_INGEST_KEY`,
`RAW_SAMPLE_RETENTION_DAYS`, `STORE_RAW_SAMPLES`, `MAX_REQUEST_BYTES`,
`ML_MODEL_DIR`, `ML_ACTIVITY_MODEL`, `ML_ACTIVITY_MODEL_SINGLE`,
`ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `LOG_LEVEL`, `HW_*`.

**`CORS_ORIGINS` must contain `https://rehabsense-platform.vercel.app`**
(and any custom domain). The API refuses cookie-authenticated writes whose
`Origin` is not listed, and requests proxied by Vercel keep the browser's
`Origin`. Preview URLs are deliberately not listed, so previews cannot write
to the production API.

## 5. Production architecture

```
 Browser ──HTTPS──▶ Vercel: Next.js (rehabsense-platform.vercel.app)
   │                  ├─ pages, edge middleware (session guard)
   │                  ├─ /api/contact, /api/events      (this app's own routes)
   │                  └─ /api/*  ──HTTPS rewrite──▶ FastAPI  (BACKEND_ORIGIN)
   │                                                 │
   └──── WSS + 60 s ticket (NEXT_PUBLIC_WS_URL) ────▶ FastAPI (one process)
                                                     ├─ REST, auth, devices, calibration
                                                     ├─ /ws/ingest/v2 ◀── WSS ── ESP32
                                                     ├─ /ws/live          (dashboards)
                                                     ├─ ML inference (bundled models)
                                                     ├──▶ PostgreSQL (all records)
                                                     └──▶ S3 / R2   (exports, archives)
```

Vercel never connects to PostgreSQL, never runs Python, never trains or loads
models, and never holds a database or storage credential.

## 6. Connecting the API later (switch off frontend-only mode)

1. Host the API (docs/DEPLOYMENT.md steps 1–10) at `https://api.<domain>`,
   with `CORS_ORIGINS=https://rehabsense-platform.vercel.app`.
2. In Vercel set `BACKEND_ORIGIN=https://api.<domain>` and
   `NEXT_PUBLIC_WS_URL=wss://api.<domain>` (Production + Preview).
3. `npx vercel@latest --prod` (or redeploy from the dashboard).
4. `REHABSENSE_API=https://api.<domain> REHABSENSE_FRONTEND=https://rehabsense-platform.vercel.app bash scripts/vercel_readiness_check.sh`
   should end with `VERCEL READY`, then run
   `scripts/deployment_check.py --api https://api.<domain> --frontend https://rehabsense-platform.vercel.app`
   against staging data.

## 7. Manual steps that cannot be automated from here

- Hosting the FastAPI service, PostgreSQL and object storage (no connector
  for an API host exists in this environment).
- Optionally deleting the old `rehabsense` project (irreversible): Vercel
  dashboard → project `rehabsense` → Settings → "Delete Project", or
  `npx vercel@latest project remove rehabsense`.
- The Vercel connector used here has no access to the
  `trivediyash154-7968s-projects` scope for logs, deployment events and
  protected previews (403). Re-authorize it on claude.ai with that scope if
  those should work through the connector; the CLI works regardless.
