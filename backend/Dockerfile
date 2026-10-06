# RehabSense API (FastAPI + realtime WebSockets + scikit-learn inference).
#
# A long-running server: persistent WebSocket connections (ESP32 ingestion and
# dashboards), in-memory per-session processors and model bundles held in
# memory. It is NOT a serverless function and does not belong on Vercel.
#
# Build from the repository root (the model bundles live in ml/artifacts):
#   docker build -f backend/Dockerfile -t rehabsense-api .
#
# Python matches the training environment (ml/.venv, 3.14) and scikit-learn
# is pinned to the version the bundles were trained with: the server refuses a
# bundle whose sklearn major.minor differs, and verifies every model file's
# SHA-256 against its bundle.json before loading.
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements-production.txt ./
RUN pip install -r requirements-production.txt

COPY backend/ ./
# Inference only: the trained, hash-verified bundles. Training never happens
# here. Only the two deployed bundles are copied, not datasets or experiments.
COPY ml/artifacts/activity_bilateral /app/models/activity_bilateral
COPY ml/artifacts/activity_single_side /app/models/activity_single_side
# Fail the image build if a bundle does not verify.
RUN ML_MODEL_DIR=/app/models python -c "from app.sensing.inference import ModelBundle, find_bundle; \
    [ModelBundle.load(find_bundle('/app/models', n)) for n in ('activity_bilateral','activity_single_side')]; \
    print('model bundles verified')"

# UID 1000: Hugging Face Spaces always run the container as user 1000, and
# every other host accepts it, so files the API writes stay writable.
RUN useradd --create-home --uid 1000 rehabsense && mkdir -p /data/storage && chown rehabsense /data/storage
USER rehabsense

ENV ENVIRONMENT=production ML_MODEL_DIR=/app/models PORT=8000
EXPOSE 8000
# Migrations normally run as a release step (`alembic upgrade head`); the API
# refuses to start if the schema is not at the head. Hosts without a release
# step (Render's free tier) set RUN_MIGRATIONS_ON_START=true instead.
# One worker: live sessions are held in process memory (see DEPLOYMENT.md).
CMD ["sh", "/app/docker-entrypoint.sh"]
