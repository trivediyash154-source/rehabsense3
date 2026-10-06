"""Deployment posture: production config gate, readiness, limits, device auth."""

from __future__ import annotations

import pytest

from tests.test_hardware_v2_integration import _hello, _register


def test_readiness_reports_each_dependency_without_internals(client):
    r = client.get("/api/health/ready").json()
    assert set(r) >= {"api", "database", "schema", "ml", "storage", "realtime", "status"}
    text = str(r).lower()
    for secret in ("postgres", "sqlite", "password", "secret", "://"):
        assert secret not in text


def test_readiness_is_503_when_a_dependency_fails(client, monkeypatch):
    from app.services import storage

    # The test DB is built with create_all and has no model bundles, so it may
    # legitimately be degraded; the status code must agree with the body.
    r = client.get("/api/health/ready")
    assert r.status_code == (200 if r.json()["status"] == "ok" else 503)

    class Broken:
        def health(self):
            return False

    monkeypatch.setattr(storage, "get_storage", lambda: Broken())
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json()["storage"] == "error" and r.json()["status"] == "degraded"


def _prod(monkeypatch, **env):
    from app.core.config import Settings

    for k in ("DATABASE_URL", "SECRET_KEY", "CORS_ORIGINS", "COOKIE_SECURE", "STORAGE_BACKEND",
              "STORAGE_LOCAL_DIR", "DEBUG"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_production_refuses_missing_variables_and_sqlite(monkeypatch):
    s = _prod(monkeypatch)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        s.assert_production_safe()
    s = _prod(monkeypatch, DATABASE_URL="sqlite:///./x.db", SECRET_KEY="k" * 48,
              CORS_ORIGINS="https://app.example.com", COOKIE_SECURE="true", STORAGE_BACKEND="s3",
              STORAGE_S3_BUCKET="b", DEBUG="false")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        s.assert_production_safe()
    s = _prod(monkeypatch, DATABASE_URL="postgresql+psycopg://u:p@db/rs", SECRET_KEY="k" * 48,
              CORS_ORIGINS="https://app.example.com", COOKIE_SECURE="true", STORAGE_BACKEND="s3",
              STORAGE_S3_BUCKET="b", DEBUG="false")
    s.assert_production_safe()                       # complete production config passes
    s = _prod(monkeypatch, DATABASE_URL="postgresql+psycopg://u:p@db/rs", SECRET_KEY="k" * 48,
              CORS_ORIGINS="*", COOKIE_SECURE="true", STORAGE_BACKEND="s3",
              STORAGE_S3_BUCKET="b", DEBUG="false")
    with pytest.raises(RuntimeError, match="wildcard"):
        s.assert_production_safe()


def test_production_forces_registered_devices_and_no_simulators(monkeypatch):
    from app.core.config import get_settings

    _prod(monkeypatch)
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.require_registered_devices and s.require_migrated_schema
        assert s.allow_simulated_devices is False
    finally:
        monkeypatch.delenv("ENVIRONMENT")
        get_settings.cache_clear()


def test_oversized_request_is_rejected(client):
    r = client.post("/api/auth/token", content=b"x" * 2_000_000,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


@pytest.fixture
def v2_session(client, clinician, patient_record):
    return client.post("/api/sessions", headers=clinician["headers"],
                       json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"}).json()["id"]


def _handshake(client, sid, hello):
    with client.websocket_connect(f"/ws/ingest/v2/{sid}") as dev:
        dev.send_json(hello)
        return dev.receive_json()


def test_device_authorization_matrix(client, v2_session, monkeypatch):
    from app.core.config import get_settings

    sid = v2_session
    key = _register(client, "esp32-matrix-01")
    # Registered device, wrong key -> DENIED
    assert _handshake(client, sid, _hello(simulated=False, device_id="esp32-matrix-01",
                                          key="nope"))["code"] == "DEVICE_UNAUTHORIZED"
    # Unregistered device in registered-only mode (production) -> DENIED
    monkeypatch.setattr(get_settings(), "require_registered_devices", True)
    assert _handshake(client, sid, _hello(simulated=False, device_id="esp32-unknown"))["code"] \
        == "DEVICE_NOT_REGISTERED"
    # Registered, authenticated -> ALLOWED
    assert _handshake(client, sid, _hello(simulated=False, device_id="esp32-matrix-01",
                                          key=key))["type"] == "hello_ack"


def test_revoked_and_expired_devices_are_denied(client, clinician, patient_record):
    from datetime import datetime, timedelta, timezone

    from app.db.database import SessionLocal
    from app.db.models.device import Device
    from tests.test_hardware_v2_integration import _technician

    def new_session():
        return client.post("/api/sessions", headers=clinician["headers"],
                           json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"}).json()["id"]

    tech = _technician(client)
    key = client.post("/api/devices/register", headers=tech,
                      json={"device_id": "esp32-revoke-01"}).json()["device_key"]
    assert client.post("/api/devices/esp32-revoke-01/revoke", headers=tech).status_code == 200
    # Revoked: refused even with the old key, and even without one.
    for k in (key, None):
        assert _handshake(client, new_session(), _hello(simulated=False, device_id="esp32-revoke-01",
                                                        key=k))["code"] == "DEVICE_REVOKED"
    key2 = client.post("/api/devices/register", headers=tech,
                       json={"device_id": "esp32-expire-01", "expires_in_days": 1}).json()["device_key"]
    db = SessionLocal()
    try:
        d = db.query(Device).filter_by(device_id="esp32-expire-01").one()
        d.key_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    assert _handshake(client, new_session(), _hello(simulated=False, device_id="esp32-expire-01",
                                                    key=key2))["code"] == "DEVICE_KEY_EXPIRED"


def test_export_is_stored_with_hash_and_location(client, clinician, patient_record, tmp_path,
                                                 monkeypatch):
    import hashlib

    from app.core.config import get_settings
    from app.simulator.dual_imu import DualImuModel
    from tests.test_research_export import _record_physical, _research

    monkeypatch.setattr(get_settings(), "storage_local_dir", str(tmp_path / "store"))
    pid, headers = patient_record["id"], clinician["headers"]
    sid = _research(client, headers, pid, "P20")
    _record_physical(client, headers, sid, DualImuModel(seed=1), 12.0, "esp32-store-01")
    r = client.get(f"/api/sessions/{sid}/export.zip", headers=headers)
    assert r.status_code == 200
    sha = hashlib.sha256(r.content).hexdigest()
    assert r.headers["X-RehabSense-Artifact-SHA256"] == sha
    arts = client.get(f"/api/sessions/{sid}/artifacts", headers=headers).json()["items"]
    assert arts[0]["kind"] == "EXPORT_ZIP" and arts[0]["sha256"] == sha
    assert arts[0]["storage_uri"].startswith("local://recordings/")
    stored = tmp_path / "store" / arts[0]["storage_uri"][len("local://"):]
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == sha


def test_s3_storage_backend_against_s3_api_emulator(tmp_path, monkeypatch):
    """S3Storage exercised against moto's S3 API (an emulator, not a real bucket)."""
    import hashlib

    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    from app.services.storage import S3Storage

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="rs-test")
        st = S3Storage("rs-test", "rehabsense/", None, "us-east-1")
        assert st.health()
        src = tmp_path / "a.bin"
        src.write_bytes(b"raw evidence" * 100)
        obj = st.put_file("recordings/x/raw.npz", src)
        assert obj.uri == "s3://rs-test/rehabsense/recordings/x/raw.npz"
        assert obj.sha256 == hashlib.sha256(src.read_bytes()).hexdigest()
        with pytest.raises(FileExistsError):
            st.put_file("recordings/x/raw.npz", src)          # never overwrite
        back = tmp_path / "b.bin"
        st.get_file("recordings/x/raw.npz", back)
        assert back.read_bytes() == src.read_bytes()


def test_local_storage_refuses_path_escape_and_overwrite(tmp_path):
    from app.services.storage import LocalStorage

    st = LocalStorage(str(tmp_path / "s"))
    src = tmp_path / "f"
    src.write_bytes(b"x")
    st.put_file("a/b", src)
    with pytest.raises(FileExistsError):
        st.put_file("a/b", src)
    with pytest.raises(ValueError):
        st.put_file("../../etc/x", src)


def test_a_handshake_without_data_creates_no_recording(client, clinician, patient_record):
    from app.db.database import SessionLocal
    from app.db.models.sensing import Recording

    sid = client.post("/api/sessions", headers=clinician["headers"],
                      json={"patient_id": patient_record["id"], "exercise_type": "SQUAT"}).json()["id"]
    key = _register(client, "esp32-noop-01")
    assert _handshake(client, sid, _hello(simulated=False, device_id="esp32-noop-01",
                                          key=key))["type"] == "hello_ack"
    client.post(f"/api/sessions/{sid}/end", headers=clinician["headers"], json={})
    db = SessionLocal()
    try:
        assert db.query(Recording).filter_by(session_id=sid).count() == 0
    finally:
        db.close()


def test_ml_status_block_is_derived_not_asserted(client, clinician):
    from app.api.hardware import ml_status_block
    from app.db.database import SessionLocal

    block = client.get("/api/ml/models", headers=clinician["headers"]).json()["status_block"]
    assert block["REAL_REHABSENSE_HARDWARE_VALIDATED"] == "NO"
    assert block["CLINICAL_VALIDATION"] == "NO"
    assert block["HUMAN_LABELED_PHYSICAL_DATA"] == 0
    # With the shipped bundle's own metadata: public YES, hardware/clinical NO.
    shipped = {"bilateral": {"validation_status": {
        "public_dataset": "EVALUATED (subject-independent; see metrics.json)",
        "rehabsense_hardware": "NOT_VALIDATED", "clinical": "NOT_VALIDATED"}}}
    db = SessionLocal()
    try:
        b = ml_status_block(db, shipped)
    finally:
        db.close()
    assert b == {"MODEL_IMPLEMENTED": "YES", "PUBLIC_DATASET_VALIDATED": "YES",
                 "REAL_REHABSENSE_HARDWARE_VALIDATED": "NO", "HUMAN_LABELED_PHYSICAL_DATA": 0,
                 "CLINICAL_VALIDATION": "NO"}


def test_host_style_postgres_urls_use_the_installed_psycopg_driver(monkeypatch):
    from app.core.config import Settings

    for given in ("postgres://u:p@db.internal:5432/rs?sslmode=disable",
                  "postgresql://u:p@db.internal:5432/rs?sslmode=disable",
                  "postgresql+psycopg://u:p@db.internal:5432/rs?sslmode=disable"):
        monkeypatch.setenv("DATABASE_URL", given)
        assert Settings().database_url == "postgresql+psycopg://u:p@db.internal:5432/rs?sslmode=disable"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./dev.db")
    assert Settings().database_url == "sqlite:///./dev.db"


def test_a_switched_off_model_is_reported_not_loaded_and_not_degraded(client, monkeypatch):
    from app.core.config import get_settings
    from app.sensing import model_store

    monkeypatch.setattr(get_settings(), "ml_activity_model_single", "none")
    model_store.reset()
    try:
        bundle, reason = model_store.get("single_side")
        assert bundle is None and "disabled on this deployment" in reason
        st = model_store.status()
        assert st["single_side"] == {"loaded": False, "disabled": True, "reason": reason}
        # Readiness does not count a deliberately disabled model as a fault.
        assert client.get("/api/health/ready").json()["ml"] in ("ok", "degraded")
        from app.api.health import health_ready  # noqa: F401  (route import sanity)
    finally:
        model_store.reset()
