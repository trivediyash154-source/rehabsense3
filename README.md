# RehabSense

A research prototype interface for a wearable lower-limb rehabilitation sensing
concept, initially focused on ACL recovery. The site communicates the idea —
bilateral movement capture, time-synchronised comparison, and explainable
recovery indicators — without claiming capabilities the system does not have.

**RehabSense is not a medical device.** It is not certified, cleared or
clinically validated. Every number shown in this interface is invented to
demonstrate a layout. Nothing here diagnoses, treats or prescribes.

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
# 1. backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 2. frontend
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev

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

### Accounts

`/signup` and `/login` create and use real accounts on the backend. Passwords
are stored only as Argon2id hashes; the session is an **HttpOnly** cookie that
no page script can read, so an injected script has no credential to steal.
`/workspace` is guarded in `middleware.ts` before the page renders, and every
API response is authorised server-side against the real session — a patient
cannot reach another patient's records by editing a URL, and an unauthorised
record answers 404 rather than confirming it exists.

Social sign-in, password-reset email and SMS verification are **not**
configured; those screens say so instead of implying a message was sent.

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

Node 20+ is expected. No environment variables are required to run the site;
every integration is off by default and says so in the UI.

---

## What is real and what is not

| Area | Status |
|---|---|
| Landing page, navigation, theming | Fully implemented |
| Sign in / sign up / reset / verify screens | Fully implemented **UI**; authentication is **not connected** |
| Contact form | Fully implemented, validated client- and server-side; **delivery is off** until configured |
| Demo dashboard | Fully implemented against **illustrative, invented data** |
| Product event logging | Implemented with a strict allowlist; **collection is off** by default |
| Sensor hardware, FastAPI service, PostgreSQL, analytics pipeline | **Not part of this repository** |

### Authentication — demo mode

`/api/auth` answers every request with `503 AUTH_NOT_CONFIGURED` and never reads
the request body. The client (`lib/auth.ts`) sends only the action name, so an
email, password, phone number or verification code entered into the form **never
leaves the browser**. The screens show a persistent "Demo mode" banner, and the
resend cooldown only starts if a provider actually accepts a delivery request —
so the timer can never imply a message that was not sent.

To connect real authentication:

1. Implement `AuthAdapter` in `lib/server/auth-adapter.ts` (or delegate to a
   reviewed library) and return it from `getAuthAdapter()`.
2. Put provider secrets in **server-only** environment variables. Never prefix a
   secret with `NEXT_PUBLIC_` — that inlines it into the client bundle.
3. Set `AUTH_ADAPTER_ENABLED=true`.
4. Change `lib/auth.ts` to submit credentials over HTTPS to your server route.
   Until step 1 exists, this step would transmit secrets to a route that
   discards them, so it is deliberately left undone.

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

See `.env.example`. All are optional.

| Variable | Purpose |
|---|---|
| `CONTACT_DELIVERY_URL` | HTTPS endpoint receiving contact submissions. Enables the form. |
| `CONTACT_DELIVERY_TOKEN` | Optional bearer token for that endpoint. |
| `CONTACT_RATE_LIMIT` / `CONTACT_RATE_WINDOW_SECONDS` | Per-process limiter (default 5 per 600s). |
| `NEXT_PUBLIC_ANALYTICS_ENABLED` | Must be `true` for any event to be sent. |
| `ANALYTICS_INGEST_URL` / `ANALYTICS_INGEST_TOKEN` | Server-side event collector. |
| `AUTH_ADAPTER_ENABLED` | Reserved. Does **not** enable auth on its own. |
| `NEXT_PUBLIC_CONTACT_PREFILL_NAME` | Optional demo convenience; leave empty for a public form. |
| `NEXT_PUBLIC_SITE_URL` | Canonical origin for metadata and the sitemap. |

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
app/          routes, API routes, global stylesheet
components/   auth, brand, charts, contact, dashboard, hero, navigation, sections, three, ui
lib/          theme, analytics allowlist, validation, auth boundary, audit log, rate limit
lib/server/   server-only auth adapter seam
```

## Known limitations

- No authentication, no accounts, no sessions.
- No database, no patient records, no sensor ingestion.
- Dashboard values are invented and labelled as such throughout.
- The rate limiter is per-process; use a shared limiter in production.
- A named data controller, retention periods and user-rights processes must be
  established before collecting any real personal or health data.
