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
from dayoptimizer.core.models import Event, PlannedChange, Task
from dayoptimizer.llm.task_rules import block_problem, minutes, task_lines, unplaced

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class Block(BaseModel):
    day: str
    start: str
    end: str
    category: str
    title: str
    why: str = ""
    task_id: str | None = None


class PlanOver(BaseModel):
    event_id: str
    note: str


class Unscheduled(BaseModel):
    task_id: str
    reason: str


class WeekPlan(BaseModel):
    blocks: list[Block] = []
    plan_over: list[PlanOver] = []
    unscheduled: list[Unscheduled] = []
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


TASK_RULES = (
    "\nTasks (listed under # Tasks, when there are any):\n"
    "- A task is work with a length the person wants done, usually before a deadline. Place its "
    "minutes as blocks with task_id = the task's id, category = the task's category, title = the "
    "task's title.\n"
    "- Task blocks go into the free time left after the day's routine and events; they never "
    "overlap either. They start after 'not before' and end by the deadline.\n"
    "- 'chunks >= N min': split the task into blocks of at least N minutes; only the very last "
    "piece may be shorter, to finish it. 'in one piece': one block for all its minutes.\n"
    "- Never place more minutes than are left. Overdue tasks first, then nearer deadlines, then "
    "higher priority.\n"
    "- Spread a long task over days rather than one marathon: at most about 3 hours of one task a day "
    "when the deadline allows.\n"
    "- A task whose deadline falls on a day you plan must be placed in full. If it cannot fit, place "
    "what fits and list the task in unscheduled with a short reason (how many minutes are missing and "
    "why). Never invent free time.\n"
    "- A task due after the planned days may wait, but use spare free time for it.\n"
)

EXAMPLES = (
    "\nExamples (shortened: a real answer also has the rest of the day's plan):\n"
    "1) Monday 2030-10-14 planned, free 13:00-15:00 and 16:00-18:00. Task: "
    "- [t1] Report (Work) 180 min left, due Mon 2030-10-14 18:00, chunks >= 60 min, priority normal\n"
    '{"blocks":[{"day":"2030-10-14","start":"13:00","end":"15:00","category":"Work","title":"Report",'
    '"task_id":"t1"},{"day":"2030-10-14","start":"16:00","end":"17:00","category":"Work",'
    '"title":"Report","task_id":"t1"}],"unscheduled":[]}\n'
    "2) Monday 2030-10-14 planned, free only 20:00-21:00. Task: "
    "- [t2] Slides (Learn) 120 min left, due Mon 2030-10-14 22:00, chunks >= 60 min, priority high\n"
    '{"blocks":[{"day":"2030-10-14","start":"20:00","end":"21:00","category":"Learn","title":"Slides",'
    '"task_id":"t2"}],"unscheduled":[{"task_id":"t2","reason":"60 min missing: no other free time '
    'before the deadline"}]}\n'
    "3) Tuesday 2030-10-15 planned, free 09:00-12:00. Tasks: "
    "- [t3] Taxes (Home) 60 min left, due Fri 2030-10-18 23:59, in one piece, priority normal; "
    "- [t4] Bug fix (Work) 90 min left, due Fri 2030-10-18 23:59, in one piece, priority high. "
    "The high-priority one goes first:\n"
    '{"blocks":[{"day":"2030-10-15","start":"09:00","end":"10:30","category":"Work","title":"Bug fix",'
    '"task_id":"t4"},{"day":"2030-10-15","start":"10:30","end":"11:30","category":"Home",'
    '"title":"Taxes","task_id":"t3"}],"unscheduled":[]}\n'
)


def system_prompt(few_shot: bool = True) -> str:
    """The planning instructions; the worked examples can be left out so the
    evals can measure what they add (scripts/eval_tasks.py --few-shot off)."""
    return SYSTEM + TASK_RULES + (EXAMPLES if few_shot else "")


def _hhmm(value: str) -> int | None:
    m = re.fullmatch(r"([01]?\d|2[0-4]):([0-5]\d)", value.strip())
    if not m:
        return None
    total = int(m.group(1)) * 60 + int(m.group(2))
    return total if total <= 1440 else None


def _fmt(ev: Event) -> str:
    return f"{ev.start:%H:%M}-{ev.end:%H:%M}"


def build_prompt(days: list[date], routine: str, categories: list[str], events: list[Event],
                 previous: list[Event], now: datetime, health: str | None = None,
                 tasks: list[Task] = (), left: dict[str, int] | None = None) -> str:
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
    pending = task_lines(list(tasks), left or {}, now)
    if pending:
        lines += ["", "# Tasks"] + pending
    return "\n".join(lines)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[\"“”„'‘’]", "", text).lower().split())


def validate(plan: WeekPlan, days: list[date], categories: list[str], events: list[Event],
             notes: str, rules: list[NoteRule], now: datetime,
             history: dict[str, list[date]] | None = None,
             expect: set[date] | frozenset[date] = frozenset(),
             tasks: list[Task] = (), left: dict[str, int] | None = None) -> tuple[list[PlannedChange], list[str]]:
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
    by_id = {t.id: t for t in tasks}
    left = dict(left or {})
    running = dict(left)
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
        if b.task_id is not None:
            why = block_problem(by_id.get(b.task_id), b.category, start, end, running.get(b.task_id, 0), now)
            if why is not None:
                problems.append(f"{label}: task {b.task_id} {why}")
                continue
            running[b.task_id] -= minutes(start, end)
        kept.append((start, end, b))
    kept, count_problems = _count_rules(kept, rules, history or {})
    problems += count_problems
    used: dict[str, int] = {}
    for s, e, b in kept:
        if b.task_id is not None:
            used[b.task_id] = used.get(b.task_id, 0) + minutes(s, e)
    after = {tid: n - used.get(tid, 0) for tid, n in left.items()}
    listed = {u.task_id for u in plan.unscheduled}
    problems += [f"unscheduled {u.task_id}: not one of the tasks" for u in plan.unscheduled if u.task_id not in by_id]
    problems += unplaced(list(tasks), after, listed, max(days), now)
    filled = {s.date() for s, _, _ in kept}
    problems += [f"{d.isoformat()}: no blocks planned for this day - return its full plan"
                 for d in sorted(expect) if d in wanted.values() and d not in filled
                 and datetime.combine(d, time(23, 59)).astimezone() > now]
    changes = [PlannedChange(kind="create", category=b.category, title=b.title, reason=b.why or "planned",
                             new_start=s, new_end=e, task_id=b.task_id) for s, e, b in kept]
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
              attempts: int = 3, tasks: list[Task] = (), left: dict[str, int] | None = None,
              few_shot: bool = True) -> tuple[list[PlannedChange], str, list[str], list[str]]:
    """Ask, check, send the problems back; at most `attempts` rounds.
    Returns the calendar changes, the model's summary, what was dropped and the
    tasks it could not fit ("t2: reason").
    A small local model (`one_day_at_a_time`) gets one day per request; what it
    planned for earlier days counts toward the weekly limits and the task
    minutes of later ones."""
    if len(days) > 1 and getattr(backend, "one_day_at_a_time", False):
        history = {c: list(ds) for c, ds in (history or {}).items()}
        left = dict(left or {})
        changes, summaries, dropped, unscheduled = [], [], [], []
        for d in days:
            ch, summary, dr, un = plan_days(backend, [d], routine, categories, events, notes, rules, now,
                                            health, history, expect, attempts, tasks=tasks, left=left,
                                            few_shot=few_shot)
            changes += ch
            dropped += dr
            unscheduled += un
            if summary:
                summaries.append(summary)
            for c in ch:
                if c.kind == "create" and c.new_start is not None:
                    history.setdefault(c.category, []).append(c.new_start.date())
                    if c.task_id in left:
                        left[c.task_id] -= minutes(c.new_start, c.new_end)
        return changes, " ".join(summaries), dropped, unscheduled
    planned = set(days)
    previous = [e for e in events if e.managed and e.start.date() in planned and e.start >= now]
    prompt = build_prompt(days, routine, categories, [e for e in events if e not in previous],
                          previous, now, health, tasks, left)
    request = prompt
    for attempt in range(attempts):
        plan = backend.plan_week(system_prompt(few_shot), request)
        creates, problems = validate(plan, days, categories, events, notes, rules, now, history, expect,
                                     tasks=tasks, left=left)
        if not problems or attempt == attempts - 1:
            return (diff(creates, previous), plan.summary, problems,
                    [f"{u.task_id}: {u.reason}" for u in plan.unscheduled])
        request = (prompt + "\n\n# Your previous answer\n" + plan.model_dump_json()
                   + "\n\n# It broke these rules - return the whole corrected plan\n"
                   + "\n".join(f"- {p}" for p in problems))
    raise AssertionError("unreachable")
