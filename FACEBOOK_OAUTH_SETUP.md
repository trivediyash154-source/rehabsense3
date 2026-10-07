# Facebook sign-in setup (free, no card)

RehabSense's "Continue with Facebook" stays **Not configured** until these steps are
done. You need a Facebook account. Meta may ask you to confirm your phone number or
email when you first register as a developer. It does not need a payment card for
Facebook Login.

## Values you will use (copy exactly)

| Field | Value |
|---|---|
| Valid OAuth Redirect URI | `https://rehabsense-platform.vercel.app/api/auth/facebook/callback` |
| App domain | `rehabsense-platform.vercel.app` |
| Privacy Policy URL | `https://rehabsense-platform.vercel.app/privacy` |
| User data deletion (instructions URL) | `https://rehabsense-platform.vercel.app/data-deletion` |
| Permissions | `public_profile`, `email` only. Meta grants these without App Review. |

The redirect URI is on the **website** (`rehabsense-platform`), not `rehabsense-api`,
for the same cookie reason as Google (see
[AUTHENTICATION_ARCHITECTURE.md](AUTHENTICATION_ARCHITECTURE.md)).

## Steps

1. Open <https://developers.facebook.com/> and log in with Facebook. Click
   **Get started** (or **My Apps**) and finish developer registration if asked: accept
   the terms and confirm your phone or email.
2. Go to **My Apps → Create app**:
   1. App name `RehabSense`, plus your contact email. Click **Next**.
   2. Use case: **Authenticate and request data from users with Facebook Login**.
      Click **Next**.
   3. Business: choose **I don't want to connect a business portfolio yet**. Click
      **Next**, then **Create app**. Meta may ask for your Facebook password.
3. **Use cases → Authenticate and request data from users with Facebook Login →
   Customize**:
   - Under **Permissions**, make sure **email** is added (click **Add** if needed).
     `public_profile` is always included.
   - Under **Settings** (Facebook Login settings), set:
     - Client OAuth login: **Yes**
     - Web OAuth login: **Yes**
     - Enforce HTTPS: **Yes**
     - Use Strict Mode for redirect URIs: **Yes**
     - **Valid OAuth Redirect URIs:**
       `https://rehabsense-platform.vercel.app/api/auth/facebook/callback`
   - Click **Save changes**.
4. **App settings → Basic**:
   - App domains: `rehabsense-platform.vercel.app`
   - Privacy Policy URL: `https://rehabsense-platform.vercel.app/privacy`
   - User data deletion: choose **Data deletion instructions URL** and enter
     `https://rehabsense-platform.vercel.app/data-deletion`
   - Category: e.g. **Health & fitness**
   - App icon (1024 × 1024): upload `public/brand/rehabsense-app-icon-1024.png` from
     this repository (after the next deploy it is also at
     `https://rehabsense-platform.vercel.app/brand/rehabsense-app-icon-1024.png`).
   - Click **Save changes**.
   - Copy the **App ID**, then click **Show** next to **App secret** (Meta asks for
     your password) and copy it.
5. Put the two values into Vercel (typed in your terminal, never shown or saved
   anywhere else):

   ```bash
   npx vercel@latest login          # once
   bash scripts/set_oauth_env.sh    # press Enter to skip Google, then paste App ID and App secret
   ```

   This stores `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` (Sensitive) and
   `FACEBOOK_REDIRECT_URI` on **rehabsense-api**, **Production**. The API then needs a
   redeploy.
6. **Development mode vs Live.** A new Meta app is in **Development** mode:
   - Only people with a role on the app can log in: you (the admin), and anyone you add
     under **App roles → Roles** as developer or tester.
   - Everyone else gets a "not available" message from Facebook. RehabSense shows
     that as a cancelled or failed Facebook sign-in, never as a success.
   - To let **anyone** sign in, switch the app to **Live** (the **Publish** button or the
     App Mode toggle). Meta lists any missing items first, typically the privacy policy
     URL, the data deletion URL, the category and the icon from step 4.
   - Do this **after** the deploy that publishes `/privacy` and `/data-deletion`,
     because Meta may open those links.
   - `email` and `public_profile` need no App Review and no business verification.

## Check it

- `https://rehabsense-platform.vercel.app/api/auth/providers` shows `"facebook":{"enabled":true}`.
- On `/login`, **Continue with Facebook** opens Facebook's own dialog. Continue and you
  land in the workspace, signed in.
- **Settings → Sign-in methods** shows Facebook as connected.
- Cancel on Facebook's dialog (**Not now** or **Cancel**) and you return to `/login`
  with "Facebook sign-in was cancelled". Nobody is signed in.

## What RehabSense receives and keeps

- **Receives:** the app-scoped Facebook user ID (the identity key), name and email.
- **Keeps:** the ID, the email and the last-used time.
- **Never keeps:** the access token, which is used once, server-side, to verify the
  login.
- Facebook does not say whether the email is verified, so RehabSense never uses it to
  join accounts.
- Users can disconnect Facebook or delete their account in **Settings**. Those steps are
  on the data deletion page given to Meta.

## Troubleshooting

| What you see | Cause |
|---|---|
| "URL blocked: This redirect failed because the redirect URI is not whitelisted" | The Valid OAuth Redirect URI does not exactly equal `https://rehabsense-platform.vercel.app/api/auth/facebook/callback`. |
| "App not active" / "This app is in development mode" | The person has no role on the app. Add them as a tester or switch the app to Live. |
| "Facebook did not share an email address" | The person declined email, or their Facebook account has no email. **Try Facebook again** asks once more. |
| "Invalid App ID" | The wrong `FACEBOOK_APP_ID` in Vercel, or the API was not redeployed. |
