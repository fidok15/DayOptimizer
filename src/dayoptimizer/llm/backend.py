from __future__ import annotations
from typing import Protocol
from pydantic import BaseModel
from dayoptimizer.core.models import PlannedChange

class NewEvent(BaseModel):
    title: str
    category: str                      # one of the user's categories
    date: str                          # ISO YYYY-MM-DD
    start_time: str | None = None      # "HH:MM"; None when the user gave no usable time
    duration_minutes: int | None = None

class DayRequest(BaseModel):
    """What the user said about their day: events to add, and the day to replan."""
    date: str                          # ISO YYYY-MM-DD, the day the message is about
    events: list[NewEvent] = []
    reply: str | None = None           # set when the message isn't about the schedule

class LLMBackend(Protocol):
    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest: ...
    def summarize_changes(self, changes: list[PlannedChange]) -> str: ...

def format_changes(changes: list[PlannedChange]) -> str:
    lines = []
    for c in changes:
        when = ""
        if c.new_start is not None:
            when = f" → {c.new_start.strftime('%H:%M')}"
            if c.new_end is not None:
                when += f"-{c.new_end.strftime('%H:%M')}"
        flag = " [approval required]" if c.requires_approval else ""
        lines.append(f"- [{c.kind}] {c.category}: {c.title}{when} — {c.reason}{flag}")
    return "\n".join(lines) if lines else "No changes — the plan is consistent."
