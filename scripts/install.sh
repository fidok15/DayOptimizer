#!/bin/bash
# One-time setup. Afterwards `dayoptimizer` works from any terminal and opens
# the planner in your browser. Safe to run again (e.g. after `git pull`).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/dayoptimizer"

step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\033[31m%s\033[0m\n' "$1" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "DayOptimizer needs macOS: it works with Apple Calendar through macOS itself."

step "1/3 Python dependencies"
command -v uv >/dev/null 2>&1 || fail "uv is missing. Install it (https://docs.astral.sh/uv/), open a new terminal, then run this again:
  curl -LsSf https://astral.sh/uv/install.sh | sh"
uv sync --project "$REPO"

step "2/3 Calendar access"
"$REPO/scripts/setup-bundle.sh" >/dev/null
echo "Ready. macOS asks for calendar permission the first time DayOptimizer reads your calendar."

step "3/3 The dayoptimizer command"
mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<LAUNCH
#!/bin/bash
# Installed by $REPO/scripts/install.sh
exec uv run --quiet --project "$REPO" dayoptimizer "\$@"
LAUNCH
chmod 755 "$LAUNCHER"
echo "Installed $LAUNCHER"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    RC="$HOME/.zshrc"; [ "${SHELL##*/}" = "bash" ] && RC="$HOME/.bash_profile"
    if ! grep -qs 'DayOptimizer: .local/bin' "$RC"; then
      printf '\n# DayOptimizer: .local/bin on PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
      echo "Added ~/.local/bin to your PATH in $RC. Open a new terminal to use it."
    fi
    ;;
esac

step "Done"
echo "Open the planner any time with:  dayoptimizer"
echo "Other commands:                  dayoptimizer --help"
