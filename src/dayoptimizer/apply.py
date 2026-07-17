from __future__ import annotations
from typing import Callable
from dayoptimizer.core.models import PlannedChange

def apply_changes(changes, calendar, storage, confirm: Callable[[PlannedChange], bool]):
    """Returns (applied, errors): errors is a list of human-readable messages
    for changes whose calendar write failed (typically a missing calendar on
    first run) — callers must surface these, not just rely on the storage
    log, or a write failure is invisible to the user."""
    applied = []
    errors: list[str] = []
    for c in changes:
        if c.kind == "note":
            storage.log_change(f"[note] {c.category}: {c.title}", c.reason)
            continue
        if c.requires_approval and not confirm(c):
            pid = storage.save_pending(c)
            storage.log_change(f"[pending #{pid}] {c.kind} {c.category}: {c.title}", c.reason)
            continue
        try:
            if c.kind == "move":
                calendar.move_event(c.event_id, c.new_start, c.new_end)
            elif c.kind == "create":
                calendar.create_event(c.category, c.title, c.new_start, c.new_end)
        except KeyError:
            # no calendar named after this category (typical on first run) —
            # skip this change but keep applying the rest of the plan
            msg = (f"calendar '{c.category}' not found — create or rename a calendar "
                   "with this name in the Calendar app")
            storage.log_change(f"[error] {c.kind} {c.category}: {c.title}", msg)
            errors.append(msg)
            continue
        when = f" → {c.new_start:%H:%M}" if c.new_start is not None else ""
        storage.log_change(f"[{c.kind}] {c.category}: {c.title}{when}", c.reason)
        applied.append(c)
    return applied, errors
