"""Settings for the test suite: deterministic, offline, no secrets required."""

import os

os.environ["DJANGO_SKIP_DOTENV"] = "1"
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DJANGO_DEBUG", "false")
os.environ["REDIS_URL"] = ""
os.environ["TOMTOM_API_KEY"] = "test-key"

from config.settings import *  # noqa: F403
