# Authentication production report

**Date:** 2026-10-07

**Live site:** <https://rehabsense-platform.vercel.app>. The API is
<https://rehabsense-api.vercel.app>.

**Infrastructure:** both run in Vercel region `sin1`, with PostgreSQL 17 on Neon
(`ancient-queen-09719759`, AWS ap-southeast-1, in the owner's account).

**Code:** commit `9e4cb6d` (`main`). Every deployment records its commit SHA (see
[VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md)).

## Result table

Values are limited to PASS, FAIL, NOT CONFIGURED and NOT TESTED.

- "Implementation" means the code exists and its automated tests pass: 290 backend tests
  on SQLite **and** PostgreSQL 16, plus 29 + 9 + 13 browser checks against a local
  production build.
- "Live Browser Test" means a real Chromium browser on the **live** website. Every step
  was also checked in the production PostgreSQL database.

| Feature | Implementation | Live Browser Test | Status |
|---|---|---|---|
| Email signup | PASS | PASS | PASS |
| Email login | PASS | PASS | PASS |
| Email logout | PASS | PASS | PASS |
| Google OAuth | PASS | NOT TESTED | NOT CONFIGURED |
| Google returning login | PASS | NOT TESTED | NOT CONFIGURED |
| Facebook OAuth | PASS | NOT TESTED | NOT CONFIGURED |
| Facebook returning login | PASS | NOT TESTED | NOT CONFIGURED |
| Session persistence | PASS | PASS | PASS |
| Protected routes | PASS | PASS | PASS |
| User isolation | PASS | PASS | PASS |
| Phone OTP | NOT CONFIGURED | NOT TESTED | NOT CONFIGURED |

Google and Facebook are NOT CONFIGURED because they need OAuth credentials created in
the owner's Google Cloud and Meta developer accounts. No other part of the work is
waiting. The live site shows both buttons with a **Not configured** badge. Clicking one
explains this and keeps email sign-in available; nothing redirects and no session is
created. That behaviour was verified live (checks 18 and 18b below).

Phone OTP is deliberately not offered: no SMS provider is connected. `/verify-phone`
says so and has no code inputs (check 17, live).

## Live browser test: email, sessions, records, isolation

Script `prod_e2e.js`, real Chromium on <https://rehabsense-platform.vercel.app>, with
each step queried in the production database. **29/29 PASS.**

| # | Check | Result |
|---|---|---|
| 01 | Site opens (`x-vercel-id: bom1::sin1`) | PASS |
| 02 | Signup through the form lands in the workspace | PASS (1.28 s) |
| 03 | User row in PostgreSQL with an `$argon2id$` hash | PASS |
| 04 | Logout, then login through the form | PASS (0.76 s) |
| 05 | `rs_session` is HttpOnly + Secure + SameSite=Lax; no token in localStorage or sessionStorage | PASS |
| 06 | Protected dashboard recognises the session (`/api/auth/me` 200) | PASS |
| 07 | Still signed in after a refresh and in a second tab | PASS |
| 07c | Settings → Sign-in methods: password set, Google and Facebook "Not configured" | PASS |
| 08 | Hardware Lab: live socket `wss://rehabsense-api.vercel.app/ws/live/…`, frames arriving, stream labelled SIMULATED | PASS |
| 09 | Patient created through the UI and stored in PostgreSQL | PASS |
| 10 | Session created and stored in PostgreSQL | PASS |
| 11 | Calibration, 29 raw-sample chunks and 44 ML results (`activity_bilateral/v1`) stored | PASS |
| 11b | Session ended, stored as COMPLETED | PASS |
| 12 | After sign-out, `/api/auth/me` and `/api/patients` return 401 | PASS |
| 13 | After sign-out, `/workspace`, `/workspace/patients` and `/workspace/hardware` redirect to `/login` | PASS |
| 14–15 | Sign in again: the patient and session are still there | PASS |
| 16 | A second user gets 404 on the first user's patient and session, and doesn't see them in the list | PASS |
| 17 | `/verify-phone` states phone verification is unavailable (no inputs) | PASS |
| 18 | Social buttons "Not configured"; a click explains, with no redirect and no session | PASS |
| 18b | `/api/auth/facebook/start` with no credentials goes back to `/login?oauth_error=not_configured` | PASS |
| 19 | Development seed endpoint refused in production | PASS |
| 20 | Account deletion removes the user row | PASS |

## Live API and security checks

| Check | Result |
|---|---|
| `scripts/deployment_check.py` against the production URLs | **28 passed, 0 failed, 1 skipped**. Covers health (database, schema, ML, storage, realtime), register and login, 401 without credentials, isolation, device registration, wrong key / revoked device refused, simulator over WSS, calibration, ML inference (38 windows), movement analysis, raw-sample storage, recording integrity and the frontend proxy. The skip is physical hardware. |
| CORS preflight from `https://evil.example` | 400, no `Access-Control-Allow-Origin` |
| CORS preflight from the website | exact origin plus `Access-Control-Allow-Credentials: true` |
| Cookie-authenticated write with a foreign `Origin` | 403 `Request origin is not allowed.`; the session stays intact |
| 2 MB request body | 413 `PAYLOAD_TOO_LARGE` |
| `/docs`, `/redoc`, `/openapi.json` | 404 (interactive API docs are off in production) |
| Website headers | HSTS (2 years, preload), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy` |
| Repository secret scan (Neon, Google, AWS, Vercel and GitHub key patterns, private keys) | none found; only `.env.example` files tracked |

## To make Google and Facebook live

Only the account owner can create the provider apps; nothing else is outstanding. Once
the four values exist (Google client ID and secret, Facebook app ID and secret), they are
stored as Sensitive Vercel variables, the API is redeployed, and Google and Facebook
sign-in are tested live: new user, returning user, cancel, logout and the same-email
account case. See [GOOGLE_OAUTH_SETUP.md](GOOGLE_OAUTH_SETUP.md) and
[FACEBOOK_OAUTH_SETUP.md](FACEBOOK_OAUTH_SETUP.md).

## Verdict

**PRODUCTION PARTIALLY WORKING.**

- **Working live, end to end:** email/password, sessions, records, isolation, devices,
  the simulator, ML and the database.
- **Not configured:** Google and Facebook, until their credentials exist.
- **Not configured:** phone OTP, by design.
