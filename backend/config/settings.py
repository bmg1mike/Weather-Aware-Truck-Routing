"""Django settings. Every deploy-specific value comes from the environment (spec section 10).

No database tables are used: the app is stateless apart from the cache.
"""

import os
from pathlib import Path
from typing import Any, Literal, cast

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a local .env without overriding the real environment.

    Accepts an optional ``export`` prefix and single or double quotes around the value.
    Set ``DJANGO_SKIP_DOTENV=1`` to ignore the file (the test suite does).
    """
    if os.environ.get("DJANGO_SKIP_DOTENV") == "1" or not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")
    SECRET_KEY = "insecure-dev-only-key"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "trips",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Stateless service: no models, no migrations, no database.
DATABASES: dict[str, Any] = {}

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
USE_I18N = False
APPEND_SLASH = False

# --- CORS ---------------------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
# Lets the cross-origin frontend read the rate-limit retry hint.
CORS_EXPOSE_HEADERS = ["Retry-After"]

# --- Cache: Redis in production, local memory in development -----------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
CACHES: dict[str, dict[str, Any]]
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "truck-routing",
        }
    }

# --- Django REST Framework ----------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "trips.errors.api_exception_handler",
}

# --- Providers (server-side only; never sent to the frontend) ----------------------------------
TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY", "")

WindSource = Literal["sustained", "gust"]
_wind_source = os.environ.get("WIND_SOURCE", "sustained").strip().lower() or "sustained"
if _wind_source not in ("sustained", "gust"):
    raise ImproperlyConfigured("WIND_SOURCE must be 'sustained' or 'gust'.")
# [ASSUMPTION] spec 6.2: sustained wind is scored; gusts are display-only unless switched here.
WIND_SOURCE = cast(WindSource, _wind_source)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
