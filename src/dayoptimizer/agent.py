from __future__ import annotations
import os
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "com.dayoptimizer.check"

HOME_DIR = Path.home() / ".dayoptimizer"
BUNDLE_BINARY = str(HOME_DIR / "DayOptimizer.app" / "Contents" / "MacOS" / "dayopt")
RUNNER_PATH = HOME_DIR / "check_runner.py"
LAUNCHD_LOG_PATH = HOME_DIR / "check.launchd.log"
CHECK_LOG_PATH = HOME_DIR / "check.log"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def _schedule(interval: int, at: list[str] | None) -> str:
    """Every `interval` seconds, or only at the given HH:MM times each day."""
    if not at:
        return f"""    <key>StartInterval</key>
    <integer>{interval}</integer>"""
    times = "".join(f"""
        <dict>
            <key>Hour</key>
            <integer>{int(t.split(':')[0])}</integer>
            <key>Minute</key>
            <integer>{int(t.split(':')[1])}</integer>
        </dict>""" for t in at)
    return f"""    <key>StartCalendarInterval</key>
    <array>{times}
    </array>"""


def build_plist(bundle_binary: str, runner: str, interval: int = 900, at: list[str] | None = None) -> str:
    """Pure: render the launchd plist XML. No I/O."""
    log_path = escape(str(LAUNCHD_LOG_PATH))
    bundle_binary = escape(str(bundle_binary))
    runner = escape(str(runner))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{bundle_binary}</string>
        <string>{runner}</string>
    </array>
{_schedule(interval, at)}
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""


def build_runner(repo: str) -> str:
    """Pure: render the runner-script source that launchd's bundle binary
    executes. Chdirs into the repo, redirects stdout/stderr to check.log,
    and invokes `dayoptimizer check` in-process."""
    return f'''import os
import sys

os.chdir({repo!r})
log = open(os.path.expanduser("~/.dayoptimizer/check.log"), "a")
sys.stdout = log
sys.stderr = log
sys.argv = ["dayoptimizer", "check"]
try:
    from dayoptimizer.cli import main
    main()
except SystemExit:
    pass
except Exception as exc:
    import traceback
    traceback.print_exc()
    from dayoptimizer.core.notify import notify
    notify("DayOptimizer", f"Background check failed ({{type(exc).__name__}}). "
                           "Details in ~/.dayoptimizer/check.log")
finally:
    log.flush()
'''


def install(interval: int = 900, at: list[str] | None = None) -> str:
    """Write the runner script + plist and (re)bootstrap the launchd agent."""
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    RUNNER_PATH.write_text(build_runner(REPO_ROOT))
    PLIST_PATH.write_text(build_plist(BUNDLE_BINARY, str(RUNNER_PATH), interval, at))

    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)],
                    capture_output=True)
    result = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
                             capture_output=True)

    if result.returncode == 0:
        when = f"daily at {', '.join(at)}" if at else f"interval {interval}s"
        return f"Installed agent {LABEL} ({when})."
    stderr = result.stderr.decode(errors="replace") if result.stderr else ""
    return f"Agent install failed ({result.returncode}): {stderr}"


def uninstall() -> str:
    """Bootout the launchd agent and remove its plist."""
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)],
                    capture_output=True)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return f"Uninstalled agent {LABEL}."


def status() -> str:
    """Return 'running' if the agent is loaded in launchd, else 'not loaded'."""
    uid = os.getuid()
    result = subprocess.run(["launchctl", "print", f"gui/{uid}/{LABEL}"],
                             capture_output=True)
    return "running" if result.returncode == 0 else "not loaded"
