# RehabSense — Vercel readiness report

Date: 2026-10-06. Scope: deploying the existing Next.js frontend to a **new**
Vercel project, `rehabsense-platform`, through the real Vercel build
pipeline, then fixing what the real builds reported. Instructions for future
deployments: [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md).

How Vercel was driven:

- **Vercel connector (claude.ai):** created the project, set environment
  variables, read project state.
- **Vercel CLI 62.4.0**, logged in through Vercel's browser device approval:
  uploaded the working tree, read build logs and runtime logs, and ran
  `vercel pull` / `vercel build`.

The CLI was needed because the connector cannot upload a local working tree
in practice: files are passed inline, and `globals.css` (223 KB) and
`package-lock.json` (260 KB) alone exceed what a single call can carry. Its
log, protected-fetch and deletion-link endpoints also returned
`403 Forbidden … scope "trivediyash154-7968s-projects"` for this account. The
connector's own error payload recommends the CLI for those calls.

Nothing was pushed to GitHub (`trivediyash154-source/rehabsense3` is public).
No backend, ML or firmware code was changed by this work.

---

## 1. Original Vercel errors

**First real deployment**: `dpl_CE9f544iqsZuANYV5EDnh6MitvDt`. iad1,
2026-10-06 13:47 UTC, target production (Vercel made the first deployment of
the new project a production target). State: **ERROR**.

```
Warning: Detected "engines": { "node": ">=20.9.0" } in your `package.json` that will
         automatically upgrade when a new major Node.js Version is released.
npm warn deprecated recharts@2.15.4: 1.x and 2.x branches are no longer active.
npm warn deprecated eslint@9.39.5: This version is no longer supported.
npm warn install-scripts 1 package has install scripts not yet covered by allowScripts:
npm warn install-scripts   unrs-resolver@1.12.2 (postinstall: node postinstall.js)
Detected Next.js version: 15.5.25
Running "npm run build"
 ⨯ Failed to load next.config.ts, see more info here https://nextjs.org/docs/messages/next-config-error
> Build error occurred
Error: RehabSense deployment configuration invalid:
  - BACKEND_ORIGIN is not set (the RehabSense API, e.g. https://api.example.com)
  - NEXT_PUBLIC_WS_URL is not set (the API's WebSocket origin, e.g. wss://api.example.com)
  - NEXT_PUBLIC_SITE_URL is not set (this site's origin, e.g. https://rehabsense.vercel.app)
    at assertDeploymentConfig (lib/config.server.ts:56:15)
Error: Command "npm run build" exited with 1
```

**Second real build** (preview `dpl_2bBUk3Eaqf6CEKbxS79969CiYyRo`, READY)
also reported:

```
9 vulnerabilities (1 moderate, 8 high)
```

**Local `vercel pull && vercel build`** (Vercel's pipeline run on this machine):

```
Error: RehabSense deployment configuration invalid:
  - NEXT_PUBLIC_SITE_URL is not set (this site's origin, e.g. https://rehabsense.vercel.app)
```

**Connector**: `403 Forbidden — Trying to access resource under scope
"trivediyash154-7968s-projects". You must re-authenticate to this scope`.
This came from `list_deployment_events`, `get_runtime_logs`,
`web_fetch_vercel_url` and `get_project_deletion_link`.

## 2. Root causes

| Error | Root cause | Why on Vercel | Why local passed | Fix | Class |
|---|---|---|---|---|---|
| `deployment configuration invalid` (all three URLs) | The build guard (`assertDeploymentConfig`) requires the API's https/wss URLs, but **no API host exists**. The repo had no honest way to ship the frontend without one. `NEXT_PUBLIC_SITE_URL` was simply unset | The guard only runs when `VERCEL=1`, so an unconfigured deployment can never silently use localhost | Local builds are not `VERCEL=1` and use the development defaults (`http://localhost:8000`) | Explicit frontend-only mode, `BACKEND_ORIGIN=none` (an *unset* value still fails); `/api/*` answers `503 BACKEND_NOT_CONNECTED`; site URL defaults to Vercel's `VERCEL_PROJECT_PRODUCTION_URL`; both variables set through the connector | CODE FIX REQUIRED + MANUAL VERCEL CONFIGURATION (automated) + EXTERNAL BACKEND INFRASTRUCTURE REQUIRED |
| `engines ">=20.9.0"` warning | Open-ended range: Vercel would jump to Node 26 by itself | Vercel picks Node from `engines` | npm does not warn about this | `">=20.9.0 <25"` (stays on 24.x, which matches local Node 24.16) | CODE FIX |
| `npm install` (default) instead of the locally validated `npm ci` | No install command configured | Vercel's default for npm projects | — | `vercel.json` with `"installCommand": "npm ci"`: lockfile-exact, fails if out of sync | CODE FIX |
| `9 vulnerabilities (1 moderate, 8 high)` | Transitive advisories in build tooling and in `next`'s bundled `postcss` | `npm ci` prints the audit summary | Local installs printed the same summary; it was never acted on | `npm audit fix` (non-breaking only): `next`/`eslint-config-next` 15.5.25 → 15.5.27, `brace-expansion`, `source-map-js`. **7 remain** (see §9) | CODE FIX (partial) |
| `vercel build`: `NEXT_PUBLIC_SITE_URL is not set` | `vercel pull` does not provide `VERCEL_PROJECT_PRODUCTION_URL`; remote builds do (the production deployment's sitemap shows it was present) | — | — | `NEXT_PUBLIC_SITE_URL=https://rehabsense-platform.vercel.app` set explicitly via the connector | MANUAL VERCEL CONFIGURATION (automated) |
| Connector 403 on logs, protected fetch, deletion link | The connector's authorization does not cover this account's team scope for those endpoints | — | — | Used the CLI for those calls. Re-authorizing the connector is optional | External (connector authorization) |
| `recharts` 2.x / `eslint` 9 deprecations; `unrs-resolver` postinstall not allow-listed | Upstream end-of-life notices; npm 11's new script allow-list | — | Same warnings locally | Not blockers: lint and type checks pass on Vercel. Recharts 3 is a breaking API migration, deliberately not done here | none |

## 3. Changes made

| File | Why |
|---|---|
| `lib/config.server.ts` | `backendConnected()`: `BACKEND_ORIGIN=none` declares a frontend-only deployment. Site URL falls back to `VERCEL_PROJECT_PRODUCTION_URL`. The error message names the `none` option. A build-log notice is printed in frontend-only mode |
| `next.config.ts` | `/api/*` is rewritten to the API, or (frontend-only) to `/backend-unavailable` |
| `app/backend-unavailable/route.ts` (new) | Answers every backend path with `503 {"code":"BACKEND_NOT_CONNECTED","message":…}` so the sign-in form and the workspace state the truth instead of showing an HTML 404. Returns 404 when an API is configured |
| `lib/server/session.ts` | No server-side session lookup when no API exists |
| `vercel.json` (new) | `framework: nextjs`, `installCommand: npm ci` |
| `package.json` | `engines.node: ">=20.9.0 <25"` |
| `package-lock.json` | Non-breaking `npm audit fix` |
| `.vercelignore` | Also excludes `.pytest_cache/`, `__pycache__/`, `*.tsbuildinfo`, `*.log`, `docker-compose.yml`, `.dockerignore`, `.env*` (except the example) and `*.md` |
| `.gitignore` | `.vercel` (CLI link and local build output) |
| `.env.example` | Documents `BACKEND_ORIGIN=none` and the site-URL default |
| `scripts/vercel_readiness_check.sh` (new) | Automated readiness check (§4) |
| `VERCEL_DEPLOYMENT.md` (new), `README.md`, `docs/DEPLOYMENT.md`, `docs/DEPLOYMENT_AUDIT.md`, `docs/HARDWARE_VALIDATION_STATUS.md` | Instructions and deployment status |

Unchanged: `backend/`, `ml/` (model bundles re-verified by SHA-256),
`firmware/`, the authentication system, the database schema, TypeScript and
ESLint settings. No `any`, `@ts-ignore`, `eslint-disable`, `ignoreBuildErrors`
or `ignoreDuringBuilds` was added; Vercel's log shows
`Linting and checking validity of types` running.

Vercel side:

- **Project:** `rehabsense-platform` (`prj_ohl5XWEARZ5eXHeFMtvBTX6SUJyS`, Next.js, Node 24.x, root directory = repository root).
- **Variables:** `BACKEND_ORIGIN=none` and `NEXT_PUBLIC_SITE_URL=https://rehabsense-platform.vercel.app` (Production + Preview).

## 4. Local tests

Run in a clean copy of exactly the upload set (`.vercelignore` applied):

| Command | Result |
|---|---|
| `npm ci` | PASS (424 packages) |
| `npm run lint` / `npm run typecheck` | PASS / PASS |
| `VERCEL=1 npm run build` (nothing set) | FAILS as designed, with the configuration message |
| `VERCEL=1 BACKEND_ORIGIN=none … npm run build`, then `next start` | PASS. `/` `/login` `/signup` `/dashboard` `/contact` 200; `/workspace` 307 → `/login?next=…`; `GET /api/health` and `POST /api/auth/login` 503 `BACKEND_NOT_CONNECTED`; own route `/api/contact` still handled locally |
| `VERCEL=1 BACKEND_ORIGIN=https://… NEXT_PUBLIC_WS_URL=wss://… npm run build` | PASS. Rewrite `/api/:path*` → `https://…/api/:path*`; browser JS contains the wss URL only, no `BACKEND_ORIGIN`, secrets, local addresses or paths |
| `vercel pull --environment=preview && vercel build` | PASS once the site URL is set. Vercel output routes `/api/*` → `/backend-unavailable` function |
| Proxy regression with a real local API (Next 15.5.27): `scripts/deployment_check.py --api … --frontend …` | **24 passed, 0 failed, 2 skipped** (signup through the proxy, cookie, authenticated `/workspace/hardware`, simulator → calibration → ML → DB) |
| Bundle-scan negative test (planted `postgres://` and `ws://localhost:8000`) | All three scans detect them |
| `backend` pytest / `ml` pytest | 231 passed / 8 passed |
| Model bundles (`ModelBundle.load`, SHA-256) | both verified, unchanged |
| `bash scripts/vercel_readiness_check.sh` (+ `REHABSENSE_FRONTEND=https://rehabsense-platform.vercel.app`) | 15 PASS, 0 FAIL → `VERCEL READY — EXTERNAL BACKEND INFRASTRUCTURE REQUIRED` |

## 5. Vercel build

**PASS.** The first build failed (§1). Every build after the fix succeeded,
running `npm ci`, ESLint and type checking on Vercel.

## 6. Actual Vercel deployment

**PASS (frontend-only).**

| Deployment | Target | Status | URL |
|---|---|---|---|
| `dpl_CE9f544iqsZuANYV5EDnh6MitvDt` | production (first) | ERROR (§1) | — |
| `dpl_2bBUk3Eaqf6CEKbxS79969CiYyRo` | preview | READY | rehabsense-platform-5cu728spf-trivediyash154-7968s-projects.vercel.app (Vercel login required) |
| `dpl_sVdLLuVJiMirioiCcuXmZQda29iQ` | production | READY, superseded | rehabsense-platform-7mbw7hpyr-… |
| **`dpl_G2ccYE2yjF9Mu3P5TkVasbfJDR1b`** | **production** | **READY, current** | **https://rehabsense-platform.vercel.app** |

Verified on the public production URL with anonymous `curl`:

- **Pages:** `/`, `/login`, `/signup`, `/dashboard`, `/contact`, `/forgot-password`, `/robots.txt` and `/sitemap.xml` return 200; `/dev/integration` and unknown paths return 404.
- **Protected pages:** `/workspace/*` returns 307 to `/login`.
- **Backend paths:** `/api/*` returns 503 `BACKEND_NOT_CONNECTED`.
- **Site URL:** `sitemap.xml` and `robots.txt` use `https://rehabsense-platform.vercel.app`.
- **Headers:** `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `COOP` and HSTS are present; there is no `x-powered-by`.

Runtime logs (CLI) show 0 error/fatal entries, and the only 5xx responses
are the intended `/api/*` 503s.

**Not verified, because no API exists:** sign-in, logout, refresh, patient
and session creation, the dashboard with recorded data, ML results, and the
production WebSocket. They were verified locally through the same proxy code
(§4). **Vercel frontend deployment verified. Production backend integration
pending external API hosting.**

## 7. Environment variables

- **Vercel, set:**
  - `BACKEND_ORIGIN` (`none` until the API exists)
  - `NEXT_PUBLIC_SITE_URL`
- **Vercel, needed once the API exists:**
  - `BACKEND_ORIGIN` (`https://api.<domain>`)
  - `NEXT_PUBLIC_WS_URL` (`wss://api.<domain>`)
- **Vercel, optional:**
  - `CONTACT_DELIVERY_URL`, `CONTACT_DELIVERY_TOKEN` (secret), `CONTACT_RATE_LIMIT`, `CONTACT_RATE_WINDOW_SECONDS`
  - `NEXT_PUBLIC_ANALYTICS_ENABLED`, `ANALYTICS_INGEST_URL`, `ANALYTICS_INGEST_TOKEN` (secret)
  - `NEXT_PUBLIC_CONTACT_PREFILL_NAME`
- **API host only, never Vercel:**
  - `ENVIRONMENT`, `DEBUG`, `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, `COOKIE_SECURE`, `COOKIE_SAMESITE`
  - `STORAGE_BACKEND`, `STORAGE_S3_BUCKET`, `STORAGE_S3_REGION`, `STORAGE_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
  - `ALLOW_SIMULATED_DEVICES`, `REQUIRE_REGISTERED_DEVICES`, `RAW_SAMPLE_RETENTION_DAYS`
  - `ML_MODEL_DIR` and others (VERCEL_DEPLOYMENT.md §4)

No secret is, or needs to be, a `NEXT_PUBLIC_` variable (checked
automatically).

## 8. Architecture

```
Vercel (Next.js, rehabsense-platform.vercel.app)
  │  /api/*  HTTPS rewrite (BACKEND_ORIGIN)           browser ── WSS + ticket ──┐
  ▼                                                                             ▼
FastAPI (one process: REST, auth, devices, calibration, ML inference, WebSockets)
  ├──▶ PostgreSQL (all records)
  └──▶ S3 / R2 (exports, archives)

ESP32 ── WSS (per-device key) ──▶ FastAPI
```

The frontend never connects to PostgreSQL, never runs Python or trains a
model, and holds no database or storage credential. ML status is unchanged:

```
MODEL IMPLEMENTED                  YES
PUBLIC DATASET VALIDATED           YES
REAL REHABSENSE HARDWARE VALIDATED NO
HUMAN-LABELED PHYSICAL DATA        0
CLINICAL VALIDATION                NO
```

## 9. Remaining manual actions

1. **EXTERNAL BACKEND INFRASTRUCTURE:** host the FastAPI image
   (`docker build -f backend/Dockerfile .`, not yet built anywhere), managed
   PostgreSQL 16 and an S3/R2 bucket (docs/DEPLOYMENT.md steps 1–10), with
   `CORS_ORIGINS=https://rehabsense-platform.vercel.app`.
2. Then set `BACKEND_ORIGIN` and `NEXT_PUBLIC_WS_URL` on Vercel and redeploy
   (VERCEL_DEPLOYMENT.md §6). Run the readiness check with `REHABSENSE_API`
   and `deployment_check.py` against staging.
3. Residual npm advisories (7):
   - **ESLint toolchain chain:** build-time only, reachable only through our own lint config.
   - **`next`'s bundled `postcss`:** matters only for untrusted CSS, and this app compiles only its own.

   Clearing them requires a planned Next.js 16 migration (semver-major), not
   a deployment change.
4. Optional: delete the old `rehabsense` project (irreversible; dashboard →
   Settings → Delete Project, or `npx vercel@latest project remove rehabsense`).
5. Optional: re-authorize the Vercel connector for the
   `trivediyash154-7968s-projects` scope, so logs and protected previews also
   work through it.

## 10. Final verdict

```
VERCEL READY — EXTERNAL BACKEND INFRASTRUCTURE REQUIRED
```
