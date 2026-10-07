# RehabSense

A research prototype interface for a wearable lower-limb rehabilitation sensing
concept, initially focused on ACL recovery. The site communicates the idea —
bilateral movement capture, time-synchronised comparison, and explainable
recovery indicators — without claiming capabilities the system does not have.

**RehabSense is not a medical device.** It is not certified, cleared or
clinically validated. Demo figures are invented and labelled as demo data;
figures from the backend are research outputs from recorded (or explicitly
SIMULATED) sessions. Nothing here diagnoses, treats or prescribes.

Live: https://rehabsense-platform.vercel.app (website) and
https://rehabsense-api.vercel.app (API), both on Vercel's free plan, with Neon
PostgreSQL · [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md) ·
Deployment: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (steps) ·
[docs/DEPLOYMENT_AUDIT.md](docs/DEPLOYMENT_AUDIT.md) (what runs where) ·
[docs/POSTGRESQL_VALIDATION.md](docs/POSTGRESQL_VALIDATION.md) ·
[docs/HARDWARE_VALIDATION_STATUS.md](docs/HARDWARE_VALIDATION_STATUS.md).

---

## Running it

The frontend runs standalone on the illustrative demo dataset, or against the
real backend for live recorded data.

**Frontend only** — no backend required:

```bash
npm install
npm run dev        # http://localhost:3000
```

**Full stack** — three terminals:

```bash
# 1. backend (development posture: SQLite, local storage, simulators allowed)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 2. frontend (BACKEND_ORIGIN / NEXT_PUBLIC_WS_URL default to localhost:8000 in dev)
cp .env.example .env.local
npm run dev

# 3. seed a demo dataset by driving the real pipeline
cd backend && python -m scripts.seed_demo
#    then sign in at /login with demo@example.com / a-very-long-demo-passphrase
```

Stream a single live session into the workspace:

```bash
cd backend
python -m app.simulator.sensor_simulator --session-id 1 \
    --exercise WALK --operated-leg LEFT --scenario ASYMMETRY --seed 42 --fsr
```

### Hardware v2: one ESP32, two MPU6050s, force sensors

The target device streams over protocol v2 (`docs/SENSOR_PROTOCOL_V2.md`) to
`/ws/ingest/v2/{session_id}`. In the workspace, open **Hardware**, choose an
exercise, then either **Start simulated device** (clearly labelled SIMULATED
DATA) or **Wait for real ESP32** and flash `firmware/rehabsense_dual_imu/` with
that session id. From the terminal:

```bash
cd backend
python -m app.simulator.dual_imu_simulator --session-id 1 --exercise SQUAT --scenario ASYMMETRIC
python -m app.simulator.dual_imu_simulator --list-scenarios
```

Architecture, ML stages, domain-gap strategy and validation status:
[docs/HARDWARE_ML_ARCHITECTURE.md](docs/HARDWARE_ML_ARCHITECTURE.md). Training
code: [ml/README.md](ml/README.md).

### Accounts

`/signup` and `/login` create and use real accounts on the backend. Passwords
are stored only as Argon2id hashes; the session is an **HttpOnly** cookie that
no page script can read, so an injected script has no credential to steal.
`/workspace` is guarded in `middleware.ts` before the page renders, and every
API response is authorised server-side against the real session — a patient
cannot reach another patient's records by editing a URL, and an unauthorised
record answers 404 rather than confirming it exists.

**Continue with Google** and **Continue with Facebook** use the real providers
(authorization-code flow, verified server-side) and end in the same HttpOnly
session as email sign-in. Each is offered only once its credentials are set on
the API ([GOOGLE_OAUTH_SETUP.md](GOOGLE_OAUTH_SETUP.md),
[FACEBOOK_OAUTH_SETUP.md](FACEBOOK_OAUTH_SETUP.md)); until then the button says
"Not configured". Accounts are never merged by email: a provider is connected to
an existing account only while signed in to it (Settings → Sign-in methods).
Design: [AUTHENTICATION_ARCHITECTURE.md](AUTHENTICATION_ARCHITECTURE.md).
Password-reset email and SMS verification are **not** configured; those screens
say so instead of implying a message was sent.

The workspace header always states its data source: **LIVE BACKEND · SIGNED
IN**, **BACKEND REACHABLE · NOT SIGNED IN · SHOWING DEMO DATA**, or **DEMO DATA
· NO BACKEND CONNECTED**. Demo figures are never presented as recorded ones.

See [backend/README.md](backend/README.md) for the API, the signal-processing
maths, the hardware protocol and the security model.

```bash
npm run build      # production build
npm start          # serve the production build
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
```

Node 20.9+ is expected. Development needs no environment variables. A Vercel
build **fails on purpose** unless `BACKEND_ORIGIN` (https), `NEXT_PUBLIC_WS_URL`
(wss) and `NEXT_PUBLIC_SITE_URL` (https) are set — there is no silent localhost
fallback in production.

---

## What is real and what is not

| Area | Status |
|---|---|
| Landing page, navigation, theming | Implemented |
| Sign up / sign in | Implemented against the FastAPI backend (Argon2id, HttpOnly cookie) |
| Google / Facebook sign-in | Implemented (real OAuth, server-side verification, identity table, no email merge). **Google is live**; Facebook is live once its credentials are set |
| Password reset email, SMS verification | **Not configured**; the screens say so |
| Account deletion | Implemented (Settings → Delete account) |
| Contact form | Implemented; **delivery is off** until configured |
| Demo dashboard | Implemented against **illustrative, invented data**, labelled as such |
| Workspace (patients, sessions, live view, hardware lab) | Implemented against the backend |
| Synthetic demonstration cohort (5 fictional records + 1 public-dataset reference, 69 sessions) | **Generated data, labelled everywhere.** Streamed through the real ingestion, calibration, ML and analytics pipeline by `backend/scripts/seed_demo_data.py`. Not patient data, not hardware data, not clinical evidence. See [docs/SYNTHETIC_DEMONSTRATION_DATA.md](docs/SYNTHETIC_DEMONSTRATION_DATA.md) |
| Movement progress reports (PDF) | Implemented: frozen report payload rendered server-side. Every page states its provenance and "research prototype, not a medical device" |
| FastAPI service, PostgreSQL schema, ingestion, analytics, ML inference | Implemented; tested on SQLite and PostgreSQL 16.2 |
| ESP32 firmware (1 ESP32 + 2×MPU6050 + FSR) | Implemented, compiles; **not tested on a physical board** |
| ML activity model | Validated on public datasets only; **0 human-labelled physical recordings** |
| Clinical validity | **None.** Not a medical device |
| Website + API on Vercel (free), PostgreSQL on Neon (free) | **Deployed and tested end to end** (sign-up, login, patients, sessions, device auth over WSS, simulator, ML inference, live dashboard). See VERCEL_DEPLOYMENT.md |
| Object storage (S3/R2) | **Not deployed**; exports use the API's temporary disk |

### Contact delivery

Delivery is off until `CONTACT_DELIVERY_URL` points at a trusted HTTPS endpoint
that you control. While unset, `/api/contact` returns `503
CONTACT_NOT_CONFIGURED`, the form shows an honest failure state with a developer
note, and the user's entries are preserved. **No fake success screen is ever
shown** — the success state requires a 2xx from the configured endpoint.

When configured, the route validates on the server, enforces same-origin, caps
body size, applies a small in-process rate limit, strips the honeypot field, and
requires HTTPS with `redirect: "error"`. Message contents are never logged.

> The in-memory limiter in `lib/rate-limit.ts` is per-process and resets on
> redeploy. Put a shared limiter (edge / WAF / Redis) in front of any public
> deployment.

### Product event logging

Events are sent only when **both** `NEXT_PUBLIC_ANALYTICS_ENABLED=true` and
`ANALYTICS_INGEST_URL` are set. `lib/analytics.ts` defines closed allowlists for
event names, routes, actions, providers and error codes; `sanitize()` drops
anything else, and `/api/events` re-validates against the same allowlists with
`.strict()` so a modified client cannot push free-form values through.

Never logged: passwords, OTPs, OAuth or session tokens, contact message
contents, raw sensor data, or medical information. `navigator.doNotTrack` is
honoured before anything is queued.

---

## Environment variables

Frontend: `.env.example` (development defaults to localhost). Backend:
`backend/.env.example`.

| Variable | Purpose |
|---|---|
| `BACKEND_ORIGIN` | Server-only. API origin that `/api/*` is proxied to. **Required on Vercel:** an https URL, or `none` for a frontend-only deployment. |
| `NEXT_PUBLIC_WS_URL` | API WebSocket origin for the live view. **Required (wss) on Vercel** when an API is connected. |
| `CONTACT_DELIVERY_URL` | HTTPS endpoint receiving contact submissions. Enables the form. |
| `CONTACT_DELIVERY_TOKEN` | Optional bearer token for that endpoint. |
| `CONTACT_RATE_LIMIT` / `CONTACT_RATE_WINDOW_SECONDS` | Per-process limiter (default 5 per 600s). |
| `NEXT_PUBLIC_ANALYTICS_ENABLED` | Must be `true` for any event to be sent. |
| `ANALYTICS_INGEST_URL` / `ANALYTICS_INGEST_TOKEN` | Server-side event collector. |
| `NEXT_PUBLIC_CONTACT_PREFILL_NAME` | Optional demo convenience; leave empty for a public form. |
| `NEXT_PUBLIC_SITE_URL` | Canonical origin for metadata and the sitemap. https on Vercel; defaults there to the project's production domain. |

---

## The visual system

The background is a layered scene, not a decorative gradient.

- **Bilateral ribbons.** Two dominant ribbons stand for the left and right limb.
  A `uSync` uniform drives them apart and back together, keeping a small
  residual asymmetry — real gait is never perfectly symmetric.
- **Travelling light.** Pulses move *along* each tube's length in the fragment
  shader (`vUv.x`), with a comet tail, a fine sampling comb, and a periodic
  bilateral synchronisation flash. The geometry does not slide back and forth.
- **Scene modes.** `MODE_STATE` in `components/three/KineticScene.tsx` maps each
  section to targets the ribbons damp toward: fragmented for the problem
  section, sequential station activation for the pipeline, and a morph to a
  closed orbit for the recovery score (via a second `aOrbit` vertex attribute
  blended in the vertex shader).
- **Two authored themes.** `DARK_PALETTES` and `LIGHT_PALETTES` are written
  separately. Daylight is not an inversion: it uses deeper hues, normal instead
  of additive blending, reduced bloom and softer shadows.

### Performance and fallback

Dynamic import (never blocks first paint) · device-tier geometry and particle
reduction · bloom only on the high tier · `frameloop="never"` when the tab is
hidden · WebGL2 capability probe · `prefers-reduced-motion` and `saveData`
respected · error boundary plus `webglcontextlost` handling that tears the scene
down to the CSS layer.

The CSS aurora in `.scene-fallback` is not a placeholder — it is the complete
experience for reduced-motion and no-WebGL visitors, and keeps the paired-strand
metaphor.

---

## Accessibility

Semantic landmarks and a single `<h1>` per page · skip link · visible focus
rings throughout · `<dialog>` for the mobile drawer and modal (focus trapping,
Escape, focus restored to the trigger) · labelled fields with `role="alert"`
inline errors · text descriptions on every chart · accessible data tables
behind a toggle in the dashboard · ~44px touch targets · no colour-only status
(confidence and coverage carry text) · verified 4.5:1+ text contrast in both
themes · no horizontal overflow from 360px up.

---

## Project layout

```
app/          Next.js routes (deployed to Vercel)
components/   UI, workspace, hardware lab
lib/          API client, config (config.ts browser / config.server.ts server-only)
backend/      FastAPI API, WebSockets, DB models, migrations, inference (Python host, not Vercel)
ml/           training code, reports, versioned model bundles (training env only)
firmware/     ESP32 firmware
docs/         architecture, protocol, validation status, deployment
scripts/      deployment checks
```

The frontend stays at the repository root rather than in `frontend/`: moving
it would change the Vercel root directory and every import path for no
functional gain. `.vercelignore` keeps `backend/`, `ml/` and `firmware/` out
of the Vercel upload.

## Known limitations

- No physical hardware validation yet; no clinical validation.
- Live processors are held in the memory of the API instance receiving a
  device's stream. The free Vercel deployment runs several instances: dashboards
  get live messages through a PostgreSQL relay and validation from a snapshot.
  Every WebSocket is cut at 300 s, and long sessions may resume on another
  instance with a fresh calibration (VERCEL_DEPLOYMENT.md). A host with
  long-lived connections removes this limit.
- Google and Facebook sign-in need provider credentials before they appear as
  available.
- Demo dashboard values are invented and labelled as such throughout.
- The rate limiter is per-process; use a shared limiter in production.
- A named data controller, retention periods and user-rights processes must be
  established before collecting any real personal or health data.
