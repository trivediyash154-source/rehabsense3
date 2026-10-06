"""Test fixtures: an isolated in-file SQLite database per test session."""

from __future__ import annotations

import os
import tempfile

import pytest

# Configure before any app module reads settings.
_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-not-for-production-0123456789abcdef")
os.environ.setdefault("DEBUG", "true")
# Tests never depend on whatever model bundles happen to be on disk; tests
# that need one build a tiny bundle themselves.
os.makedirs(f"{_tmp}/models", exist_ok=True)
os.environ.setdefault("ML_MODEL_DIR", f"{_tmp}/models")

from app.db.database import Base, SessionLocal, engine  # noqa: E402
from app.db.seed import seed_exercises  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_exercises(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def clinician(client):
    """A registered clinician plus auth headers."""
    import uuid

    email = f"clin-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "a-very-long-passphrase", "name": "Dr Test",
              "role": "PHYSIOTHERAPIST"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Signup establishes a browser session (cookies). The test client is a
    # program, so it takes a bearer pair from the machine endpoint.
    pair = client.post(
        "/api/auth/token", json={"email": email, "password": "a-very-long-passphrase"}
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {pair['access_token']}"},
        "user": body["user"],
        "email": email,
        "password": "a-very-long-passphrase",
    }


@pytest.fixture
def patient_record(client, clinician):
    response = client.post(
        "/api/patients",
        headers=clinician["headers"],
        json={"name": "Demo Patient", "age": 24, "operated_leg": "LEFT",
              "surgery_date": "2026-05-10", "notes": "clinician-only note"},
    )
    assert response.status_code == 201, response.text
    return response.json()
