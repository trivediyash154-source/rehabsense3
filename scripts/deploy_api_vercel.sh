#!/usr/bin/env bash
# Deploy the RehabSense FastAPI backend to Vercel as a container image
# (Vercel Functions, Fluid compute; beta on all plans, including Hobby).
#
#   VERCEL_ORG_ID=team_... VERCEL_PROJECT_ID=prj_... bash scripts/deploy_api_vercel.sh --prod
#
# Builds a small upload directory -- backend/ (no venv, tests, databases or
# env files), the two deployed model bundles, and backend/Dockerfile as
# Dockerfile.vercel, which Vercel builds and routes all traffic to -- then runs
# `vercel deploy`. Configuration (DATABASE_URL, SECRET_KEY, CORS_ORIGINS, PORT,
# ...) lives in the Vercel project's environment variables, never in files.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/rs-api.XXXXXX")"
trap 'rm -rf "$OUT"' EXIT
rsync -a --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude tests \
  --exclude '*.db' --exclude '*.db-*' --exclude var --exclude '.env' --exclude '.env.*' \
  "$ROOT/backend/" "$OUT/backend/"
mkdir -p "$OUT/ml/artifacts"
cp -R "$ROOT/ml/artifacts/activity_bilateral" "$ROOT/ml/artifacts/activity_single_side" "$OUT/ml/artifacts/"
cp "$ROOT/backend/Dockerfile" "$OUT/Dockerfile.vercel"
cp "$ROOT/.dockerignore" "$OUT/.dockerignore"
echo "upload: $(find "$OUT" -type f | wc -l | tr -d ' ') files, $(du -sh "$OUT" | cut -f1)"
cd "$OUT"
"${VERCEL_BIN:-npx vercel@latest}" deploy --yes "$@"
