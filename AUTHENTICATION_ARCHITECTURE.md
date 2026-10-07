# RehabSense authentication architecture

RehabSense has **one** session system. Email/password, Google and Facebook all
end in the same thing: the `rs_session` and `rs_refresh` HttpOnly cookies, issued by
`issue_tokens()` in [backend/app/api/auth.py](backend/app/api/auth.py) and read by
`get_current_user()` in [backend/app/api/deps.py](backend/app/api/deps.py).
There is no Google session, no Facebook session, and no token in JavaScript or `localStorage`.

```
Browser ──HTTPS──▶ rehabsense-platform.vercel.app (Next.js)
                     └─ /api/*  ──rewrite (proxy)──▶ rehabsense-api.vercel.app (FastAPI) ──▶ Neon PostgreSQL
                                                         │
                       Google / Facebook  ◀──server-to-server: code exchange, ID-token / token checks
```

## Why every auth URL is on the website origin

The browser only ever talks to `https://rehabsense-platform.vercel.app`. Next.js
rewrites `/api/*` to the FastAPI service, so every cookie the API sets is
first-party to the website. `vercel.app` is on the Public Suffix List, so a
cookie set by `rehabsense-api.vercel.app` could never be sent to
`rehabsense-platform.vercel.app`. For that reason the OAuth callbacks are:

| Provider | Redirect URI registered with the provider (exact) | Handled by |
|---|---|---|
| Google | `https://rehabsense-platform.vercel.app/api/auth/google/callback` | `GET /api/auth/{provider}/callback` in [backend/app/api/oauth.py](backend/app/api/oauth.py), reached via the proxy |
| Facebook | `https://rehabsense-platform.vercel.app/api/auth/facebook/callback` | same route |

A callback on `https://rehabsense-api.vercel.app/...` would set the session cookie on the
wrong host, so the dashboard would never see it. The API refuses that configuration in
production (`Settings.oauth_problem()`: "redirect URI must be on the website origin
listed in CORS_ORIGINS").

## Session (shared by every method)

| Item | Value |
|---|---|
| Access cookie | `rs_session`: HS256 JWT (`typ=access`, `sub`, `role`, `ver`), 12 h, `HttpOnly; Secure; SameSite=Lax; Path=/` |
| Refresh cookie | `rs_refresh`: 14 days, `HttpOnly; Secure; SameSite=Lax; Path=/api/auth/refresh` |
| Validation | Signature + expiry + `ver == users.token_version` + `is_active` on every request |
| Logout | `POST /api/auth/logout` bumps `token_version`: every token everywhere stops working; cookies cleared |
| CSRF | `SameSite=Lax` + an `Origin` allow-list check on cookie-authenticated writes ([deps.py](backend/app/api/deps.py)) |
| CORS | Exactly `https://rehabsense-platform.vercel.app`; `*` is refused at startup |

## Email and password (unchanged)

`POST /api/auth/signup` and `POST /api/auth/login` hash or verify with Argon2id,
apply the failed-login lockout (8 failures, then 15 min), then call
`issue_tokens()` and `set_auth_cookies()`. An account created through Google or
Facebook has `password_hash = NULL`. Password sign-in to it is refused with the same
"Email or password is incorrect." as a wrong password, so the endpoint reveals
nothing about it.

## Google (OpenID Connect, authorization-code flow)

1. **Start.** The button navigates the page (no fetch) to
   `/api/auth/google/start?next=…&role=…`. The API creates a random `state`
   (32 bytes), `nonce` (32 bytes) and PKCE `code_verifier` (64 bytes). It stores
   them in a short-lived signed cookie `rs_oauth_google` (HS256 with the API
   secret, 10 min, `HttpOnly; Secure; SameSite=Lax; Path=/api/auth/google`). It
   then answers `303` to `https://accounts.google.com/o/oauth2/v2/auth` with:
   - `scope=openid email profile`
   - `code_challenge` (S256)
   - `prompt=select_account`, so the account chooser always shows.
2. **Google.** The person picks an account on Google's own page and Google
   redirects to the callback with `code` and `state`, or with
   `error=access_denied` on cancel.
3. **Callback.** The checks run in this order, and any failure stops the
   attempt:
   1. Provider configured.
   2. State cookie present, signature valid, not expired, same provider.
   3. `state` equal to the cookie's (constant-time comparison).
   4. **State never used before.** Its SHA-256 is inserted into
      `oauth_state_uses`; a duplicate is a replay, on any instance.
   5. A provider `error` is turned into `cancelled` or `provider_error`.
   6. The code is exchanged **server to server** at
      `https://oauth2.googleapis.com/token`, with the client secret and the PKCE
      verifier.
   7. The **ID token is verified**:
      - RS256 signature against Google's published keys (`/oauth2/v3/certs`).
      - `iss` is `https://accounts.google.com` or `accounts.google.com`.
      - `aud` equals our client ID, and `azp` too when present.
      - `exp` and `iat`, with 60 s of leeway.
      - `nonce` equals the one we generated.
   8. The identity is the ID token's `sub`. Email and `email_verified` come from
      the same verified token.
   9. The account-linking policy below runs.
   10. `issue_tokens()` and `set_auth_cookies()` run (the standard session), the
       state cookie is cleared, and the response is a `303` to `next` or the
       role's home.

## Facebook (OAuth 2.0 authorization-code flow)

1. **Start.** `/api/auth/facebook/start` builds `state` and the signed cookie
   `rs_oauth_facebook` the same way. It answers `303` to
   `https://www.facebook.com/v25.0/dialog/oauth` with
   `scope=public_profile,email`. These are the only two permissions Facebook
   grants without App Review.
2. **Callback.** Steps 1–5 are the same as Google. Then:
   - The code is exchanged at `graph.facebook.com/v25.0/oauth/access_token`
     with the app secret.
   - The token is **inspected with `debug_token`** using the app access token.
     It must be `is_valid`, and its `app_id` must equal our app, so a token
     issued to another app is refused.
   - The profile is read from `/me?fields=id,name,email` with an
     `appsecret_proof` (HMAC-SHA256 of the token with the app secret).
   - `/me.id` must equal the inspected token's `user_id`.
   - The identity is the **app-scoped Facebook user id**, never the name or the
     email.
   - Facebook does not say whether an email is verified, so it is recorded as
     unverified and **never** used to match an account.
3. The access token is then discarded: it is not stored, not logged and never
   sent to the browser.

## Identity model

`users` is the person's RehabSense account (role, profile, records). Sign-in
identities are separate:

| Table / column | Purpose |
|---|---|
| `users.password_hash` (nullable) | The password method; email is its login identifier. NULL means the account has no password. |
| `user_identities` | One external identity: `id, user_id → users.id (ON DELETE CASCADE), provider, provider_subject, provider_email, provider_email_verified, last_used_at, created_at, updated_at`. |
| `UNIQUE (provider, provider_subject)` | The identity key. A Google `sub` or Facebook id belongs to at most one account. |
| `UNIQUE (user_id, provider)` | At most one Google and one Facebook account per user. |
| `CHECK provider IN ('google','facebook','phone')` | `phone` is reserved; SMS is not configured. |
| `oauth_state_uses (state_hash UNIQUE, provider, used_at)` | Single-use guarantee for OAuth states across instances. Rows older than a day are pruned. |

Migration: [backend/migrations/versions/cf12f69e0b50_social_sign_in_identities_single_use_.py](backend/migrations/versions/cf12f69e0b50_social_sign_in_identities_single_use_.py).
It also adds the audit actions `OAUTH_LOGIN`, `OAUTH_LOGIN_REFUSED`, `IDENTITY_LINKED`,
`IDENTITY_UNLINKED` and `USER_DELETED` to the PostgreSQL `auditaction` type.

## Account-linking policy

Implemented in [backend/app/services/identity_service.py](backend/app/services/identity_service.py).

| Case | What happens |
|---|---|
| 1. Identity unknown, no account uses the email | A new account is created: name from the provider, role from the sign-up page's "I am a…" (self-assignable roles only, default Patient), no password. Google additionally requires `email_verified=true`; Facebook must share an email at all. |
| 2. Identity known | Sign in to the account it belongs to, even if the provider email has changed. |
| 3. Identity unknown, but an account already uses the email | **Refused with `account_exists`.** Nothing is merged and no second account is created. The login page explains why, the person signs in to that account the way they did before, and the browser then goes straight back to Google or Facebook with `intent=link`. |
| Link (`intent=link`, from Settings or after case 3) | Attaches the identity to the account that is signed in **at the callback** (the session must still be the same user that started). An identity already on another account is never moved (`identity_in_use`). A second Google account on the same user is refused (`provider_already_linked`). |
| Disconnect | `DELETE /api/auth/identities/{provider}`. Refused if it would leave the account with no way to sign in (`LAST_SIGN_IN_METHOD`). |
| Delete account | `DELETE /api/me` (type DELETE, plus the password if the account has one). Deletes the user row; identities cascade. Clinicians with active assignments and admins are refused. |

**Why there is no auto-merge by email:** RehabSense does not verify the email of
password accounts, because no email provider is configured. Auto-merging a Google login
into an existing account with the same email would let anyone who pre-registered that
address with a password share the Google user's account (pre-account hijacking).
Matching therefore uses `(provider, provider_subject)` only. A shared email is a reason
to ask the person to prove ownership of both sides, never proof by itself.

**Known limitation:** because Facebook emails are unverified, someone could create a
Facebook-based account using an email they do not own. That address is then taken in
RehabSense: its owner cannot sign up with it until the squatting account is deleted. No
takeover is possible, because nothing is ever merged by email.

## Endpoints

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /api/auth/signup`, `POST /api/auth/login` | none | Email/password; set the session cookies |
| `GET /api/auth/me` | session | The signed-in user (401 when signed out) |
| `POST /api/auth/logout` | session | Invalidate all sessions (`token_version`++), clear cookies |
| `GET /api/auth/providers` | none | `{password, google, facebook, phone}.enabled`. No secrets, no DB access; also the sign-in page's API probe |
| `GET /api/auth/{google,facebook}/start` | none (`intent=link` needs a session) | Set the state cookie; 303 to the provider |
| `GET /api/auth/{google,facebook}/callback` | state cookie | Verify, link or create, start the session; 303 to the workspace |
| `GET /api/auth/identities` | session | The user's sign-in methods (no subject ids, no tokens) |
| `DELETE /api/auth/identities/{provider}` | session | Disconnect a provider |
| `DELETE /api/me` | session (+ password) | Delete the account |

Failures redirect to `/login?oauth_error=<code>&provider=<p>`, or to
`/workspace/settings?…` for link attempts. The codes are `cancelled`,
`not_configured`, `invalid_state`, `provider_error`, `provider_unreachable`,
`email_unverified`, `email_required`, `account_exists`, `account_disabled`,
`identity_in_use`, `provider_already_linked` and `link_session_expired`.
[lib/auth.ts](lib/auth.ts) (`oauthErrorMessage`) turns each into a plain sentence. No
failure creates a session.

## Security boundaries

| Concern | How it is handled |
|---|---|
| Client secret / app secret | Read only by the API from its environment (`GOOGLE_CLIENT_SECRET`, `FACEBOOK_APP_SECRET`, stored as Vercel *Sensitive*). Never in the website project, never `NEXT_PUBLIC_*`, never in git. |
| Provider tokens | Used once, server-side, to read the identity; never stored, logged or returned. |
| Logs | `httpx`/`httpcore` request logging is silenced, because those URLs carry codes, tokens and the Facebook app access token. Refusals log a reason code only. A test (`test_no_secret_code_or_token_reaches_the_logs`) checks this. |
| Login CSRF / injected callbacks | `state` bound to an HttpOnly cookie on the browser that started the attempt, plus a single-use table. |
| Replay | Second use of a state → `invalid_state` before any code exchange. Google and Facebook codes are single-use too. |
| Token substitution | Google: `aud`/`azp`/`iss`/signature/nonce. Facebook: `debug_token` app check plus `appsecret_proof`. |
| Open redirect | `next` must be a same-site path (`/…`, not `//`, no `\`, not `/api/`); anything else falls back to the role's home. |
| Role escalation | A new social account gets only a self-assignable role; `ADMIN` is ignored and becomes Patient. |
| Referrer leakage | Callback redirects send `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. |

## Environment variables

| Variable | Project | Type | Notes |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | rehabsense-api | plain | `….apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | rehabsense-api | **Sensitive** | never `NEXT_PUBLIC_` |
| `GOOGLE_REDIRECT_URI` | rehabsense-api | plain | `https://rehabsense-platform.vercel.app/api/auth/google/callback` (default if unset: first CORS origin + path) |
| `FACEBOOK_APP_ID` | rehabsense-api | plain | digits |
| `FACEBOOK_APP_SECRET` | rehabsense-api | **Sensitive** | never `NEXT_PUBLIC_` |
| `FACEBOOK_REDIRECT_URI` | rehabsense-api | plain | `https://rehabsense-platform.vercel.app/api/auth/facebook/callback` |
| `FACEBOOK_GRAPH_VERSION` | rehabsense-api | plain, optional | default `v25.0` |
| `OAUTH_STATE_MINUTES` | rehabsense-api | plain, optional | default 10 |

The website project needs no new variable: the buttons are links to its own
`/api/*`. [scripts/set_oauth_env.sh](scripts/set_oauth_env.sh) stores these values in
Vercel with hidden input. A provider is offered only when its ID **and** secret are set.
A half-configured provider is reported in the startup log (variable names only) and
shown as "Not configured" on the sign-in page. It never breaks email sign-in.

## Tests

[backend/tests/test_oauth.py](backend/tests/test_oauth.py) has 53 tests, run on SQLite
and PostgreSQL 16. It drives the real routes, the state handling, the ID-token
verification and the linking policy. Only the provider's network side is stubbed (in the
test file). Covered:

- new and returning users for both providers;
- cancellation; missing, forged, expired and replayed state;
- the wrong audience, issuer, nonce, expiry, azp and signing key;
- a Facebook token issued to another app, and a mismatched profile;
- an unverified email, a missing email, and the same-email account (no merge);
- linking, an identity already on another account, and disconnecting the last method;
- open-redirect attempts, role escalation and secrets in logs;
- account deletion.
