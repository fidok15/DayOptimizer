"""The user's routine as a short brief for the LLM, rendered from the typical
week drawn in the setup page and saved to ~/.dayoptimizer/routine.md."""
from __future__ import annotations
import os
from dayoptimizer import paths

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
NAMES = dict(zip(DAYS, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")))


def _day_label(days: list[str]) -> str:
    """['mon','tue','wed'] -> 'Mon-Wed'; non-consecutive -> 'Mon, Wed'."""
    idx = [DAYS.index(d) for d in days]
    if len(idx) > 2 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{NAMES[days[0]]}-{NAMES[days[-1]]}"
    return ", ".join(NAMES[d] for d in days)


def render_routine(categories: dict, week: dict, notes: str = "") -> str:
    """Compact, LLM-friendly description of the routine. Days with the same
    blocks are merged so a regular work week costs one section, not five."""
    lines = ["# My typical week", "",
             "Categories (fixed = only moved with my OK, flexible = the planner may move it; "
             "priority 0-10, higher gets better hours):"]
    for name, c in sorted(categories.items(), key=lambda kv: -(kv[1] or {}).get("priority", 5)):
        c = c or {}
        mode = "flexible" if c.get("movable") else "fixed"
        lines.append(f"- {name}: {mode}, priority {c.get('priority', 5)}")
    groups: dict[tuple, list[str]] = {}
    for d in DAYS:
        blocks = sorted(week.get(d) or [], key=lambda b: b["start"])
        key = tuple((b["start"], b["end"], b["category"], b.get("title", ""),
                     bool(b.get("protected")) and not (b.get("intent") or "").strip(),
                     (b.get("intent") or "").strip())
                    for b in blocks)
        groups.setdefault(key, []).append(d)
    for key, days in sorted(groups.items(), key=lambda kv: DAYS.index(kv[1][0])):
        lines += ["", f"## {_day_label(days)}"]
        if not key:
            lines.append("(nothing drawn)")
        for start, end, cat, title, kept, intent in key:
            what = f"open: {intent} ({cat})" if intent else cat
            lines.append(f"{start}-{end} {what}" + (f": {title}" if title and title not in (cat, intent) else "")
                         + (" (protected: no tasks here)" if kept else ""))
    if notes and notes.strip():
        lines += ["", "## What matters to me", notes.strip()]
    return "\n".join(lines) + "\n"


def save_routine(text: str) -> str:
    path = paths.routine_path()
    paths.ensure_private_dir()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return str(path)


def load_routine() -> str | None:
    path = paths.routine_path()
    try:
        return path.read_text() if path.exists() else None
    except OSError:
        return None
