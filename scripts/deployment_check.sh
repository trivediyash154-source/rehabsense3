#!/usr/bin/env bash
# RehabSense deployment check.
#
#   scripts/deployment_check.sh                 static checks only
#   REHABSENSE_API=http://localhost:8000 REHABSENSE_FRONTEND=http://localhost:3000 \
#     REHABSENSE_ADMIN_EMAIL=... REHABSENSE_ADMIN_PASSWORD=... scripts/deployment_check.sh
#
# Static: frontend lint/typecheck/build, backend imports, model bundle
# verification, migration head consistency, backend test suite.
# Live (when REHABSENSE_API is set): scripts/deployment_check.py against the
# running stack. Physical hardware is always reported NOT TESTED.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
FAIL=0
step() { printf '\n== %s\n' "$1"; }
ok()   { printf 'PASS     %s\n' "$1"; }
bad()  { printf 'FAIL     %s\n' "$1"; FAIL=1; }

step "frontend"
cd "$ROOT"
npm run -s lint      >/dev/null 2>&1 && ok "lint"      || bad "lint"
npm run -s typecheck >/dev/null 2>&1 && ok "typecheck" || bad "typecheck"
npm run -s build     >/dev/null 2>&1 && ok "build"     || bad "build"

step "backend"
cd "$ROOT/backend"
"$PY" -c "import app.main" 2>/dev/null && ok "imports" || bad "imports"
"$PY" - <<'EOF' && ok "model bundles verify (hash, feature/preprocessing/sklearn versions)" || bad "model bundles"
import os
from app.sensing.inference import ModelBundle, find_bundle
root = os.environ.get("ML_MODEL_DIR", "../ml/artifacts")
for name in ("activity_bilateral", "activity_single_side"):
    p = find_bundle(root, name)
    assert p is not None, f"{name} missing under {root}"
    b = ModelBundle.load(p)
    print(f"         {b.name}/{b.version}: {len(b.classes)} classes, {b.input_kind}, "
          f"{b.rate_hz} Hz, {b.window_s} s, threshold {b.threshold}")
EOF
[ "$("$PY" -m alembic heads 2>/dev/null | grep -c head)" = "1" ] && ok "single alembic head" || bad "alembic heads"
if [ -n "${DATABASE_URL:-}" ]; then
  "$PY" -m alembic current 2>/dev/null | grep -q "(head)" && ok "database at migration head" \
    || bad "database not at migration head (run: alembic upgrade head)"
fi
"$PY" -m pytest -q tests -p no:cacheprovider >/tmp/rs_pytest.log 2>&1 \
  && ok "backend tests: $(tail -1 /tmp/rs_pytest.log)" || bad "backend tests: $(tail -1 /tmp/rs_pytest.log)"

if [ -n "${REHABSENSE_API:-}" ]; then
  step "live stack ($REHABSENSE_API)"
  "$PY" "$ROOT/scripts/deployment_check.py" || FAIL=1
else
  step "live stack"
  printf 'SKIPPED  set REHABSENSE_API to check a running API\n'
fi

step "physical hardware"
printf 'NOT TESTED  no board connected (docs/PHYSICAL_HARDWARE_CHECKLIST.md)\n'
exit $FAIL
