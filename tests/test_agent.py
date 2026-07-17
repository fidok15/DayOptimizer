from __future__ import annotations
from unittest.mock import patch, MagicMock
from dayoptimizer import agent


# --- build_plist (pure) -----------------------------------------------------

def test_build_plist_contains_label():
    xml = agent.build_plist("/a/dayopt", "/b/runner.py")
    assert "<string>com.dayoptimizer.check</string>" in xml

def test_build_plist_program_arguments_in_order():
    xml = agent.build_plist("/a/dayopt", "/b/runner.py")
    bin_idx = xml.index("<string>/a/dayopt</string>")
    runner_idx = xml.index("<string>/b/runner.py</string>")
    assert bin_idx < runner_idx

def test_build_plist_default_interval():
    xml = agent.build_plist("/a", "/b")
    assert "<integer>900</integer>" in xml

def test_build_plist_custom_interval():
    xml = agent.build_plist("/a", "/b", interval=300)
    assert "<integer>300</integer>" in xml
    assert "<integer>900</integer>" not in xml

def test_build_plist_run_at_load_false():
    xml = agent.build_plist("/a", "/b")
    assert "<false/>" in xml

def test_build_plist_log_paths_expanded_absolute():
    xml = agent.build_plist("/a", "/b")
    assert xml.count("/.dayoptimizer/check.launchd.log") == 2
    assert "~" not in xml

def test_build_plist_escapes_xml_specials():
    xml = agent.build_plist("/tmp/we&ird<path>/bin", "/tmp/run&ner.py", 900)
    assert "we&amp;ird&lt;path&gt;" in xml
    assert "run&amp;ner.py" in xml
    assert "<string>com.dayoptimizer.check</string>" in xml


# --- build_runner (pure) -----------------------------------------------------

def test_build_runner_contains_repo_path():
    src = agent.build_runner("/repo/DayOptimizer")
    assert "/repo/DayOptimizer" in src

def test_build_runner_contains_check_argv():
    src = agent.build_runner("/repo/DayOptimizer")
    assert "check" in src

def test_build_runner_contains_log_path():
    src = agent.build_runner("/repo/DayOptimizer")
    assert "check.log" in src

def test_build_runner_calls_cli_main():
    src = agent.build_runner("/repo/DayOptimizer")
    assert "cli" in src and "main" in src


# --- install / uninstall / status (I/O, subprocess mocked) ------------------

def test_install_writes_runner_and_plist(tmp_path, monkeypatch):
    home_dir = tmp_path / ".dayoptimizer"
    plist_path = tmp_path / "LaunchAgents" / "com.dayoptimizer.check.plist"
    runner_path = home_dir / "check_runner.py"
    monkeypatch.setattr(agent, "HOME_DIR", home_dir)
    monkeypatch.setattr(agent, "RUNNER_PATH", runner_path)
    monkeypatch.setattr(agent, "PLIST_PATH", plist_path)

    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr=b"")
        agent.install()

    assert runner_path.exists()
    assert plist_path.exists()
    assert "check" in runner_path.read_text()
    assert "com.dayoptimizer.check" in plist_path.read_text()

def test_install_calls_bootout_then_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "HOME_DIR", tmp_path)
    monkeypatch.setattr(agent, "RUNNER_PATH", tmp_path / "check_runner.py")
    monkeypatch.setattr(agent, "PLIST_PATH", tmp_path / "agent.plist")
    monkeypatch.setattr(agent.os, "getuid", lambda: 501)

    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr=b"")
        agent.install(interval=300)

    assert run.call_count == 2
    bootout_args = run.call_args_list[0].args[0]
    bootstrap_args = run.call_args_list[1].args[0]
    assert bootout_args[:2] == ["launchctl", "bootout"]
    assert bootout_args[2] == "gui/501"
    assert bootstrap_args[:2] == ["launchctl", "bootstrap"]
    assert bootstrap_args[2] == "gui/501"
    assert bootstrap_args[3] == str(tmp_path / "agent.plist")

def test_install_ignores_bootout_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "HOME_DIR", tmp_path)
    monkeypatch.setattr(agent, "RUNNER_PATH", tmp_path / "check_runner.py")
    monkeypatch.setattr(agent, "PLIST_PATH", tmp_path / "agent.plist")

    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.side_effect = [
            MagicMock(returncode=1, stderr=b"not loaded"),
            MagicMock(returncode=0, stderr=b""),
        ]
        result = agent.install()

    assert "Installed" in result or "install" in result.lower()

def test_install_returns_message_with_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "HOME_DIR", tmp_path)
    monkeypatch.setattr(agent, "RUNNER_PATH", tmp_path / "check_runner.py")
    monkeypatch.setattr(agent, "PLIST_PATH", tmp_path / "agent.plist")

    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr=b"")
        result = agent.install(interval=60)

    assert isinstance(result, str) and len(result) > 0

def test_uninstall_calls_bootout_and_removes_plist(tmp_path, monkeypatch):
    plist_path = tmp_path / "agent.plist"
    plist_path.write_text("dummy")
    monkeypatch.setattr(agent, "PLIST_PATH", plist_path)
    monkeypatch.setattr(agent.os, "getuid", lambda: 502)

    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr=b"")
        agent.uninstall()

    args = run.call_args_list[0].args[0]
    assert args == ["launchctl", "bootout", "gui/502", str(plist_path)]
    assert not plist_path.exists()

def test_uninstall_missing_plist_does_not_raise(tmp_path, monkeypatch):
    plist_path = tmp_path / "missing.plist"
    monkeypatch.setattr(agent, "PLIST_PATH", plist_path)

    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr=b"")
        agent.uninstall()  # should not raise

def test_status_running_when_returncode_zero(monkeypatch):
    monkeypatch.setattr(agent.os, "getuid", lambda: 503)
    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        result = agent.status()
    args = run.call_args.args[0]
    assert args == ["launchctl", "print", "gui/503/com.dayoptimizer.check"]
    assert result == "running"

def test_status_not_running_when_returncode_nonzero():
    with patch("dayoptimizer.agent.subprocess.run") as run:
        run.return_value = MagicMock(returncode=3, stdout=b"", stderr=b"Could not find")
        result = agent.status()
    assert result == "not loaded"
