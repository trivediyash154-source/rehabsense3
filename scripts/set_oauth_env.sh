#!/usr/bin/env bash
# Store Google / Facebook sign-in credentials in the Vercel API project
# (rehabsense-api, Production) -- typed here, never printed, never written to
# a file, never committed, never a NEXT_PUBLIC_ variable.
#
#   npx vercel@latest login          # once, in this terminal
#   bash scripts/set_oauth_env.sh    # paste the values when asked
#
# VERCEL_GLOBAL_CONFIG=<dir> reuses a login stored in another Vercel CLI
# config directory (the -Q flag) instead of the default one.
#
# Press Enter at a prompt to skip that provider. Run it again any time to
# replace a value. A redeploy of the API is needed afterwards (env changes
# apply to new deployments only).
set -euo pipefail

ORG_ID=team_2sBcwmlki2DTOyMtbjFvI4pi
API_PROJECT_ID=prj_ylHGtJbAT868yeCW1LtrslhN0Wz6
SITE=https://rehabsense-platform.vercel.app
VERCEL=(npx --yes vercel@latest)
[ -n "${VERCEL_BIN:-}" ] && VERCEL=("$VERCEL_BIN")
# Reuse a Vercel CLI login kept in another config directory (vercel -Q).
[ -n "${VERCEL_GLOBAL_CONFIG:-}" ] && VERCEL+=(-Q "$VERCEL_GLOBAL_CONFIG")
export VERCEL_TELEMETRY_DISABLED=1

export VERCEL_ORG_ID=$ORG_ID VERCEL_PROJECT_ID=$API_PROJECT_ID
# Run from an empty directory so no .vercel link is created in the repository.
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

if ! "${VERCEL[@]}" whoami >/dev/null 2>&1; then
  echo "Not signed in to Vercel. Run:  npx vercel@latest login   then run this script again."
  exit 1
fi
echo "Signed in to Vercel as: $("${VERCEL[@]}" whoami 2>/dev/null)"
echo "Values go to project rehabsense-api, environment Production."
echo

add() { # NAME VALUE [--sensitive]   (secrets: --sensitive; ids and URLs: plain config)
  if printf '%s' "$2" | "${VERCEL[@]}" env add "$1" production --project "$API_PROJECT_ID" \
      "${3:---no-sensitive}" --force --yes >/dev/null 2>&1; then
    echo "  saved $1"
  else
    echo "  FAILED to save $1 (nothing printed for safety). Check 'npx vercel@latest whoami'."
    exit 1
  fi
}

echo "Google  (Google Cloud Console > Google Auth Platform > Clients > your Web client)"
read -r -p "  Client ID (ends .apps.googleusercontent.com, Enter to skip): " GOOGLE_CLIENT_ID
GOOGLE_CLIENT_ID=$(printf '%s' "$GOOGLE_CLIENT_ID" | tr -d '[:space:]')
if [ -n "$GOOGLE_CLIENT_ID" ]; then
  case "$GOOGLE_CLIENT_ID" in
    *.apps.googleusercontent.com) ;;
    *) echo "  That is not a Google OAuth client ID (it must end in .apps.googleusercontent.com)."; exit 1 ;;
  esac
  read -r -s -p "  Client secret (typing is hidden): " GOOGLE_CLIENT_SECRET; echo
  GOOGLE_CLIENT_SECRET=$(printf '%s' "$GOOGLE_CLIENT_SECRET" | tr -d '[:space:]')
  [ -n "$GOOGLE_CLIENT_SECRET" ] || { echo "  No secret entered; Google skipped."; GOOGLE_CLIENT_ID=""; }
fi
if [ -n "$GOOGLE_CLIENT_ID" ]; then
  add GOOGLE_CLIENT_ID "$GOOGLE_CLIENT_ID"
  add GOOGLE_CLIENT_SECRET "$GOOGLE_CLIENT_SECRET" --sensitive
  add GOOGLE_REDIRECT_URI "$SITE/api/auth/google/callback"
fi
unset GOOGLE_CLIENT_SECRET
echo

echo "Facebook  (developers.facebook.com > your app > App settings > Basic)"
read -r -p "  App ID (digits only, Enter to skip): " FACEBOOK_APP_ID
FACEBOOK_APP_ID=$(printf '%s' "$FACEBOOK_APP_ID" | tr -d '[:space:]')
if [ -n "$FACEBOOK_APP_ID" ]; then
  case "$FACEBOOK_APP_ID" in
    *[!0-9]*) echo "  A Facebook App ID is digits only."; exit 1 ;;
  esac
  read -r -s -p "  App secret (typing is hidden): " FACEBOOK_APP_SECRET; echo
  FACEBOOK_APP_SECRET=$(printf '%s' "$FACEBOOK_APP_SECRET" | tr -d '[:space:]')
  [ -n "$FACEBOOK_APP_SECRET" ] || { echo "  No secret entered; Facebook skipped."; FACEBOOK_APP_ID=""; }
fi
if [ -n "$FACEBOOK_APP_ID" ]; then
  add FACEBOOK_APP_ID "$FACEBOOK_APP_ID"
  add FACEBOOK_APP_SECRET "$FACEBOOK_APP_SECRET" --sensitive
  add FACEBOOK_REDIRECT_URI "$SITE/api/auth/facebook/callback"
fi
unset FACEBOOK_APP_SECRET
echo
echo "Done. The values are stored only in Vercel. Redeploy the API for them to take effect."
