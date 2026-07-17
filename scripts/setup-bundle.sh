#!/bin/bash
# Build the TCC app bundle that macOS requires for calendar access.
# EventKit silently denies processes whose host app lacks the calendar usage
# keys (Terminal, VS Code, Claude Code) — so DayOptimizer runs its calendar
# work through this minimal bundle instead. Run once after `uv sync`,
# then: open -W -a ~/.dayoptimizer/DayOptimizer.app --args <script.py>
set -euo pipefail
umask 077  # everything under ~/.dayoptimizer is private from the moment it exists

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv"
HOME_DIR="$HOME/.dayoptimizer"
APP="$HOME_DIR/DayOptimizer.app"
MACOS="$APP/Contents/MacOS"

[ -x "$VENV/bin/python" ] || { echo "No .venv found — run 'uv sync' in $REPO first."; exit 1; }

mkdir -p "$MACOS"
chmod 700 "$HOME_DIR"

# Copy the venv python binary (a copy, not a symlink: TCC identifies the app
# by its own executable) and recreate the venv layout around it.
cp -f "$VENV/bin/python" "$MACOS/dayopt"
cp -f "$VENV/pyvenv.cfg" "$MACOS/pyvenv.cfg"
ln -sfn "$VENV/lib" "$MACOS/lib"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>com.dayoptimizer.app</string>
  <key>CFBundleName</key><string>DayOptimizer</string>
  <key>CFBundleExecutable</key><string>dayopt</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>NSCalendarsFullAccessUsageDescription</key>
  <string>DayOptimizer reads and updates your calendar to build your day plan.</string>
  <key>NSCalendarsUsageDescription</key>
  <string>DayOptimizer reads and updates your calendar to build your day plan.</string>
</dict>
</plist>
PLIST

cat > "$HOME_DIR/cli_runner.py" <<RUNNER
import os, sys
from pathlib import Path
os.chdir("$REPO")
home = Path.home() / ".dayoptimizer"
args = (home / "cli_args").read_text().splitlines() if (home / "cli_args").exists() else ["plan"]
log = open(home / "cli.log", "w")
sys.stdout = log
sys.stderr = log
sys.argv = ["dayoptimizer"] + [a for a in args if a]
try:
    from dayoptimizer.cli import main
    main()
except SystemExit:
    pass
except Exception:
    import traceback; traceback.print_exc()
finally:
    log.flush()
RUNNER

echo "Bundle ready: $APP"
echo "First run will show the macOS calendar permission prompt:"
echo "  $REPO/scripts/dayoptimizer-app plan"
