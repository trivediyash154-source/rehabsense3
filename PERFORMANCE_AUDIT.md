# RehabSense performance audit (live site)

**Status:** fixes implemented and tested locally; **not yet deployed**. The
"after" column is filled only from production measurements taken after the
redeploy. No improvement is claimed before it is measured.

## Method

- **Where measured:** the live site, `https://rehabsense-platform.vercel.app` and
  `https://rehabsense-api.vercel.app`, on 2026-10-07 between 23:03 and 23:30 UTC.
- **Browser:** real Chromium (Playwright) on a laptop in India. Vercel routed it
  through its **Mumbai edge (`bom1`)**:
  - pages render in `iad1` (Washington DC);
  - the API runs in `cle1` (Cleveland), next to Neon PostgreSQL in `us-east-2`.
- **Recorded per page:** DOMContentLoaded, LCP, every `/api` request with its
  start and end times, the request chain, duplicates and JavaScript transferred.
- **Recorded per action:** email signup, then login, each until the workspace URL;
  logout.
- **Also measured:** `curl` timings for cold and warm API requests, and Python
  import profiling of the API (`python -X importtime`).
- **Scripts:** in the session scratchpad (`perf.js`); they create clearly-labelled
  `perf-…@example.com` accounts.

Two baseline runs were made against the current production deployment (the code
before this change). Times are milliseconds from navigation start.

## Findings

| Metric | Current measurement | Root cause | Fix | Measurement after fix |
|---|---|---|---|---|
| **API cold start** (first request after about 5 min idle) | 4.75 s TTFB (curl). Repeated mid-sequence cold instances: 4.2 s, and 4.85 s and 5.12 s in the browser. | Vercel scales the container to zero; a new instance boots the image, imports Python (0.45–0.8 s measured), connects to Neon (which itself wakes from scale-to-zero) and checks the schema. Not caused by app code. | Not removable on the free plan: no minimum instances, and a keep-warm pinger would burn the Hobby memory allowance. Every user-facing path was changed to **tolerate** it (rows below). | pending redeploy |
| **Warm API round trip** | 0.25–0.27 s (`/api/health`, `/api/auth/me`) | Distance: Mumbai edge → Cleveland function. The function sits next to the database, so each request is one long trip rather than many. | None in this change. See "Not changed". | n/a |
| **Sign-in / sign-up page: API probe** | 0.28–0.33 s warm. **4.85 s and 5.12 s** when the instance was cold. "Checking the connection…" showed for up to 5 s. | `/api/health` probe, 5 s timeout. A cold instance answers just under it. | The probe is now `/api/auth/providers`: no database, and it also returns which sign-in methods exist (no extra request for the buttons). The timeout is 8 s, so a waking API is not reported as down. After 2 s the line says "Waking the RehabSense API…". Social buttons work while the probe runs: the server decides. | pending redeploy |
| **Signed-in page, first render with a cold API** | DCL **3.40 s**, LCP **4.68 s** (dashboard) | `getServerUser()` held the server render up to **3 s** for `/api/auth/me`, timed out, and the browser then fetched `/me` again (a duplicate). | Server timeout cut to **1.5 s** (a warm API answers in well under 100 ms from `iad1`). On timeout the page renders and the browser confirms the session. | pending redeploy |
| **Anonymous page renders** | One server→API `/me` call (answering 401) on **every** page render for any visitor with any cookie, e.g. the cookie-consent cookie | The check ran whenever *any* cookie existed | The API is asked only when an `rs_session` cookie exists | pending redeploy |
| **Workspace data load** (dashboard, patients, hardware) | Data done at **1.56–1.69 s** with a warm API. Chain: `/api/health` → `/api/me` → `/api/patients` → `/api/progress`, four sequential round trips, with a 0.35 s gap. The `/api/me` result was never used. | Waterfall in `DataProvider.load()` | One request answers all three questions: 401 means signed out, network or 5xx means unreachable, otherwise it is the roster. The chain is now **patients → progress**: 2 round trips instead of 4. | pending redeploy |
| **Workspace right after a cold start** | Showed **"The RehabSense API is not responding."** | The `probeBackend()` timeout of **1.5 s** was shorter than a 4–5 s cold start, so "waking" was reported as "offline" | Probe removed; no artificial timeout on the roster request | pending redeploy |
| **Email signup → workspace** | **5.82 s** and **5.96 s** (signup API itself: 0.69 s) | After the 201: an extra `/api/auth/me`, a fixed **550 ms** pause, then `router.replace` **and** `router.refresh()` (a second server render) | Adopt the user from the signup response (`setSignedIn`), navigate immediately, no refresh | pending redeploy |
| **Email login → workspace** | **2.03 s** and **2.48 s** (login API: 0.57–1.02 s) | Same as signup | Same as signup | pending redeploy |
| `GET /api/auth/me` | 0.24–0.65 s (first on a new connection is slowest) | Geography plus connection setup | n/a | n/a |
| **Hardware page: `/api/ml/models`** | **3.27–3.44 s** on the first call per instance | `model_store.status()` loads both bundles (736 MB) to report them | **Not changed.** This deliberately warms the models before a device session, so the first inference does not stall calibration. Documented. | n/a |
| **Home page JS** | 678 KB in 26 files (cold cache); LCP 1.66–2.62 s | 3D scenes (three.js) | Not changed in this task (no auth impact) | n/a |
| **OAuth start** (`/api/auth/{provider}/start`) | New. No database work: the state is a signed cookie. | n/a | Designed to need no DB round trip | pending redeploy and provider configuration |
| **OAuth callback** | New. One state insert, one provider exchange, one identity lookup, one commit. | n/a | n/a | pending redeploy and provider configuration |
| **WebSocket connection** | Not re-measured in this pass (unchanged code; last session: 79 frames over WSS, calibration PASS) | n/a | n/a | n/a |

## Checked and not found

- **Redirect loops:** none. `/workspace` while signed out gives one `307` to `/login?next=…`.
- **Retry or polling loops:** none during any 15 s network-idle window.
- **Repeated auth checks:** `/api/auth/me` (client) plus `/api/me` (DataProvider) on
  the same load. Fixed above.
- **Failed requests:** none.
- **Blocking server work:** apart from the `/me` wait above, none.
- **API import time:** 0.45–0.8 s locally, so not the main cold-start cost.

## Not changed (with measured reasons)

- **Static rendering of public pages.** The root layout reads cookies, so every page,
  including `/`, `/privacy` and `/cookies`, is server-rendered in `iad1`: page TTFB is
  0.30–0.40 s from India instead of an edge cache hit. Fixing it means moving session
  resolution out of the root layout, which affects the header on every page; deferred.
- **Region.** About 250 ms per API round trip comes from India → Cleveland. Moving the
  API and the database to Singapore (`sin1` plus Neon `ap-southeast-1`) would cut it
  roughly fourfold for users in India. It needs a new Neon project and a data copy, so
  it is a separate, deliberate change.
- **Free-plan cold starts** are platform behaviour. They are now *waited out* instead
  of being shown as errors.
