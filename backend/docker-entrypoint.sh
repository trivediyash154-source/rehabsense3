#!/bin/sh
# Start the RehabSense API (one process: live sessions live in its memory).
#
# RUN_MIGRATIONS_ON_START=true runs `alembic upgrade head` first, for hosts
# that have no release / pre-deploy step (Render's free tier). Where a release
# step exists, run migrations there and leave this unset.
set -e
if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
  alembic upgrade head
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 \
  --ws-max-size 1048576 --proxy-headers --forwarded-allow-ips='*'
