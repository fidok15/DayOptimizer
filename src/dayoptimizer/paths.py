"""Filesystem locations for user data. Everything private lives under
~/.dayoptimizer (override with DAYOPTIMIZER_HOME, mainly for tests)."""
from __future__ import annotations
import os
from pathlib import Path


def app_dir() -> Path:
    return Path(os.environ.get("DAYOPTIMIZER_HOME", "~/.dayoptimizer")).expanduser()


def user_config_path() -> Path:
    return app_dir() / "config.local.yaml"


def db_path() -> Path:
    return app_dir() / "data.db"


def routine_path() -> Path:
    return app_dir() / "routine.md"


def garmin_token_dir() -> Path:
    return app_dir() / "garmin"


def ensure_private_dir() -> Path:
    """Create the app dir if needed and make sure it is private (0700):
    it holds health data, calendar cache and Garmin OAuth tokens."""
    d = app_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d
