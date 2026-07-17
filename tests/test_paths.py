import os
import stat
from pathlib import Path
from dayoptimizer import paths


def test_app_dir_respects_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path / "custom"))
    assert paths.app_dir() == tmp_path / "custom"
    assert paths.db_path() == tmp_path / "custom" / "data.db"
    assert paths.user_config_path() == tmp_path / "custom" / "config.local.yaml"
    assert paths.garmin_token_dir() == tmp_path / "custom" / "garmin"


def test_ensure_private_dir_creates_with_0700(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path / "priv"))
    created = paths.ensure_private_dir()
    assert created.is_dir()
    assert stat.S_IMODE(created.stat().st_mode) == 0o700


def test_ensure_private_dir_tightens_existing_perms(tmp_path, monkeypatch):
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(loose))
    paths.ensure_private_dir()
    assert stat.S_IMODE(loose.stat().st_mode) == 0o700
