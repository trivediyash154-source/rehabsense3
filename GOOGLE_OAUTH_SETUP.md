# Google sign-in setup (free, no card)

RehabSense's "Continue with Google" stays **Not configured** until these steps are done.
Nothing here needs a billing account or a payment card. You need a Google account and
about 10 minutes.

## Values you will use (copy exactly)

| Field | Value |
|---|---|
| Application type | **Web application** |
| Authorized JavaScript origin | `https://rehabsense-platform.vercel.app` |
| Authorized redirect URI | `https://rehabsense-platform.vercel.app/api/auth/google/callback` |
| Privacy policy | `https://rehabsense-platform.vercel.app/privacy` |
| Authorized domain | `rehabsense-platform.vercel.app` |
| Scopes | `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (non-sensitive: no Google review) |

The redirect URI is on the **website** (`rehabsense-platform`), not on
`rehabsense-api`. The website proxies `/api/*` to the API, so the sign-in cookie stays on
the website (see [AUTHENTICATION_ARCHITECTURE.md](AUTHENTICATION_ARCHITECTURE.md)). One
character of difference and Google shows `redirect_uri_mismatch`.

## Steps

1. Open <https://console.cloud.google.com/> and sign in.
   - If asked, accept the terms.
   - Ignore any "free trial" or billing banner. It is not needed for sign-in.
2. Click the project picker at the top and choose **New project**. Name it
   `RehabSense` and click **Create**, then select it.
3. Open the menu and go to **APIs & Services → OAuth consent screen**. This opens
   **Google Auth Platform**. Click **Get started**:
   1. App name `RehabSense`, User support email: your Gmail. Click **Next**.
   2. Audience: **External**. Click **Next**.
   3. Contact information: your Gmail. Click **Next**.
   4. Tick the agreement, click **Continue**, then **Create**.
4. **Branding** (left menu):
   - App home page: `https://rehabsense-platform.vercel.app`
   - App privacy policy link: `https://rehabsense-platform.vercel.app/privacy`
   - Authorized domains: add `rehabsense-platform.vercel.app`
   - Click **Save**.
   - **Do not upload a logo.** A logo makes Google require brand verification, which
     takes days.
5. **Clients** (left menu) → **Create client**:
   1. Application type: **Web application**. Name: `RehabSense web`.
   2. Authorized JavaScript origins → **Add URI**:
      `https://rehabsense-platform.vercel.app`
   3. Authorized redirect URIs → **Add URI**:
      `https://rehabsense-platform.vercel.app/api/auth/google/callback`
   4. Click **Create**.
   5. **Copy the Client ID and the Client secret now.** Google shows the secret only
      once. If you lose it, open the client and use **Add secret** (rotation).
6. **Audience** (left menu): Publishing status shows **Testing**. Click
   **Publish app**, then **Confirm**. It becomes **In production**.
   - With only the basic scopes, publishing needs no verification and users see no
     "unverified app" warning.
   - While the app is in Testing, only the test users you list there can sign in.
7. Put the two values into Vercel (they are typed in your terminal, never shown or
   saved anywhere else):

   ```bash
   npx vercel@latest login          # once
   bash scripts/set_oauth_env.sh    # paste Client ID, then the secret (hidden)
   ```

   This stores `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (Sensitive) and
   `GOOGLE_REDIRECT_URI` on the **rehabsense-api** project, **Production**
   environment. The API then needs a redeploy.

## Check it

- `https://rehabsense-platform.vercel.app/api/auth/providers` shows `"google":{"enabled":true}`.
- On `/login`, **Continue with Google** opens Google's account chooser. Pick an
  account and you land in the workspace, signed in.
- In **Settings → Sign-in methods**, Google shows "Connected as …".

## Local development

Create a **separate** Web client (do not reuse the production one) with:

- Origin: `http://localhost:3000`
- Redirect URI: `http://localhost:3000/api/auth/google/callback`

Put its values in `backend/.env`, which git ignores. Plain `http` is accepted only for
`localhost`, and only when `ENVIRONMENT` is not `production`.

## Troubleshooting

| What you see | Cause |
|---|---|
| `Error 400: redirect_uri_mismatch` | The redirect URI in the client differs from `https://rehabsense-platform.vercel.app/api/auth/google/callback` (check the trailing slash, `http` vs `https`, and the host). |
| `Error 401: invalid_client` | The wrong Client ID in Vercel, or the API was not redeployed after setting it. |
| `Access blocked: … has not completed the Google verification process` | Publishing status is still **Testing** and this Google account is not a test user. Publish the app (step 6). |
| Back on `/login` with "That Google sign-in expired or was already used" | More than 10 minutes on Google's page, or the Back button replayed an old callback. Try again. |
| "A RehabSense account already uses this Google email address" | Sign in with your password once on that screen; Google is then connected to that account (no merge without proof). |
