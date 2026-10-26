import os
import tempfile

import pytest

os.environ["DAYOPTIMIZER_HOME"] = tempfile.mkdtemp(prefix="dayoptimizer-tests-")


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path, monkeypatch):
    """Every test gets a private, empty DAYOPTIMIZER_HOME — tests never touch
    the user's real ~/.dayoptimizer."""
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path / "app-home"))
    monkeypatch.setattr("dayoptimizer.llm.backend.planning_backends", lambda cfg: [])
    monkeypatch.setattr("dayoptimizer.llm.ollama_backend.ensure_running", lambda: None)
