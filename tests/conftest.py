import os
import tempfile
import pytest

# test modules load config at import time, before any fixture runs: point the
# app dir away from the user's real ~/.dayoptimizer during collection too
os.environ["DAYOPTIMIZER_HOME"] = tempfile.mkdtemp(prefix="dayoptimizer-tests-")


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path, monkeypatch):
    """Every test gets a private, empty DAYOPTIMIZER_HOME — tests never touch
    the user's real ~/.dayoptimizer."""
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path / "app-home"))
