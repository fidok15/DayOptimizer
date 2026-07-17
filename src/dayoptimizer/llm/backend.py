from __future__ import annotations
from typing import Literal, Protocol
from pydantic import BaseModel
from dayoptimizer.core.models import PlannedChange

class Intent(BaseModel):
    action: Literal["plan_day", "move_event", "add_event", "show_plan", "question"]
    date: str | None = None            # ISO YYYY-MM-DD
    category: str | None = None        # calendar/category name
    title: str | None = None
    duration_minutes: int | None = None
    start_time: str | None = None      # "HH:MM"
    answer_hint: str | None = None     # for action=question: what the user asks about

class LLMBackend(Protocol):
    def parse_intent(self, text: str, today: str) -> Intent: ...
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
