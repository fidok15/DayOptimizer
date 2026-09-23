import subprocess
from pathlib import Path

SETUP = Path("scripts/setup-bundle.sh")
WRAPPER = Path("scripts/dayoptimizer-app")
INSTALL = Path("scripts/install.sh")


def test_scripts_exist_and_are_executable():
    for p in (SETUP, WRAPPER, INSTALL):
        assert p.exists(), p
        assert p.stat().st_mode & 0o111, f"{p} not executable"


def test_scripts_pass_bash_syntax_check():
    for p in (SETUP, WRAPPER, INSTALL):
        r = subprocess.run(["bash", "-n", str(p)], capture_output=True)
        assert r.returncode == 0, r.stderr


def test_no_personal_strings():
    # built indirectly so this guard doesn't itself ship the banned string
    # (the repo-wide de-personalization grep must stay empty)
    banned = "".join(["fi", "dok"])
    for p in (SETUP, WRAPPER, INSTALL):
        text = p.read_text().lower()
        assert banned not in text
        assert "com.dayoptimizer.app" in SETUP.read_text()
