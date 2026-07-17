from unittest.mock import patch
from dayoptimizer.core.notify import build_osascript, notify


def test_build_osascript_quotes_safely():
    cmd = build_osascript('Title "x"', 'message with "quotes" and \\ backslash')
    assert cmd[0] == "osascript" and cmd[1] == "-e"
    assert "display notification" in cmd[2]
    assert '\\"quotes\\"' in cmd[2]  # escaped, not raw


def test_notify_never_raises():
    with patch("dayoptimizer.core.notify.subprocess.run", side_effect=OSError("boom")):
        assert notify("t", "m") is False
