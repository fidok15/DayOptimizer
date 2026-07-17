import pytest


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path, monkeypatch):
    """Every test gets a private, empty DAYOPTIMIZER_HOME — tests never touch
    the user's real ~/.dayoptimizer."""
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path / "app-home"))
