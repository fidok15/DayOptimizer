from __future__ import annotations
import json
import subprocess


def build_osascript(title: str, message: str) -> list[str]:
    # json.dumps gives AppleScript-safe double-quoted strings (escapes " and \)
    return ["osascript", "-e",
            f"display notification {json.dumps(message, ensure_ascii=False)} with title {json.dumps(title, ensure_ascii=False)}"]


def notify(title: str, message: str) -> bool:
    try:
        subprocess.run(build_osascript(title, message),
                       check=False, capture_output=True, timeout=10)
        return True
    except Exception:
        return False
