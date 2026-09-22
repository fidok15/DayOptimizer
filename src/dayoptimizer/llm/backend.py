from __future__ import annotations
import os
from datetime import date, timedelta
from typing import Literal, Protocol
from pydantic import BaseModel
from dayoptimizer.core.models import PlannedChange

# Models name the day in words; code turns it into a date (small models get date maths wrong).
DayWord = Literal["today", "tomorrow", "day_after_tomorrow",
                  "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def resolve_day(word: str, today: date) -> date:
    """'thursday' = the next Thursday from today (today itself if it is Thursday)."""
    if word in ("today", "tomorrow", "day_after_tomorrow"):
        return today + timedelta(days=("today", "tomorrow", "day_after_tomorrow").index(word))
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return today + timedelta(days=(names.index(word) - today.weekday()) % 7)

class NewEvent(BaseModel):
    title: str
    category: str                      # one of the user's categories
    day: DayWord = "today"
    start_time: str | None = None      # "HH:MM"; None when the user gave no usable time
    end_time: str | None = None        # "HH:MM" when the user says until when
    duration_minutes: int | None = None

class DayRequest(BaseModel):
    """What the user said about their day: the events to add."""
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


_REQUEST_SYSTEM = (
    "You turn a user's message about their day into calendar events for the DayOptimizer "
    "planner. The message may be in any language; keep event titles in that language.\n"
    "- One event per activity; never merge two activities or invent one. Example: 'dentist at 10, "
    "then work until 17' is TWO events: dentist 10:00 (no end given) and work from when the "
    "dentist ends until 17:00.\n"
    "- category must be exactly one of the listed categories: pick the closest fit.\n"
    "- day is a word: today, tomorrow, day_after_tomorrow or a weekday name. A day said once "
    "('tomorrow dentist at 10, then work') applies to the events after it until another day is said. "
    "'morning'/'evening' alone do not change the day.\n"
    "- start_time is HH:MM, 24h. 'then'/'after that' starts when the previous event ends. "
    "If the time can't be worked out, leave start_time empty.\n"
    "- end_time is HH:MM when the user says until when ('until 17', 'from 20 to 22'). "
    "Otherwise duration_minutes from the message ('about an hour' = 60); empty if not said.\n"
    "- If the message isn't about the schedule, return no events and a short reply."
)

_SUMMARY_SYSTEM = (
    "You summarize the changes to the user's day plan for them. In English, "
    "concise, bulleted, what and why. Do not invent changes outside the list."
)


def request_prompt(text: str, today: str, now: str, categories: list[str]) -> str:
    """User turn for parse_request (`today` is unused: days come back as words)."""
    return f"now: {now}\ncategories: {', '.join(categories)}\nmessage: {text}"


class LLMUnavailable(RuntimeError):
    """No usable LLM; the message tells the user how to get one."""


def make_backend(llm_config: dict) -> LLMBackend:
    """Pick the LLM from config `llm.backend`: ollama, anthropic, or auto
    (local Ollama when it's running, else the Anthropic API when a key is set)."""
    from dayoptimizer.llm.ollama_backend import OllamaBackend, ollama_running
    choice = llm_config.get("backend", "auto")
    local = llm_config.get("ollama_model", "qwen3:8b")
    if choice == "ollama" or (choice == "auto" and ollama_running()):
        return OllamaBackend(model=local)
    if choice in ("anthropic", "auto") and os.environ.get("ANTHROPIC_API_KEY"):
        from dayoptimizer.llm.anthropic_backend import AnthropicBackend
        return AnthropicBackend(model=llm_config.get("model", "claude-opus-4-8"))
    raise LLMUnavailable(
        "Requests in plain words need a language model. Either run one locally for free:\n"
        f"  brew install ollama && brew services start ollama && ollama pull {local}\n"
        "or add ANTHROPIC_API_KEY=... to the .env file in the DayOptimizer folder.")
