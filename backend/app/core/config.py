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
    debug: bool = True
    log_level: str = "INFO"

    # --- persistence ---
    # SQLite by default (zero setup); point DATABASE_URL at PostgreSQL for
    # production, matching the documented architecture.
    database_url: str = "sqlite:///./rehabsense.db"

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

    def assert_production_safe(self) -> None:
        """Refuse to start with an unsafe configuration outside debug mode.

        Called from the startup lifespan, so a misconfigured deployment fails
        loudly at boot rather than silently serving patient data insecurely.
        """
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
    return Settings()
