# Authentication production report

**Date:** 2026-10-07

**Live site:** <https://rehabsense-platform.vercel.app>. The API is
<https://rehabsense-api.vercel.app>.

**State of this report:**

- The new authentication code is implemented and tested locally.
- It is **not deployed yet**: deploying needs a Vercel CLI login by the account owner.
- Google and Facebook need provider apps created by the account owner, as described in
  [GOOGLE_OAUTH_SETUP.md](GOOGLE_OAUTH_SETUP.md) and
  [FACEBOOK_OAUTH_SETUP.md](FACEBOOK_OAUTH_SETUP.md).
- This file is updated after the deployment and the live tests.

## Result table

Values are limited to PASS, FAIL, NOT CONFIGURED and NOT TESTED.

- "Implementation" means the code exists and its automated tests pass: 288 backend tests
  on SQLite and PostgreSQL 16, plus 29 + 9 + 13 real-browser checks against a local
  production build.
- "Live Browser Test" means a real browser on the live website, running the new code.

| Feature | Implementation | Live Browser Test | Status |
|---|---|---|---|
| Email signup | PASS | NOT TESTED | NOT TESTED |
| Email login | PASS | NOT TESTED | NOT TESTED |
| Email logout | PASS | NOT TESTED | NOT TESTED |
| Google OAuth | PASS | NOT TESTED | NOT CONFIGURED |
| Google returning login | PASS | NOT TESTED | NOT CONFIGURED |
| Facebook OAuth | PASS | NOT TESTED | NOT CONFIGURED |
| Facebook returning login | PASS | NOT TESTED | NOT CONFIGURED |
| Session persistence | PASS | NOT TESTED | NOT TESTED |
| Protected routes | PASS | NOT TESTED | NOT TESTED |
| User isolation | PASS | NOT TESTED | NOT TESTED |
| Phone OTP | NOT CONFIGURED | NOT TESTED | NOT CONFIGURED |

Before this change, email signup, login, logout, protected routes and isolation all
passed on the live site: 13/13 browser checks and 28 API checks in the last session.
Email signup, login and logout also passed in today's performance runs on the current
deployment. They are listed as NOT TESTED above only because the new version is not live
yet.

## What was verified locally

All of this ran against the real code paths. The only stubs are Google's token endpoint
and Facebook's Graph API, inside `tests/test_oauth.py`.

**Backend tests (53 OAuth, 288 total, on SQLite and PostgreSQL):**

- new and returning users for both providers; the standard session cookies;
  `/api/auth/me` after OAuth;
- Google ID-token checks: signature, `aud`, `iss`, `nonce`, `exp`, `azp`;
- Facebook token belonging to another app; mismatched profile;
- missing, forged, expired and replayed state; cancellation;
- unverified Google email; missing Facebook email;
- same-email account refused rather than merged; linking only while signed in;
  identities never moved between accounts; disconnecting the last method refused;
- open-redirect attempts; role escalation; secrets and codes absent from logs;
- account deletion.

**Real browser against a local production build** (Next.js plus FastAPI):

- "Continue with Google" reaches **accounts.google.com** and "Continue with Facebook"
  reaches **facebook.com**. Placeholder credentials were used, so the providers answered
  with their own "invalid client" pages, which proves the redirect chain.
- The state cookie is `HttpOnly`, `SameSite=Lax` and scoped to `/api/auth/<provider>`.
- Cancellation returns to `/login` with a message and no session.
- Forged and replayed states are refused.
- The account-exists flow signs in first, then opens Google with `intent=link`.
- Settings → Sign-in methods works, and so does account deletion.
- With no credentials, the buttons say **Not configured**, clicking them explains why,
  and nothing redirects or signs in.
- The previous 13-check email suite still passes.

**Migration:** upgrade, downgrade and re-upgrade on PostgreSQL with existing users and
audit rows. Users are intact, the enum values were added, the CHECK constraint is
enforced and `alembic check` is clean.

## Remaining before any "production ready" claim

1. Owner: `npx vercel@latest login`. Then I run the Neon migration and deploy the API
   and website.
2. Owner: create the Google OAuth client and the Meta app, then run
   `bash scripts/set_oauth_env.sh`.
3. Live tests 1–13 from the task, on the live site. Google and Facebook account
   selection must be done by a person with those accounts.
4. Meta: switch the app to **Live** so people without a role on the app can use
   Facebook sign-in.

## Verdict

**NOT PRODUCTION READY.** Google and Facebook are NOT CONFIGURED, and the new
authentication code is not deployed or live-tested yet.
