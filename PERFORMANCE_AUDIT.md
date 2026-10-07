# RehabSense performance audit (live site)

All numbers below were measured on the **live site** with a real browser. Nothing is
estimated, and no improvement is claimed without a measurement after it.

## Method

- **Where measured:** `https://rehabsense-platform.vercel.app` and
  `https://rehabsense-api.vercel.app`, from a laptop in India (Pune). Vercel's edge
  entry point is Mumbai (`bom1`).
- **Tools:**
  - Real Chromium (Playwright) recording navigation timing, LCP, every `/api` request
    with its start and end, duplicate requests and JavaScript transferred;
  - `curl` for single-request timing;
  - the API's own startup log, which now records process start, import time and
    startup database time.
- **Baseline:** two runs on 2026-10-07 between 23:03 and 23:30 UTC (Oct 6), with the
  previous code. Website functions ran in `iad1` (Washington DC), the API in `cle1`
  (Cleveland), the database in Neon `us-east-2` (Ohio).
- **After:** runs on 2026-10-07 between 01:50 and 02:25 UTC, with the new code.
  Website, API and database are all in Singapore (`sin1`, Neon `ap-southeast-1`).
- **Units:** milliseconds from navigation start unless stated.

## Results

| Metric | Before | Root cause | Fix | After |
|---|---|---|---|---|
| **Warm API round trip** (`/api/auth/me` from the page) | 235–280 ms | Every request travelled Mumbai → Cleveland | Moved the API **and** the database to Singapore (the closest Neon region to India) and the website's server functions with them | **103–171 ms** |
| **Dashboard: data loaded** | 1,690 ms | Four **sequential** requests: `/api/health` → `/api/me` (result never used) → `/api/patients` → progress | One request answers "signed in?", "API up?" and "which records?" | **550 ms** |
| **Dashboard: LCP** | 1,816 ms warm; **4,680 ms** with a cold API | The above, plus the server render waiting **up to 3 s** for `/api/auth/me` | The above, plus a 1.5 s server timeout | **616 ms** |
| **Patients page: data loaded** | 1,556 ms | Same waterfall | Same fix | **539 ms** |
| **Workspace right after a cold start** | Showed **"The RehabSense API is not responding."** | A 1.5 s health probe, shorter than a cold start | Probe removed; requests are waited out instead of declared failed | No false "offline" in any run |
| **Email login → workspace** | 2,025–2,476 ms | An extra `/me`, a fixed **550 ms** pause and a second server render after login | Use the user the login response already returns; navigate immediately | **761–859 ms** |
| **Email signup → workspace** | 5,815–5,964 ms | Same as login | Same | **1,279 ms** warm. One run hit a fresh API instance: 8,435 ms, see cold starts below. |
| **Sign-in page: API check** | 282–330 ms warm; **4,846–5,123 ms** cold | `/api/health` on a cold instance, with "Checking the connection…" showing for 5 s | Database-free `/api/auth/providers`, which also returns the sign-in methods. After 2 s the page says "Waking the RehabSense API…" | **100–270 ms** warm; cold: see below |
| **Anonymous page renders** | One server→API `/me` call per page for anyone holding *any* cookie (e.g. the cookie-consent choice) | The check ran on any cookie | The API is asked only when an `rs_session` cookie exists | 0 calls |
| **API cold start** (curl, first request of a fresh instance) | 9.47 s | Vercel boots the container: **5.41 s** before Python starts. Then **imports 3.02 s** (no compiled bytecode in the image, because `PYTHONDONTWRITEBYTECODE`; Alembic's script machinery loaded only to read the head revision). Then **startup DB 0.41 s**. | Bytecode precompiled in the image; the schema check reads the head from the migration files (a test pins it to Alembic's answer); test packages (pytest, moto) dropped from the image | **7.57 s**: platform 5.46 s, **imports 1.55 s**, **startup DB 0.24 s** |
| **Hardware page: `/api/ml/models`** | 3,269–3,442 ms on the first call of an instance | Loads both model bundles (736 MB) to report them | **Not changed.** This deliberately warms the models before a device session, so the first inference doesn't stall calibration. | 3.8 s on a fresh instance (same reason) |
| **Home page JS** | 678 KB / 26 files on a cold cache; LCP 1.7–2.6 s | 3D scenes (three.js) | Not changed in this task | n/a |

## Cold starts: what can and cannot be changed

- **Platform behaviour.** The API runs as a container on Vercel's free plan.
  - An instance with no traffic for **5 minutes** is stopped (Vercel's documented
    scale-down).
  - The next request waits for a new one: **about 5.5 s of platform boot**, which no
    application change can remove, plus our own startup, now **about 1.8 s**.
  - Vercel also starts extra instances under load. In the logs this happened during
    test traffic, e.g. while one instance was busy loading the ML models.
- **No way to keep it warm for free.** The free plan has no minimum-instances
  setting. A keep-alive pinger would burn the free memory allowance and get the
  project paused.
- **What the site does instead:**
  - **Starts the wake-up early.** The landing page sends one database-free request
    to the API when it is idle, so the API boots while the visitor reads.
  - **Says so honestly.** The sign-in page says "Waking the RehabSense API…" after
    2 s. It never reports a waking API as "offline", and never shows a success it
    has not received.

### Measured after 6+ minutes of idle (live)

| Scenario | Result |
|---|---|
| A. Straight to `/login` on a cold API | _measuring_ |
| B. Landing page, 10 s of reading, then `/login` | _measuring_ |

## Checked and not found

- **Redirect loops:** none. `/workspace` while signed out gives one `307` to `/login?next=…`.
- **Retry or polling loops:** none in any 15 s network-idle window.
- **Duplicate requests:** `/api/auth/me` (client) plus `/api/me` (DataProvider) on the
  same load. Fixed above; none remain.
- **Failed requests:** none.

## Not changed (with measured reasons)

- **Static rendering of public pages.** The root layout reads cookies, so every page is
  server-rendered: TTFB about 0.2–0.4 s from India, now served from Singapore. Making
  `/`, `/privacy` and `/cookies` static means moving session resolution out of the root
  layout, which affects the header on every page; deferred.
- **ML model warm-up on the hardware page.** Intentional, see above.
