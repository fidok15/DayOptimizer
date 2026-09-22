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

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# One model per rule type: a small local model fills a short schema with only
# required fields far more reliably than one shape with many optional ones.
class TimeRule(BaseModel):
    source: str                        # the user's own sentence this came from
    time: str                          # "HH:MM"
    category: str | None = None        # None = the whole day

class FreeRule(BaseModel):
    source: str
    start: str
    end: str
    weekday: Weekday | None = None     # None = every day

class GapRule(BaseModel):
    source: str
    category: str
    rest_days: int                     # days off between two occurrences; models
                                       # mix up "days apart" with "days of break"

class WeekRule(BaseModel):
    source: str
    category: str
    count: int

class CompiledNotes(BaseModel):
    """The user's notes as rules the planner can enforce (core/constraints.py)."""
    not_before: list[TimeRule] = []
    not_after: list[TimeRule] = []
    keep_free: list[FreeRule] = []
    min_gap_days: list[GapRule] = []
    max_per_week: list[WeekRule] = []
    not_compiled: list[str] = []       # sentences no rule type can express

    def rows(self) -> list[dict]:
        rows = []
        for kind in ("not_before", "not_after", "keep_free", "min_gap_days", "max_per_week"):
            for rule in getattr(self, kind):
                row = {"type": kind, **rule.model_dump()}
                if kind == "min_gap_days":
                    row["days"] = row.pop("rest_days") + 1
                rows.append(row)
        return rows

class LLMBackend(Protocol):
    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest: ...
    def compile_notes(self, notes: str, categories: list[str]) -> CompiledNotes: ...
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
    "- category must be exactly one of the listed categories: pick the closest fit for what the "
    "activity IS. A doctor's or dentist's visit, an errand or meeting a friend is not Work.\n"
    "- day is a word: today, tomorrow, day_after_tomorrow or a weekday name. A day said once "
    "('tomorrow dentist at 10, then work') applies to the events after it until another day is said. "
    "'morning'/'evening' alone do not change the day.\n"
    "- start_time is HH:MM, 24h. 'then'/'after that' starts when the previous event ends. "
    "If the time can't be worked out, leave start_time empty.\n"
    "- end_time is HH:MM when the user says until when ('until 17', 'from 20 to 22'). "
    "Otherwise duration_minutes from the message: 'half an hour' = 30, 'about an hour' = 60, "
    "'an hour and a half' / 'półtorej godziny' = 90, '2h' = 120; empty if not said.\n"
    "- title is the activity alone, without its time or day.\n"
    "- If the message isn't about the schedule, return no events and a short reply.\n"
    "Example, with categories Important, Meeting, Work, Food, Gym:\n"
    "'tomorrow dentist at 10 for half an hour, then work until 17, coffee with Tom at 18' -> "
    '{"events":[{"title":"dentist","category":"Important","day":"tomorrow","start_time":"10:00",'
    '"duration_minutes":30},{"title":"work","category":"Work","day":"tomorrow","start_time":"10:30",'
    '"end_time":"17:00"},{"title":"coffee with Tom","category":"Meeting","day":"tomorrow",'
    '"start_time":"18:00"}]}  (appointments and seeing people go to a category for such things, '
    "not to Work or Food)"
)

_SUMMARY_SYSTEM = (
    "You summarize the changes to the user's day plan for them: concise, bulleted, what and why. "
    "Write in the language of the event titles and quoted notes. Copy every title and quoted "
    "note exactly, never translate them. Do not invent changes or reasons outside the list."
)


def request_prompt(text: str, today: str, now: str, categories: list[str]) -> str:
    """User turn for parse_request (`today` is unused: days come back as words).
    Includes the user's routine brief, when saved, for typical durations and habits."""
    from dayoptimizer.routine import load_routine
    routine = load_routine()
    context = f"the user's routine (use it for usual durations, don't copy it into events):\n{routine}\n" if routine else ""
    return f"{context}now: {now}\ncategories: {', '.join(categories)}\nmessage: {text}"


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


_NOTES_SYSTEM = (
    "You translate a user's notes about their week into rules a planner can enforce. "
    "The notes may be in any language; copy `source` in that language. "
    "Each rule goes into the list named after its type; a note that fits none goes into "
    "not_compiled. The lists:\n"
    "- not_before / not_after: set `time` (HH:MM). The category may not be scheduled before/after it\n"
    "- keep_free: set `start` and `end` (HH:MM) for a window that stays empty, and `weekday` for a "
    "single day (mon..sun). Do NOT use `time` for this type\n"
    "- min_gap_days: `rest_days` = how many days without it must pass between two occurrences. "
    "'not two days in a row' / 'at least one day of rest between' = 1, "
    "'two days of break between' = 2, 'at most once every three days' = 2\n"
    "- max_per_week: `count` = how many times a week at most\n"
    "Rules:\n"
    "- category must be copied EXACTLY from the listed categories, or left empty when the sentence "
    "is about the whole day. Never write 'everything' or a category that isn't listed.\n"
    "- A span of time the user wants left empty (\"keep free\", \"nothing planned\", \"time for "
    "family\", \"free for myself\") is ALWAYS a keep_free rule with start and end. Never leave "
    "such a sentence uncompiled.\n"
    "- Never turn a wish or a feeling into a time limit. If a sentence names no concrete time, "
    "count or day, it is not a rule: put it in not_compiled and nothing else.\n"
    "- source is the user's own sentence, copied, so they can check the translation.\n"
    "- Only translate what the sentence clearly says. Never invent limits or times.\n"
    "- A sentence that no rule type can express (a mood, a preference about how the day "
    "should feel) goes into not_compiled, copied as written. Split several rules out of "
    "one sentence when it holds several.\n"
    "Examples, with categories Food, Gym, Work:\n"
    '"no lunch before 14:00" -> '
    '{"not_before":[{"source":"no lunch before 14:00","time":"14:00","category":"Food"}]}\n'
    '"Sunday evenings 18:00-22:00 belong to my family" -> '
    '{"keep_free":[{"source":"Sunday evenings 18:00-22:00 belong to my family",'
    '"start":"18:00","end":"22:00","weekday":"sun"}]}\n'
    '"every day 12:00-13:00 stays free" -> '
    '{"keep_free":[{"source":"every day 12:00-13:00 stays free","start":"12:00","end":"13:00"}]}  '
    "(no weekday means every day; set weekday only when the note names one day)\n"
    '"I never train two days in a row" -> '
    '{"min_gap_days":[{"source":"I never train two days in a row","category":"Gym","rest_days":1}]}\n'
    '"gym three times a week at most" -> '
    '{"max_per_week":[{"source":"gym three times a week at most","category":"Gym","count":3}]}\n'
    '"no work after 18:00" -> '
    '{"not_after":[{"source":"no work after 18:00","time":"18:00","category":"Work"}]}\n'
    '"I want to feel less rushed" -> {"not_compiled":["I want to feel less rushed"]}\n'
    '"dinner around 21:00" -> {"not_compiled":["dinner around 21:00"]}  '
    '("around" is a preference, not a limit)'
)


def compile_prompt(notes: str, categories: list[str]) -> str:
    return f"categories: {', '.join(categories)}\nnotes:\n{notes}"
