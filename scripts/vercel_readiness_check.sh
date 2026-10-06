#!/usr/bin/env bash
# RehabSense Vercel readiness check (the Next.js frontend).
#
#   bash scripts/vercel_readiness_check.sh
#   REHABSENSE_API=https://api.example.com \
#   REHABSENSE_FRONTEND=https://rehabsense-platform.vercel.app bash scripts/vercel_readiness_check.sh
#
# Builds a clean copy of exactly what `vercel deploy` uploads (.vercelignore
# applied), installs it with `npm ci`, and builds it the way Vercel does
# (VERCEL=1) in the three deployment modes:
#   unconfigured                    must FAIL with a clear configuration error
#   BACKEND_ORIGIN=none             frontend-only: must build; /api/* -> 503
#   BACKEND_ORIGIN=https://...      must build and proxy /api/* to the API
# then scans the browser bundle and the source for local addresses, secrets,
# filesystem use and backend/ML dependencies.
#
# Optional live checks: REHABSENSE_API (the hosted FastAPI, https) and
# REHABSENSE_FRONTEND (the deployed site).
#
# Last line, and exit code:
#   VERCEL READY                                             0  (API verified live)
#   VERCEL READY — EXTERNAL BACKEND INFRASTRUCTURE REQUIRED  3  (no live API verified)
#   NOT VERCEL READY                                         1
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/rs-vercel.XXXXXX")"
APP="$WORK/app"
LOG="$WORK/check.log"
FAIL=0
pass() { printf '[PASS] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; FAIL=1; }
info() { printf '[INFO] %s\n' "$1"; }
run()  { "$@" >>"$LOG" 2>&1; }
check() { local name="$1"; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }
cleanup() { [ "${KEEP_WORK:-0}" = "1" ] && info "work dir kept: $WORK" || rm -rf "$WORK"; }
trap cleanup EXIT

# --- the upload set ------------------------------------------------------
# rsync does not understand gitignore negation ("!pattern"); those lines only
# re-include .env.example, which the build does not need.
grep -vE '^[[:space:]]*(#|!|$)' "$ROOT/.vercelignore" >"$WORK/excludes"
mkdir -p "$APP"
rsync -a --exclude-from="$WORK/excludes" --exclude node_modules --exclude .next \
  --exclude .git --exclude .vercel --exclude .DS_Store "$ROOT/" "$APP/"
cd "$APP" || exit 1
info "upload set: $(find . -type f | wc -l | tr -d ' ') files, $(du -sk . | cut -f1) KB (work dir $WORK)"

# --- dependencies, types, lint ------------------------------------------------
check "dependencies (npm ci from package-lock.json)" run npm ci --no-audit --no-fund
check "TypeScript (tsc --noEmit)" run npm run -s typecheck
check "ESLint" run npm run -s lint

# --- Vercel configuration -----------------------------------------------------------
vercel_config() {
  node -e '
    const fs = require("fs");
    const v = JSON.parse(fs.readFileSync("vercel.json", "utf8"));
    if (v.framework !== "nextjs") throw new Error("vercel.json framework must be nextjs");
    if (v.installCommand !== "npm ci") throw new Error("vercel.json installCommand must be npm ci");
    const p = JSON.parse(fs.readFileSync("package.json", "utf8"));
    if (!/<\s*\d+/.test((p.engines || {}).node || "")) throw new Error("engines.node needs an upper bound");
  ' >>"$LOG" 2>&1 || return 1
  for pat in 'backend/' 'ml/' 'firmware/' 'scripts/' 'docs/' '*.db' '.env*'; do
    grep -qxF "$pat" "$ROOT/.vercelignore" || { echo "missing .vercelignore entry $pat" >>"$LOG"; return 1; }
  done
}
check "Vercel configuration (vercel.json, .vercelignore, bounded Node engine)" vercel_config

# --- environment variable structure -------------------------------------------
env_structure() {
  for k in BACKEND_ORIGIN NEXT_PUBLIC_WS_URL NEXT_PUBLIC_SITE_URL; do
    grep -q "^$k=" "$ROOT/.env.example" || { echo ".env.example lacks $k" >>"$LOG"; return 1; }
  done
  # A secret must never be NEXT_PUBLIC_ (inlined into browser JavaScript).
  if grep -rhoE 'NEXT_PUBLIC_[A-Z0-9_]*(SECRET|TOKEN|PASSWORD|PRIVATE|_KEY)[A-Z0-9_]*' \
       "$ROOT/.env.example" app components lib middleware.ts next.config.ts >>"$LOG" 2>&1; then
    return 1
  fi
  # Server-only configuration must not be imported by client components.
  for f in $(grep -rlE '^"use client"' app components lib 2>/dev/null); do
    grep -q 'config.server' "$f" && { echo "client component imports config.server: $f" >>"$LOG"; return 1; }
  done
  return 0
}
check "environment variable structure (no secret NEXT_PUBLIC_*, server config server-only)" env_structure

# --- builds in the three modes -------------------------------------------------------
build() { rm -rf .next; env -u NEXT_PUBLIC_WS_URL -u NEXT_PUBLIC_SITE_URL -u BACKEND_ORIGIN \
  -u VERCEL_PROJECT_PRODUCTION_URL VERCEL=1 "$@" npm run -s build >"$WORK/build.log" 2>&1; }
rewrite_dest() { node -e 'const m=require("./.next/routes-manifest.json");
  const r=m.rewrites.afterFiles.find(x=>x.source==="/api/:path*"); console.log(r?r.destination:"")'; }

unconfigured() { ! build && grep -q "deployment configuration invalid" "$WORK/build.log"; }
check "Next.js build refuses an unconfigured Vercel deployment" unconfigured

frontend_only() { build BACKEND_ORIGIN=none NEXT_PUBLIC_SITE_URL=https://readiness.vercel.app \
  && [ "$(rewrite_dest)" = "/backend-unavailable" ]; }
check "Next.js build, frontend-only (BACKEND_ORIGIN=none; /api/* -> 503 BACKEND_NOT_CONNECTED)" frontend_only

API=https://api.readiness.invalid
WS=wss://api.readiness.invalid
connected() { build BACKEND_ORIGIN=$API NEXT_PUBLIC_WS_URL=$WS NEXT_PUBLIC_SITE_URL=https://readiness.vercel.app; }
check "Next.js build, API configured" connected
check "API proxy configuration (/api/* -> \$BACKEND_ORIGIN/api/*)" \
  test "$(rewrite_dest)" = "$API/api/:path*"

# --- bundle and source scans (on the API-configured build) -------------------------------
STATIC=.next/static
websocket() { grep -rqF "$WS" "$STATIC" && ! grep -rqE 'ws://(localhost|127\.0\.0\.1)' "$STATIC"; }
check "WebSocket configuration (browser uses NEXT_PUBLIC_WS_URL, never ws://localhost)" websocket
no_local() { ! grep -rqE 'localhost:[0-9]+|127\.0\.0\.1|0\.0\.0\.0:[0-9]+' "$STATIC"; }
check "no localhost production references in browser JavaScript" no_local
no_secrets() {
  ! grep -rqE 'DATABASE_URL|SECRET_KEY|postgres(ql)?(\+psycopg)?://|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|sk_live_|AWS_SECRET' "$STATIC" \
    && ! grep -rqF "$API" "$STATIC"   # BACKEND_ORIGIN is server-only
}
check "no secrets or server-only origins in browser JavaScript" no_secrets
no_fs() {
  ! grep -rqE "from \"(node:)?(fs|path|child_process|os)\"|require\(\"(fs|path)\"\)|/Users/|/private/tmp|file://" \
      app components lib middleware.ts \
    && ! grep -rqE '/Users/|/private/tmp' "$STATIC"
}
check "no local filesystem dependency" no_fs
boundary() {
  node -e '
    const p = require("./package.json");
    const deps = Object.keys({...p.dependencies, ...p.devDependencies});
    const bad = deps.filter(d => /^(pg|postgres|psycopg|sqlalchemy|prisma|@prisma\/|mysql|sqlite|onnxruntime|@tensorflow\/|tensorflow|torch|sklearn|pyodide)/.test(d));
    if (bad.length) { console.error("backend/ML packages in the frontend:", bad); process.exit(1); }
  ' >>"$LOG" 2>&1 || return 1
  ! grep -rqE "from \"(\.\./)+(backend|ml|firmware)/" app components lib || return 1
  for d in backend ml firmware docs scripts; do [ -e "$d" ] && { echo "$d uploaded" >>"$LOG"; return 1; }; done
  ! find . -path ./node_modules -prune -o \( -name '*.db' -o -name '*.joblib' -o -name '*.npz' -o -name '.env' -o -name '.env.local' \) -print | grep -q .
}
check "frontend/backend boundary (no DB drivers, ML, backend code or data uploaded)" boundary

# --- optional live checks ------------------------------------------------------------
API_LIVE=0
if [ -n "${REHABSENSE_API:-}" ]; then
  case "$REHABSENSE_API" in https://*) ;; *) fail "REHABSENSE_API must be https"; ;; esac
  body="$(curl -fsS --max-time 15 "$REHABSENSE_API/api/health/ready" 2>>"$LOG")"
  if printf '%s' "$body" | grep -q '"status":"ok"'; then pass "live API ready ($REHABSENSE_API)"; API_LIVE=1
  else fail "live API not ready ($REHABSENSE_API): ${body:-no response}"; fi
else
  info "live API: not checked (set REHABSENSE_API=https://api.<domain>)"
fi
if [ -n "${REHABSENSE_FRONTEND:-}" ]; then
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$REHABSENSE_FRONTEND/")"
  [ "$code" = "200" ] && pass "deployed frontend serves / ($REHABSENSE_FRONTEND)" || fail "deployed frontend / -> HTTP $code"
  health="$(curl -s --max-time 15 -w ' HTTP %{http_code}' "$REHABSENSE_FRONTEND/api/health")"
  case "$health" in
    *BACKEND_NOT_CONNECTED*) info "deployed frontend: frontend-only (/api/health -> 503 BACKEND_NOT_CONNECTED)" ;;
    *'HTTP 200') pass "deployed frontend reaches the API through /api/*" ;;
    *) fail "deployed frontend /api/health unexpected: $health" ;;
  esac
fi

echo
if [ "$FAIL" -ne 0 ]; then
  echo "details: $LOG (KEEP_WORK=1 keeps it)"; echo "NOT VERCEL READY"; exit 1
elif [ "$API_LIVE" -eq 1 ]; then
  echo "VERCEL READY"; exit 0
else
  echo "VERCEL READY — EXTERNAL BACKEND INFRASTRUCTURE REQUIRED"; exit 3
fi
