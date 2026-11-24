"""Environment-driven settings (spec section 10)."""

import importlib
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured


def load_settings(monkeypatch, **env):
    for key in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "REDIS_URL", "WIND_SOURCE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DJANGO_SKIP_DOTENV", "1")  # keep a developer's local .env out
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("config.settings", None)
    try:
        return importlib.import_module("config.settings")
    finally:
        sys.modules.pop("config.settings", None)


def test_locmem_cache_without_redis(monkeypatch):
    settings = load_settings(monkeypatch, DJANGO_SECRET_KEY="x")
    assert settings.CACHES["default"]["BACKEND"].endswith("LocMemCache")


def test_redis_cache_when_url_set(monkeypatch):
    settings = load_settings(monkeypatch, DJANGO_SECRET_KEY="x", REDIS_URL="redis://cache:6379/0")
    assert settings.CACHES["default"]["BACKEND"].endswith("RedisCache")
    assert settings.CACHES["default"]["LOCATION"] == "redis://cache:6379/0"


def test_secret_key_required_outside_debug(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_settings(monkeypatch)


def test_debug_allows_dev_secret(monkeypatch):
    settings = load_settings(monkeypatch, DJANGO_DEBUG="true")
    assert settings.DEBUG is True


def test_wind_source_defaults_to_sustained(monkeypatch):
    assert load_settings(monkeypatch, DJANGO_SECRET_KEY="x").WIND_SOURCE == "sustained"


def test_wind_source_gust(monkeypatch):
    assert (
        load_settings(monkeypatch, DJANGO_SECRET_KEY="x", WIND_SOURCE="gust").WIND_SOURCE == "gust"
    )


def test_invalid_wind_source_rejected(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_settings(monkeypatch, DJANGO_SECRET_KEY="x", WIND_SOURCE="peak")


def test_cross_origin_frontend_can_read_retry_after(monkeypatch):
    assert "Retry-After" in load_settings(monkeypatch, DJANGO_SECRET_KEY="x").CORS_EXPOSE_HEADERS


@pytest.mark.parametrize(
    "line", ['TOMTOM_API_KEY="abc"', "TOMTOM_API_KEY='abc'", "export TOMTOM_API_KEY=abc"]
)
def test_dotenv_strips_quotes_and_export(monkeypatch, tmp_path, line):
    from config.settings import _load_dotenv

    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    monkeypatch.delenv("DJANGO_SKIP_DOTENV", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"# comment\n{line}\n")
    _load_dotenv(env_file)
    import os

    assert os.environ["TOMTOM_API_KEY"] == "abc"


def test_http_client_logging_cannot_print_provider_urls(monkeypatch):
    # httpx logs full request URLs at INFO, which would include the TomTom key.
    settings = load_settings(monkeypatch, DJANGO_SECRET_KEY="x")
    for name in ("httpx", "httpcore"):
        assert settings.LOGGING["loggers"][name]["level"] == "WARNING"


def test_local_cache_holds_a_full_trip(monkeypatch):
    # A 1,000 mi trip at 10 mi needs ~300 cells x 2 hours plus routes; Django's default is 300.
    settings = load_settings(monkeypatch, DJANGO_SECRET_KEY="x")
    assert settings.CACHES["default"]["OPTIONS"]["MAX_ENTRIES"] >= 10_000
