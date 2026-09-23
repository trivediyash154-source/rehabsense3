"""The startup gate that refuses to serve patient data insecurely.

These guard `assert_production_safe`, which `app.main` calls in the startup
lifespan. Each case here is a deployment mistake that would otherwise only
show up as a browser CORS error or, worse, not at all.
"""

from __future__ import annotations

import pytest

from app.core.config import DEV_SECRET, Settings

REAL_SECRET = "k" * 48
GOOD_ORIGINS = ["https://app.example.com"]


def build(**overrides) -> Settings:
    """A settings object that ignores the developer's local .env file."""
    base = {
        "debug": False,
        "secret_key": REAL_SECRET,
        "cors_origins": list(GOOD_ORIGINS),
        "cookie_secure": True,
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def test_safe_production_config_is_accepted() -> None:
    build().assert_production_safe()


def test_debug_mode_skips_the_gate() -> None:
    """Local development must stay zero-setup: http origins, dev secret, all fine."""
    build(
        debug=True, secret_key=DEV_SECRET, cookie_secure=False,
        cors_origins=["http://localhost:3000"],
    ).assert_production_safe()


def test_insecure_cookie_is_refused() -> None:
    """A session cookie sent over plaintext HTTP is readable in transit."""
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        build(cookie_secure=False).assert_production_safe()


def test_samesite_none_is_refused() -> None:
    """SameSite=None would let any site send the session cookie."""
    with pytest.raises(RuntimeError, match="COOKIE_SAMESITE"):
        build(cookie_samesite="none").assert_production_safe()


def test_default_secret_is_refused() -> None:
    with pytest.raises(RuntimeError, match="development default"):
        build(secret_key=DEV_SECRET).assert_production_safe()


def test_short_secret_is_refused() -> None:
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        build(secret_key="tooshort").assert_production_safe()


def test_wildcard_cors_is_refused() -> None:
    """The brief's hard constraint: never wildcard CORS in production."""
    with pytest.raises(RuntimeError, match="wildcard"):
        build(cors_origins=["*"]).assert_production_safe()


def test_wildcard_hidden_among_valid_origins_is_refused() -> None:
    with pytest.raises(RuntimeError, match="wildcard"):
        build(cors_origins=["https://app.example.com", "*"]).assert_production_safe()


def test_empty_cors_is_refused() -> None:
    with pytest.raises(RuntimeError, match="empty"):
        build(cors_origins=[]).assert_production_safe()


def test_origin_without_scheme_is_refused() -> None:
    """Starlette compares origins by exact string, so a bare host never matches."""
    with pytest.raises(RuntimeError, match="not an origin"):
        build(cors_origins=["app.example.com"]).assert_production_safe()


def test_origin_with_a_path_is_refused() -> None:
    with pytest.raises(RuntimeError, match="contains a path"):
        build(cors_origins=["https://app.example.com/dashboard"]).assert_production_safe()


def test_plaintext_http_origin_is_refused_in_production() -> None:
    with pytest.raises(RuntimeError, match="plaintext HTTP"):
        build(cors_origins=["http://app.example.com"]).assert_production_safe()


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:8080"])
def test_loopback_http_origins_stay_allowed(origin: str) -> None:
    """A staging build pointed at a local frontend is a legitimate setup."""
    build(cors_origins=[origin]).assert_production_safe()


def test_trailing_slash_origin_is_accepted() -> None:
    """`https://app.example.com/` is an origin with an empty path, not a path."""
    build(cors_origins=["https://app.example.com/"]).assert_production_safe()


def test_comma_separated_env_string_still_parses() -> None:
    """Regression: pydantic-settings JSON-decodes list fields before validators."""
    settings = build(cors_origins="https://a.example.com, https://b.example.com")
    assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]
    settings.assert_production_safe()
