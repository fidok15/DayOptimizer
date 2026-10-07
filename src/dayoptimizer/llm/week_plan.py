"""The language model plans the days; this module checks its work.

The model gets the user's routine and notes as a guideline, the calendar as it
is, and lays out each day. Everything it returns goes through `validate`
before anything touches the calendar: blocks must not overlap each other or
the user's events (unless a note allows planning over one), must stay in the
future and in the user's categories, and must keep the rules compiled from the
notes. A plan that breaks something goes back to the model with the problems
listed; what is still wrong after the last try is dropped, not written.
"""
from __future__ import annotations
import re
from datetime import date, datetime, time, timedelta
from pydantic import BaseModel
from dayoptimizer.core.constraints import NoteRule, window_rule
from dayoptimizer.core.models import Event, PlannedChange

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class Block(BaseModel):
    day: str
    start: str
    end: str
    category: str
    title: str
    why: str = ""


class PlanOver(BaseModel):
    event_id: str
    note: str


class WeekPlan(BaseModel):
    blocks: list[Block] = []
    plan_over: list[PlanOver] = []
    summary: str = ""


SYSTEM = (
    "You plan days in a person's calendar. You get their typical routine, their notes, "
    "their categories and every event already in the calendar, and you return the blocks "
    "to add for each requested day.\n"
    "How to plan:\n"
    "- The routine is a guideline for the rhythm of a day (when they sleep, eat, work, rest), "
    "not a template to paste. Fit each day around what is already in the calendar: a day full "
    "of classes needs its meals, study and rest moved into the gaps, a free day can hold the "
    "longer blocks. Days should differ when their calendars differ.\n"
    "- The notes are the person's own rules and win over the routine. Follow each one "
    "literally: limits per week, rest days between workouts, earliest/latest times, which "
    "events may be planned over, travel times.\n"
    "- When the notes give a travel time to a place, add a commute block of that length before "
    "the first event there and after the last one that day (events back to back at the same "
    "place need no commute between them). Use the person's commute category if they have one.\n"
    "- Never overlap an existing event. The only exception: an event a note explicitly says may "
    "be planned over or ignored. Then list it in plan_over with its event_id and the note "
    "sentence copied word for word.\n"
    "- Blocks never overlap each other. Times are HH:MM, 24h; a block may end at 24:00. Sleep "
    "across midnight is two blocks (e.g. 23:00-24:00 and 00:00-07:00 the next day).\n"
    "- Plan only the requested days and only after the current time. Earlier blocks of yours "
    "that are listed as your previous plan will be replaced by what you return, so return the "
    "complete plan for each requested day.\n"
    "- category must be one of the listed categories, spelled exactly. Titles are short, in the "
    "language of the routine.\n"
    "- Keep real free time in every day; do not pack every minute.\n"
    "- why: a few words on the choice when it differs from the routine. summary: two or three "
    "sentences on how the days were adapted, in the language of the notes."
)


def _hhmm(value: str) -> int | None:
    m = re.fullmatch(r"([01]?\d|2[0-4]):([0-5]\d)", value.strip())
    if not m:
        return None
    total = int(m.group(1)) * 60 + int(m.group(2))
    return total if total <= 1440 else None


def _fmt(ev: Event) -> str:
    return f"{ev.start:%H:%M}-{ev.end:%H:%M}"


def build_prompt(days: list[date], routine: str, categories: list[str], events: list[Event],
                 previous: list[Event], now: datetime, health: str | None = None) -> str:
    """Everything the model needs, grouped by day so it reads like a calendar."""
    first = days[0] - timedelta(days=days[0].weekday())
    last = max(days[-1], first + timedelta(days=6))
    lines = [f"Now: {DAY_NAMES[now.weekday()]} {now:%Y-%m-%d %H:%M}",
             "Plan these days: " + ", ".join(f"{DAY_NAMES[d.weekday()]} {d.isoformat()}" for d in days),
             f"Categories: {', '.join(categories)}", ""]
    if health:
        lines += [f"Health today: {health}", ""]
    lines += [routine.strip(), "", "# Calendar"]
    d = first
    while d <= last:
        mine = sorted((e for e in events if e.start.date() == d and not e.all_day), key=lambda e: e.start)
        prev = sorted((e for e in previous if e.start.date() == d), key=lambda e: e.start)
        tag = " (plan this day)" if d in days else ""
        lines.append(f"## {DAY_NAMES[d.weekday()]} {d.isoformat()}{tag}")
        for e in mine:
            where = f" @ {e.location}" if e.location else ""
            lines.append(f"- [{e.id}] {_fmt(e)} {e.calendar}: {e.title}{where}")
        for e in prev:
            lines.append(f"- (your previous plan) {_fmt(e)} {e.calendar}: {e.title}")
        if not mine and not prev:
            lines.append("- nothing")
        d += timedelta(days=1)
    return "\n".join(lines)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[\"“”„'‘’]", "", text).lower().split())


def validate(plan: WeekPlan, days: list[date], categories: list[str], events: list[Event],
             notes: str, rules: list[NoteRule], now: datetime,
             history: dict[str, list[date]] | None = None,
             expect: set[date] | frozenset[date] = frozenset()) -> tuple[list[PlannedChange], list[str]]:
    """The blocks that keep every rule, as creates, and what was wrong with the rest.
    A day in `expect` (its routine has blocks) that comes back empty is a problem too."""
    problems: list[str] = []
    wanted = {d.isoformat(): d for d in days}
    note_text = _norm(notes)
    over = {p.event_id for p in plan.plan_over
            if len(_norm(p.note)) >= 10 and _norm(p.note) in note_text}
    for p in plan.plan_over:
        if p.event_id not in over:
            problems.append(f"plan_over {p.event_id}: \"{p.note}\" is not a sentence from the notes")
    blocking = [e for e in events if not e.all_day and not e.managed and e.id not in over]
    kept: list[tuple[datetime, datetime, Block]] = []
    for b in sorted(plan.blocks, key=lambda b: (b.day, b.start)):
        label = f"{b.day} {b.start}-{b.end} {b.category}: {b.title}"
        day = wanted.get(b.day)
        start_m, end_m = _hhmm(b.start), _hhmm(b.end)
        if end_m == 0 and start_m:
            end_m = 1440
        if day is None:
            problems.append(f"{label}: {b.day} is not one of the days to plan")
            continue
        if start_m is None or end_m is None or end_m <= start_m:
            problems.append(f"{label}: start and end must be HH:MM with end after start")
            continue
        if b.category not in categories:
            problems.append(f"{label}: '{b.category}' is not one of the categories")
            continue
        midnight = datetime.combine(day, time(0)).astimezone()
        start, end = midnight + timedelta(minutes=start_m), midnight + timedelta(minutes=end_m)
        if start < now:
            problems.append(f"{label}: starts before now ({now:%Y-%m-%d %H:%M})")
            continue
        clash = next((e for e in blocking if e.start < end and e.end > start), None)
        if clash is not None:
            problems.append(f"{label}: overlaps '{clash.title}' ({_fmt(clash)}) [{clash.id}]")
            continue
        twin = next((k for k in kept if k[0] < end and k[1] > start), None)
        if twin is not None:
            problems.append(f"{label}: overlaps your own block '{twin[2].title}' ({twin[2].start}-{twin[2].end})")
            continue
        broken = window_rule(rules, b.category, start_m, end_m, day.weekday())
        if broken is not None:
            problems.append(f"{label}: breaks the note \"{broken.source}\"")
            continue
        kept.append((start, end, b))
    kept, count_problems = _count_rules(kept, rules, history or {})
    problems += count_problems
    filled = {s.date() for s, _, _ in kept}
    problems += [f"{d.isoformat()}: no blocks planned for this day - return its full plan"
                 for d in sorted(expect) if d in wanted.values() and d not in filled
                 and datetime.combine(d, time(23, 59)).astimezone() > now]
    changes = [PlannedChange(kind="create", category=b.category, title=b.title, reason=b.why or "planned",
                             new_start=s, new_end=e) for s, e, b in kept]
    return changes, problems


def _count_rules(kept, rules: list[NoteRule], history: dict[str, list[date]]):
    """max_per_week and min_gap_days over the user's past days plus the plan.
    A block that would break one is dropped, later blocks first."""
    problems = []
    out = []
    dates: dict[str, set[date]] = {c: set(ds) for c, ds in history.items()}
    for s, e, b in kept:
        d = s.date()
        have = dates.setdefault(b.category, set())
        bad = None
        for r in rules:
            if r.category != b.category or d in have:
                continue
            if r.type == "max_per_week" and r.count is not None:
                week = d - timedelta(days=d.weekday())
                if len({x for x in have if week <= x < week + timedelta(days=7)}) >= r.count:
                    bad = r
            elif r.type == "min_gap_days" and r.days:
                if any(0 < abs((d - x).days) < r.days for x in have):
                    bad = r
            if bad:
                break
        if bad:
            problems.append(f"{b.day} {b.start}-{b.end} {b.category}: {b.title}: breaks the note \"{bad.source}\"")
            continue
        have.add(d)
        out.append((s, e, b))
    return out, problems


def diff(creates: list[PlannedChange], previous: list[Event]) -> list[PlannedChange]:
    """Blocks already in the calendar stay; the rest of the old plan goes."""
    old = {(e.calendar, e.title, e.start, e.end): e for e in previous}
    out = []
    for c in creates:
        if old.pop((c.category, c.title, c.new_start, c.new_end), None) is None:
            out.append(c)
    removed = [PlannedChange(kind="delete", category=e.calendar, title=e.title, event_id=e.id,
                             reason="replaced by the new plan") for e in old.values()]
    return removed + out


def plan_days(backend, days: list[date], routine: str, categories: list[str], events: list[Event],
              notes: str, rules: list[NoteRule], now: datetime, health: str | None = None,
              history: dict[str, list[date]] | None = None, expect: set[date] | frozenset[date] = frozenset(),
              attempts: int = 3) -> tuple[list[PlannedChange], str, list[str]]:
    """Ask, check, send the problems back; at most `attempts` rounds.
    Returns the calendar changes, the model's summary and what was dropped.
    A small local model (`one_day_at_a_time`) gets one day per request; what it
    planned for earlier days counts toward the weekly limits of later ones."""
    if len(days) > 1 and getattr(backend, "one_day_at_a_time", False):
        history = {c: list(ds) for c, ds in (history or {}).items()}
        changes, summaries, dropped = [], [], []
        for d in days:
            ch, summary, dr = plan_days(backend, [d], routine, categories, events, notes, rules, now,
                                        health, history, expect, attempts)
            changes += ch
            dropped += dr
            if summary:
                summaries.append(summary)
            for c in ch:
                if c.kind == "create" and c.new_start is not None:
                    history.setdefault(c.category, []).append(c.new_start.date())
        return changes, " ".join(summaries), dropped
    planned = set(days)
    previous = [e for e in events if e.managed and e.start.date() in planned and e.start >= now]
    prompt = build_prompt(days, routine, categories, [e for e in events if e not in previous],
                          previous, now, health)
    request = prompt
    for attempt in range(attempts):
        plan = backend.plan_week(SYSTEM, request)
        creates, problems = validate(plan, days, categories, events, notes, rules, now, history, expect)
        if not problems or attempt == attempts - 1:
            return diff(creates, previous), plan.summary, problems
        request = (prompt + "\n\n# Your previous answer\n" + plan.model_dump_json()
                   + "\n\n# It broke these rules - return the whole corrected plan\n"
                   + "\n".join(f"- {p}" for p in problems))
    raise AssertionError("unreachable")
