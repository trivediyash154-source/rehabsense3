"""Application configuration, entirely environment-driven.

Nothing here carries a production secret. `SECRET_KEY` has a development
default that the app refuses to start with when DEBUG is off.
"""

from __future__ import annotations

from functools import lru_cache

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- identity ---
    app_name: str = "RehabSense API"
    api_prefix: str = "/api"
    analytics_version: str = "mvp-1.0"

    # --- runtime ---
    # development | test | production. Production is strict: every required
    # variable must be set explicitly and nothing falls back to a dev default
    # (see assert_production_safe).
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # --- persistence ---
    # SQLite is the zero-setup DEVELOPMENT default only. Production requires
    # an explicit PostgreSQL DATABASE_URL and refuses to start without one.
    database_url: str = "sqlite:///./rehabsense.db"
    # Production refuses to serve until the schema is at the Alembic head.
    require_migrated_schema: bool = False

    # --- security ---
    secret_key: str = DEV_SECRET
    access_token_minutes: int = 60 * 12
    refresh_token_days: int = 14

    # --- browser session cookies ---
    # The browser reaches this API through the Next.js dev/prod proxy, so the
    # session cookie is first-party: HttpOnly keeps it out of reach of any
    # script (an XSS cannot exfiltrate it the way it could a localStorage
    # token), and SameSite=Lax blocks it from riding cross-site form posts.
    # Non-browser clients (simulator, firmware, CI) still use bearer tokens.
    cookie_access_name: str = "rs_session"
    cookie_refresh_name: str = "rs_refresh"
    cookie_path: str = "/"
    cookie_domain: str | None = None
    cookie_samesite: str = "lax"
    # Off by default so plain-HTTP localhost development works; the production
    # gate below requires it.
    cookie_secure: bool = False

    # --- failed-login handling ---
    max_failed_logins: int = 8
    lockout_minutes: int = 15

    # --- CORS: explicit origins, never a wildcard ---
    # Common Next.js dev ports. Anything else must be set explicitly via
    # CORS_ORIGINS — a browser silently blocking the health probe looks
    # exactly like "backend is down", which is a confusing failure to debug.
    # NoDecode: pydantic-settings JSON-decodes list fields from the
    # environment before any validator runs, so a plain comma-separated
    # CORS_ORIGINS would crash at startup. This hands the raw string to the
    # validator below instead.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ]
    )

    # --- signal processing (documented defaults) ---
    sample_rate_hz: float = 100.0
    calibration_seconds: float = 2.5
    complementary_alpha: float = 0.98
    lowpass_cutoff_hz: float = 5.0
    fsr_stance_threshold: float = 0.15

    # --- recovery score weights (ALGORITHMS.md §7) ---
    weight_rom: float = 0.30
    weight_symmetry: float = 0.25
    weight_compliance: float = 0.20
    weight_cadence: float = 0.15
    weight_pain: float = 0.10

    # Normalisation references. Configurable rather than magic numbers.
    target_rom_deg: float = 135.0
    reference_cadence_spm: float = 110.0

    # --- trend engine ---
    trend_deviation_band: float = 0.15

    # --- hardware v2: 1 ESP32 + 2 MPU6050 + N force channels ---
    # Calibration: hold still, then a few slow repetitions.
    hw_calibration_health_s: float = 1.0
    hw_calibration_still_s: float = 3.0
    hw_calibration_movement_s: float = 5.0
    # Analysis window and stride when no model dictates the window. When an
    # activity model is loaded, its own trained window length is used.
    hw_window_s: float = 2.0
    hw_stride_s: float = 0.5
    # Rate of the decimated stream sent to dashboards for live charts.
    hw_sensor_frame_hz: float = 25.0
    # How often a movement assessment row is written during a session.
    hw_assessment_interval_s: float = 5.0
    # Simulated devices (simulated: true in the handshake) are refused when
    # false. Leave on for development; turn off where only real hardware
    # should ever be accepted.
    allow_simulated_devices: bool = True
    # Optional fleet secret for devices that have no key of their own
    # (simulators, unregistered dev boards).
    device_ingest_key: str | None = None
    # When true, a non-simulated device must be registered and present its
    # own key; anything else is refused (DEVICE_NOT_REGISTERED). Production
    # forces this on.
    require_registered_devices: bool = False

    # --- object storage (exports, raw archives, model artifacts) ---
    # local: a directory (development). s3: any S3-compatible service.
    storage_backend: str = "local"
    storage_local_dir: str = "./var/storage"
    storage_s3_bucket: str | None = None
    storage_s3_prefix: str = "rehabsense/"
    storage_s3_endpoint_url: str | None = None
    storage_s3_region: str | None = None

    # --- request limits ---
    max_request_bytes: int = 1_000_000

    # --- raw sensor storage ---
    # Raw dual-IMU samples are stored in compressed ~1 s chunks so sessions
    # can become (consented) training data. They expire after this many days
    # unless explicitly retained for training under an active consent.
    store_raw_samples: bool = True
    raw_sample_retention_days: int = 30

    # --- ML model bundles (produced by ml/, never overwritten) ---
    ml_model_dir: str = "../ml/artifacts"
    ml_activity_model: str = "activity_bilateral"
    ml_activity_model_version: str | None = None
    ml_activity_model_single: str = "activity_single_side"
    ml_activity_model_single_version: str | None = None

    @field_validator("database_url", mode="after")
    @classmethod
    def _psycopg_driver(cls, value: str) -> str:
        # Hosts hand out postgres:// or postgresql:// URLs. SQLAlchemy reads the
        # former as an unknown dialect and the latter as psycopg2, which is not
        # installed; the driver this API ships with is psycopg 3.
        for scheme in ("postgres://", "postgresql://"):
            if value.startswith(scheme):
                return "postgresql+psycopg://" + value[len(scheme):]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        """Accept either a comma-separated string or a JSON array."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            import json

            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(origin).strip() for origin in parsed if str(origin).strip()]
            except json.JSONDecodeError:
                pass
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @property
    def weights(self) -> dict[str, float]:
        return {
            "rom": self.weight_rom,
            "symmetry": self.weight_symmetry,
            "compliance": self.weight_compliance,
            "cadence": self.weight_cadence,
            "pain": self.weight_pain,
        }

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def assert_production_safe(self) -> None:
        """Refuse to start with an unsafe configuration outside debug mode.

        Called from the startup lifespan, so a misconfigured deployment fails
        loudly at boot rather than silently serving patient data insecurely.
        """
        import os

        if self.is_production:
            # Explicit, not defaulted: a missing variable must never silently
            # become the development value (e.g. SQLite).
            missing = [v for v in ("DATABASE_URL", "SECRET_KEY", "CORS_ORIGINS", "COOKIE_SECURE",
                                   "STORAGE_BACKEND") if not os.environ.get(v)]
            if missing:
                raise RuntimeError(
                    "ENVIRONMENT=production but these required variables are not set: "
                    + ", ".join(missing) + ". No development defaults are used in production.")
            if self.debug:
                raise RuntimeError("ENVIRONMENT=production requires DEBUG=false.")
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError(
                    "ENVIRONMENT=production requires a PostgreSQL DATABASE_URL "
                    "(postgresql+psycopg://...). SQLite is development-only.")
            if self.storage_backend == "local" and not os.environ.get("STORAGE_LOCAL_DIR"):
                raise RuntimeError(
                    "ENVIRONMENT=production with STORAGE_BACKEND=local needs an explicit "
                    "STORAGE_LOCAL_DIR on a persistent volume (or use STORAGE_BACKEND=s3).")
            if self.storage_backend == "s3" and not self.storage_s3_bucket:
                raise RuntimeError("STORAGE_BACKEND=s3 requires STORAGE_S3_BUCKET.")
        if self.debug:
            return
        if self.secret_key == DEV_SECRET:
            raise RuntimeError(
                "SECRET_KEY is still the development default. Set a real secret "
                "before running with DEBUG=false."
            )
        # HS256 keys shorter than the digest give no extra security (RFC 7518).
        if len(self.secret_key.encode()) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 bytes.")

        # A session cookie sent over plaintext HTTP is readable in transit.
        if not self.cookie_secure:
            raise RuntimeError(
                "COOKIE_SECURE must be true outside development so the session "
                "cookie is only ever sent over HTTPS."
            )
        if self.cookie_samesite.lower() not in {"lax", "strict"}:
            raise RuntimeError(
                "COOKIE_SAMESITE must be 'lax' or 'strict'. 'none' would let "
                "any site send the session cookie with its own requests."
            )

        # cors_origins is passed straight to CORSMiddleware's allow_origins.
        # Starlette treats a "*" entry as allow-all, and because this API is
        # credentialed it would then echo back whatever Origin the caller
        # sent -- meaning any site could make authenticated requests with a
        # logged-in clinician's cookies. Refuse it rather than warn.
        if any(origin.strip() == "*" for origin in self.cors_origins):
            raise RuntimeError(
                "CORS_ORIGINS contains a wildcard '*'. This API sends "
                "credentials, so it must list explicit origins. Set "
                "CORS_ORIGINS to a comma-separated list of exact origins."
            )
        if not self.cors_origins:
            raise RuntimeError(
                "CORS_ORIGINS is empty, so every browser request would be "
                "blocked. Set it to the frontend's origin."
            )
        for origin in self.cors_origins:
            # A bare host or a path-bearing URL is silently ignored by the
            # middleware (it compares origins by exact string), which presents
            # as an unexplained CORS failure in the browser.
            if not origin.startswith(("http://", "https://")):
                raise RuntimeError(
                    f"CORS_ORIGINS entry {origin!r} is not an origin. Include "
                    "the scheme, e.g. https://app.example.com."
                )
            if origin.rstrip("/").count("/") > 2:
                raise RuntimeError(
                    f"CORS_ORIGINS entry {origin!r} contains a path. An origin "
                    "is scheme://host[:port] only."
                )
            if origin.startswith("http://"):
                host = origin[len("http://") :].split(":", 1)[0]
                if host not in {"localhost", "127.0.0.1", "[::1]"}:
                    raise RuntimeError(
                        f"CORS_ORIGINS entry {origin!r} is plaintext HTTP. "
                        "Bearer tokens and patient data must not cross an "
                        "unencrypted origin; use https://."
                    )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production:
        import os

        # Production posture is not optional.
        s.require_registered_devices = True
        s.require_migrated_schema = True
        # Simulated devices only when explicitly enabled (e.g. a demo).
        if "ALLOW_SIMULATED_DEVICES" not in os.environ:
            s.allow_simulated_devices = False
    return s
