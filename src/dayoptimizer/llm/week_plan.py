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
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pydantic import BaseModel
from dayoptimizer.core.constraints import NoteRule, skippable, window_rule
from dayoptimizer.core.models import Event, PlannedChange, Task
from dayoptimizer.core.planner import _nearest_start
from dayoptimizer.llm.backend import LLMTimeout
from dayoptimizer.llm.task_rules import block_problem, minutes, overdue, task_lines, unplaced, window

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
    "- Return only the blocks you add. Events already in the calendar stay where they are: never copy "
    "them into blocks. Each day to plan lists its free time; every block goes inside it, unless a note "
    "lets you plan over an event.\n"
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
    "- Task blocks go into the free time left after the day's routine and events, or into a "
    "routine block of the task's own category (a Learn task in the routine's Learn time): the "
    "routine says when that kind of work happens, the task says what it is. Leave that part of the "
    "routine block out. Task blocks never overlap events or routine blocks of other categories. "
    "They start after 'not before' and end by the deadline. Never in a routine block marked (protected).\n"
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
    "\nExamples. A whole day first: Monday 2030-10-14, now 08:00, calendar "
    "- [e1] 09:00-12:00 Uni: Lecture, free: 08:00-09:00, 12:00-24:00; routine lunch 13:00-13:30 (Food) and "
    "sleep 23:00-24:00 (Sleep); task - [t5] Essay (Learn) 90 min left, due Mon 2030-10-14 20:00, in one "
    "piece, priority normal. The lecture is not copied; only new blocks come back:\n"
    '{"blocks":[{"day":"2030-10-14","start":"13:00","end":"13:30","category":"Food","title":"Lunch"},'
    '{"day":"2030-10-14","start":"14:00","end":"15:30","category":"Learn","title":"Essay","task_id":"t5"},'
    '{"day":"2030-10-14","start":"23:00","end":"24:00","category":"Sleep","title":"Sleep"}],'
    '"plan_over":[],"unscheduled":[]}\n'
    "Shorter ones (a real answer also has the rest of the day's plan):\n"
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


def free_gaps(day: date, events: list[Event], now: datetime) -> list[tuple[datetime, datetime]]:
    """The day's gaps from now on: what the user's events (and planner blocks
    already under way) leave free. A small model reads these far better than it
    works the gaps out from the event list itself."""
    midnight = datetime.combine(day, time(0)).astimezone()
    end = midnight + timedelta(days=1)
    cur = max(midnight, now)
    busy = sorted((max(e.start, midnight), min(e.end, end)) for e in events
                  if not e.all_day and (not e.managed or e.start < now) and e.start < end and e.end > midnight)
    gaps = []
    for s, e in busy:
        if s > cur:
            gaps.append((cur, s))
        cur = max(cur, e)
    if cur < end:
        gaps.append((cur, end))
    return gaps


def _spans(day: date, gaps: list[tuple[datetime, datetime]]) -> str:
    midnight = datetime.combine(day, time(0)).astimezone()

    def clock(t: datetime) -> str:
        m = minutes(midnight, t)
        return f"{m // 60:02d}:{m % 60:02d}"
    return ", ".join(f"{clock(a)}-{clock(b)}" for a, b in gaps)


def free_time(day: date, events: list[Event], now: datetime) -> str:
    return _spans(day, free_gaps(day, events, now)) or "none"


Reserved = dict  # date -> [(start, end, name, category)]: routine time tasks stay out of (category None: all tasks)


def routine_spans(typical_week: dict, categories: dict, days: list[date]) -> tuple[dict, Reserved]:
    """The routine of each day as spans (start, end, category, title, fixed,
    protected), and the part of it tasks stay out of: fixed routine keeps out
    tasks of other categories, a protected block (category None) every task."""
    routine_days = {d: [(datetime.combine(d, time(0)).astimezone() + timedelta(minutes=b.start),
                         datetime.combine(d, time(0)).astimezone() + timedelta(minutes=b.end),
                         b.category, b.title or b.category,
                         not getattr(categories.get(b.category), "movable", True),
                         getattr(b, "protected", False))
                        for b in typical_week.get(d.weekday(), [])]
                    for d in days}
    reserved = {d: [(s, e, title, None if kept else cat) for s, e, cat, title, fixed, kept in spans if fixed or kept]
                for d, spans in routine_days.items()}
    return routine_days, reserved


def _guarded(span) -> bool:
    """A routine span (start, end, category, title, fixed[, protected]) the user protected from tasks."""
    return span[5:6] == (True,)


def _reserved_events(reserved: Reserved | None, category: str | None = None) -> list[Event]:
    """Fixed routine time as busy events. With `category`, that category's own
    routine time is left out: a task may take its category's routine slot."""
    return [Event(id=f"reserved-{i}", calendar="reserved", title=x[2], start=x[0], end=x[1])
            for i, x in enumerate(x for spans in (reserved or {}).values() for x in spans)
            if category is None or x[3:4] != (category,)]


def _fits(tasks: list[Task], days: list[date], events: list[Event], now: datetime,
          left: dict[str, int], reserved: Reserved | None = None) -> dict[str, str]:
    """Where each task's window meets free time long enough for one of its
    blocks (a whole chunk, or the whole task when it can't be split), outside
    the user's fixed routine (sleep, ...) of other categories."""
    out = {}
    for t in tasks:
        busy = list(events) + _reserved_events(reserved, t.category)
        gaps = {d: free_gaps(d, busy, now) for d in days}
        n = left.get(t.id, 0)
        need = min(t.min_chunk_min, n) if t.min_chunk_min else n
        lo, hi = window(t, now)
        parts = []
        for d in days:
            spans = [(max(a, lo), b if hi is None else min(b, hi)) for a, b in gaps[d]]
            spans = [(a, b) for a, b in spans if b > a and minutes(a, b) >= need]
            if spans:
                parts.append(f"{DAY_NAMES[d.weekday()][:3]} {_spans(d, spans)}")
        out[t.id] = "; ".join(parts) or NOWHERE
    return out


NOWHERE = "nowhere in the days you plan"


def _shown(tasks: list[Task], days: list[date], events: list[Event], now: datetime,
           left: dict[str, int], reserved: Reserved | None = None) -> list[Task]:
    """Tasks the model should see for these days: ones it can work on, plus
    ones due within them (so it reports them when they don't fit). A task that
    can only start later is left out, or a small model places it anyway."""
    fits = _fits(tasks, days, events, now, left, reserved)
    return [t for t in tasks if left.get(t.id, 0) > 0 and (
        fits[t.id] != NOWHERE or overdue(t, now) or (t.due is not None and t.due.date() <= max(days)))]


def _fmt(ev: Event) -> str:
    return f"{ev.start:%H:%M}-{ev.end:%H:%M}"


def build_prompt(days: list[date], routine: str, categories: list[str], events: list[Event],
                 previous: list[Event], now: datetime, health: str | None = None,
                 tasks: list[Task] = (), left: dict[str, int] | None = None,
                 busy: list[Event] = (), reserved: Reserved | None = None,
                 routine_days: dict | None = None, rules: list[NoteRule] = ()) -> str:
    """Everything the model needs, grouped by day so it reads like a calendar.
    `busy`: blocks already accepted this round; they take free time but are
    not listed as calendar events. Events the notes let us plan over are
    listed but don't take free time."""
    taken = [e for e in list(events) + list(busy) if not skippable(list(rules), e)]
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
        if d in days:
            lines.append(f"- free: {free_time(d, taken, now)}")
            if routine_days and routine_days.get(d):
                lines.append("- routine: " + ", ".join(
                    f"{_spans(d, [(s, e)])} {cat}: {title}" + (" (fixed)" if x[4] else "")
                    + (" (protected)" if _guarded(x) else "")
                    for x in routine_days[d] for s, e, cat, title in [x[:4]]))
        for e in mine:
            where = f" @ {e.location}" if e.location else ""
            lines.append(f"- [{e.id}] {_fmt(e)} {e.calendar}: {e.title}{where}")
        for e in prev:
            lines.append(f"- (your previous plan) {_fmt(e)} {e.calendar}: {e.title}")
        if not mine and not prev:
            lines.append("- nothing")
        d += timedelta(days=1)
    visible = _shown(list(tasks), days, taken, now, left or {}, reserved)
    pending = task_lines(visible, left or {}, now, _fits(visible, days, taken, now, left or {}, reserved))
    if pending:
        lines += ["", "# Tasks"] + pending
    return "\n".join(lines)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[\"“”„'‘’]", "", text).lower().split())


def plan_schema(categories: list[str], days: list[date], task_ids: list[str], notes: str,
                events: list[Event], rules: list[NoteRule] = ()) -> dict:
    """The answer's JSON schema with every closed choice spelled out, so a model
    with constrained output (Ollama) can't invent categories, days, tasks,
    events or note sentences; validate still checks everything. plan_over only
    offers events a compiled note lets the planner plan over: offered every
    event, a small model lists them over and over until its answer is cut off."""
    s = WeekPlan.model_json_schema()
    defs, props = s["$defs"], s["properties"]
    block = defs["Block"]["properties"]
    block["category"]["enum"] = list(categories)
    block["day"]["enum"] = [d.isoformat() for d in days]
    block["task_id"] = ({"anyOf": [{"enum": list(task_ids)}, {"type": "null"}], "default": None}
                        if task_ids else {"type": "null", "default": None})
    planned = set(days)
    ids = [e.id for e in events if not e.managed and not e.all_day and e.start.date() in planned
           and skippable(list(rules), e)]
    props["blocks"]["maxItems"] = 30 * len(days)
    # capped free text: a small model otherwise writes a summary until its answer is cut off
    props["summary"]["maxLength"] = 300
    block["why"]["maxLength"] = 80
    block["title"]["maxLength"] = 60
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", notes or "") if len(_norm(x)) >= 10]
    if ids and sentences:
        defs["PlanOver"]["properties"]["event_id"]["enum"] = ids
        defs["PlanOver"]["properties"]["note"]["enum"] = sentences
        props["plan_over"]["maxItems"] = len(ids)
    else:
        props["plan_over"]["maxItems"] = 0
    if task_ids:
        defs["Unscheduled"]["properties"]["task_id"]["enum"] = list(task_ids)
    else:
        props["unscheduled"]["maxItems"] = 0
    return s


def validate(plan: WeekPlan, days: list[date], categories: list[str], events: list[Event],
             notes: str, rules: list[NoteRule], now: datetime,
             history: dict[str, list[date]] | None = None,
             expect: set[date] | frozenset[date] = frozenset(),
             tasks: list[Task] = (), left: dict[str, int] | None = None,
             report_unplaced: bool = False, reserved: Reserved | None = None,
             routine_days: dict | None = None, fill_until: date | None = None,
             pushed: dict[str, int] | None = None) -> tuple[list[PlannedChange], list[str]]:
    """The blocks that keep every rule, as creates, and what was wrong with the rest.
    A day in `expect` (its routine has blocks) that comes back empty is a problem too.
    On a day with a routine, a block that is neither a task, a routine block nor
    in a category the notes count is dropped quietly, and a routine block is cut
    to its usual length: small models pad free time with made-up blocks.
    With `fill_until`, task minutes the model left out are placed by code (see `_fill`);
    `pushed` is what each task had on these days before the replan."""
    problems: list[str] = []
    wanted = {d.isoformat(): d for d in days}
    note_text = _norm(notes)
    over = {p.event_id for p in plan.plan_over
            if len(_norm(p.note)) >= 10 and _norm(p.note) in note_text}
    for p in plan.plan_over:
        if p.event_id not in over:
            problems.append(f"plan_over {p.event_id}: \"{p.note}\" is not a sentence from the notes")
    # a planner block already under way stays in the calendar, so it blocks like the user's events;
    # one the notes let us plan over doesn't, whether or not the model listed it
    blocking = [e for e in events if not e.all_day and (not e.managed or e.start < now) and e.id not in over
                and not skippable(rules, e)]
    by_id = {t.id: t for t in tasks}
    left = dict(left or {})
    running = dict(left)
    kept: list[tuple[datetime, datetime, Block]] = []
    open_by_name = {(t.category, t.title.strip().casefold()): t.id for t in tasks if not t.done}
    fixed = [x for spans in (reserved or {}).values() for x in spans]
    counted = {r.category for r in rules if r.type in ("max_per_week", "min_gap_days")}
    for b in sorted(plan.blocks, key=lambda b: (b.day, b.start)):
        if b.task_id is None and (b.category, b.title.strip().casefold()) in open_by_name:
            # a block named like an open task is that task's work, so it counts toward it
            b = b.model_copy(update={"task_id": open_by_name[(b.category, b.title.strip().casefold())]})
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
        usual = [minutes(rs, re_) for rs, re_, cat, title, *_ in (routine_days or {}).get(day, [])
                 if cat == b.category and title.strip().casefold() == b.title.strip().casefold()]
        # a commute: right before or after an event at a place
        trip = any(e.location and (e.start == end or e.end == start) for e in blocking)
        if b.task_id is None and (routine_days or {}).get(day) and b.category not in counted and not trip:
            same = sum(1 for _, _, k in kept if k.task_id is None and k.category == b.category
                       and k.title.strip().casefold() == b.title.strip().casefold() and k.day == b.day)
            if not usual or same >= len(usual):
                continue  # made up, or a second copy of a routine block the day already has
            if minutes(start, end) > max(usual):
                end = start + timedelta(minutes=max(usual))
                b = b.model_copy(update={"end": f"{(start_m + max(usual)) // 60:02d}:{(start_m + max(usual)) % 60:02d}"})
        have = running.get(b.task_id, 0) if b.task_id is not None else 0
        if b.task_id in by_id and not by_id[b.task_id].done and have <= 0:
            continue  # the task is already placed in full: a surplus block is noise, not a problem
        if 0 < have < minutes(start, end):
            # a task block longer than what is left is cut, not refused: small models miscount
            end = start + timedelta(minutes=have)
            b = b.model_copy(update={"end": f"{(start_m + have) // 60:02d}:{(start_m + have) % 60:02d}"})
        clash = next((e for e in blocking if e.start < end and e.end > start), None)
        if clash is not None:
            problems.append(f"{label}: overlaps '{clash.title}' ({_fmt(clash)}) [{clash.id}]")
            continue
        twin = next((k for k in kept if k[0] < end and k[1] > start and not _shares_slot(k[2], b)), None)
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
            quiet = next((x for x in fixed if x[0] < end and x[1] > start and x[3:4] != (b.category,)), None)
            if quiet is not None:
                problems.append(f"{label}: task {b.task_id} falls in your {'protected' if quiet[3:4] == (None,) else 'fixed'} routine '{quiet[2]}' "
                                f"({quiet[0]:%H:%M}-{quiet[1]:%H:%M})")
                continue
            running[b.task_id] -= minutes(start, end)
        kept.append((start, end, b))
    kept, count_problems = _count_rules(kept, rules, history or {})
    problems += count_problems

    def leftover():
        used: dict[str, int] = {}
        for s, e, b in kept:
            if b.task_id is not None:
                used[b.task_id] = used.get(b.task_id, 0) + minutes(s, e)
        return {tid: n - used.get(tid, 0) for tid, n in left.items()}
    after = leftover()
    if fill_until is not None:
        # a flexible, unprotected routine block may move to open a gap for a task
        flexible = {(d.isoformat(), x[2], x[3].strip().casefold()) for d, spans in (routine_days or {}).items()
                    for x in spans if not x[4] and not _guarded(x)}
        taken = blocking + [Event(id=f"kept:{i}" if b.task_id is None and (b.day, b.category, b.title.strip().casefold())
                                  in flexible else "kept", calendar=b.category, title=b.title, start=s, end=e,
                                  task_id=b.task_id) for i, (s, e, b) in enumerate(kept)]
        seen = {c: list(ds) for c, ds in (history or {}).items()}
        for s, _, b in kept:
            seen.setdefault(b.category, []).append(s.date())
        filled, moved, ruled = _fill(list(tasks), after, days, fill_until, taken, rules, now,
                                     routine_days or {}, pushed or {}, reserved, seen)
        for i, (s, e) in moved.items():
            b = kept[i][2]
            kept[i] = (s, e, b.model_copy(update={"start": f"{s:%H:%M}", "end": _spans(s.date(), [(s, e)]).split("-")[1],
                                                  "why": "moved to make room for a task"}))
        # code's blocks keep the weekly notes too; one that breaks them is just not placed
        kept, _ = _count_rules(kept + filled, rules, history or {})
        after = leftover()
    else:
        ruled = {}
    listed = {u.task_id for u in plan.unscheduled}
    problems += [f"unscheduled {u.task_id}: not one of the tasks" for u in plan.unscheduled if u.task_id not in by_id]
    if not report_unplaced:
        problems += unplaced(list(tasks), after, listed, max(days), now)
    else:
        # last round: what the model still didn't fit is reported by code, not left silent
        for t in tasks:
            if unplaced([t], after, listed, max(days), now):
                why = (f"'{t.title}' is overdue and {after[t.id]} min of it don't fit in the planned days"
                       if overdue(t, now) else
                       f"'{t.title}': your note {ruled[t.id]} rules it out before {t.due:%a %Y-%m-%d %H:%M}"
                       if t.id in ruled else
                       f"'{t.title}' doesn't fit before {t.due:%a %Y-%m-%d %H:%M} - missing {after[t.id]} min")
                plan.unscheduled.append(Unscheduled(task_id=t.id, reason=why))
    filled = {s.date() for s, _, _ in kept}
    problems += [f"{d.isoformat()}: no blocks planned for this day - return its full plan"
                 for d in sorted(expect) if d in wanted.values() and d not in filled
                 and datetime.combine(d, time(23, 59)).astimezone() > now]
    kept = _yield_to_tasks(kept)
    changes = [PlannedChange(kind="create", category=b.category, title=b.title, reason=b.why or "planned",
                             new_start=s, new_end=e, task_id=b.task_id) for s, e, b in kept]
    return changes, problems


def _shares_slot(a: Block, b: Block) -> bool:
    """A task block and a routine block of the same category may overlap: the
    task fills that routine time, and the routine block yields (_yield_to_tasks)."""
    return a.category == b.category and (a.task_id is None) != (b.task_id is None)


def _yield_to_tasks(kept: list[tuple[datetime, datetime, Block]]) -> list[tuple[datetime, datetime, Block]]:
    """Cut each non-task block around the task blocks of its category; pieces
    under 15 minutes go."""
    out = []
    for s, e, b in kept:
        if b.task_id is not None:
            out.append((s, e, b))
            continue
        pieces = [(s, e)]
        for ts, te, t in kept:
            if t.task_id is not None and t.category == b.category:
                pieces = [x for a, z in pieces for x in ((a, min(z, ts)), (max(a, te), z)) if x[1] > x[0]]
        for a, z in pieces:
            if minutes(a, z) >= 15:
                d = date.fromisoformat(b.day)
                out.append((a, z, b if (a, z) == (s, e) else
                            b.model_copy(update={"start": f"{a:%H:%M}", "end": _spans(d, [(a, z)]).split("-")[1]})))
    return out


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


def _block_key(b: Block):
    start = _hhmm(b.start)
    return b.day, start, b.category, b.title, b.task_id


def _change_key(c: PlannedChange):
    midnight = datetime.combine(c.new_start.date(), time(0)).astimezone()
    return c.new_start.date().isoformat(), minutes(midnight, c.new_start), c.category, c.title, c.task_id


def _as_block(e: Event) -> Block:
    end = f"{e.end:%H:%M}" if e.end.date() == e.start.date() else "24:00"
    return Block(day=e.start.date().isoformat(), start=f"{e.start:%H:%M}", end=end, category=e.calendar,
                 title=e.title, task_id=e.task_id)


def _unmentioned(blocks: list[Block], previous: list[Event], events: list[Event], now: datetime) -> list[Block]:
    """Old planner blocks a small model left out of its answer, kept as they
    are: it tends to return only what it changed, and deleting the rest would
    wipe sleep and meals. An old block goes only when the answer moves it (a
    block of the same name, or of the same task, that day) or something now
    overlaps it."""
    when = {}
    for b in blocks:
        s, e = _hhmm(b.start), _hhmm(b.end)
        if s is not None and e is not None:
            midnight = datetime.combine(date.fromisoformat(b.day), time(0)).astimezone()
            when[id(b)] = (midnight + timedelta(minutes=s), midnight + timedelta(minutes=e if e else 1440))
    names = {(b.day, b.task_id or (b.category, b.title)) for b in blocks}
    taken = [w for w in when.values()] + [(e.start, e.end) for e in events
                                          if not e.all_day and (not e.managed or e.start < now)]
    keep = []
    for e in previous:
        if (e.start.date().isoformat(), e.task_id or (e.calendar, e.title)) in names:
            continue
        if any(s < e.end and t > e.start for s, t in taken):
            continue
        keep.append(_as_block(e))
    return keep


def _times(b: Block) -> tuple[datetime, datetime] | None:
    s, e = _hhmm(b.start), _hhmm(b.end)
    if s is None or e is None:
        return None
    midnight = datetime.combine(date.fromisoformat(b.day), time(0)).astimezone()
    return midnight + timedelta(minutes=s), midnight + timedelta(minutes=e if e else 1440)


def _forgotten_routine(blocks: list[Block], routine_days: dict, events: list[Event],
                       now: datetime) -> tuple[list[Block], list[str]]:
    """Routine blocks a small model left out. A fixed one (sleep, ...) goes
    back at its usual time where nothing else is; a movable one (a meal) at
    the free time nearest its usual time, up to two hours either way. A
    protected one ignores task blocks (they will be refused there). Returns
    the blocks and a note for each one that found no room (one per day for three or more)."""
    busy = [(e.start, e.end) for e in events if not e.all_day and (not e.managed or e.start < now)]
    # a block the model placed on top of an event will be refused, so it is neither there nor in the way
    placed = [(b, t) for b, t in ((b, _times(b)) for b in blocks)
              if t and not any(x < t[1] and y > t[0] for x, y in busy)]
    have = [(b.day, b.category, b.title, t[0]) for b, t in placed]
    taken = [(*t, b.task_id and b.category) for b, t in placed] + [(*t, None) for t in busy]
    out, lost = [], []
    for d, spans in (routine_days or {}).items():
        # fixed blocks first (they can't move), then ones still ahead: a missed
        # breakfast moved later must not push a block that is on time
        for span in sorted(spans, key=lambda x: (not x[4], x[0] < now)):
            s, e, cat, title, fixed = span[:5]
            if any(h[:3] == (d.isoformat(), cat, title) and abs(h[3] - s) <= timedelta(hours=2) for h in have):
                continue
            day_end = datetime.combine(d, time(0)).astimezone() + timedelta(days=1)
            shifts = [0] if fixed else [0] + [m for k in range(15, 121, 15) for m in (-k, k)]
            for m in shifts:
                a, b = s + timedelta(minutes=m), e + timedelta(minutes=m)
                if a >= now and a.date() == d and b <= day_end and not any(
                        x < b and y > a and not (task and (_guarded(span) or task == cat)) for x, y, task in taken):
                    break
            else:
                if s >= now:
                    lost.append((d, s, title, f"{d:%a} {_spans(d, [(s, e)])} {cat}: {title}: no free time near its usual time"))
                continue
            taken.append((a, b, None))
            out.append(Block(day=d.isoformat(), start=f"{a:%H:%M}", end=_spans(d, [(a, b)]).split("-")[1],
                             category=cat, title=title))
    lost.sort(key=lambda x: x[1])
    days = [d for d, *_ in lost]  # a day that lost three or more gets one line, not one each
    return out, [line for d, _, _, line in lost if days.count(d) < 3] + [
        f"{d:%a}: {', '.join(dict.fromkeys(t for x, _, t, _ in lost if x == d))} - no time left around events"
        for d in dict.fromkeys(days) if days.count(d) >= 3]


def _fill(tasks: list[Task], after: dict[str, int], days: list[date], fill_until: date, taken: list[Event],
          rules: list[NoteRule], now: datetime, routine_days: dict, pushed: dict[str, int],
          reserved: Reserved | None = None, seen: dict[str, list[date]] | None = None
          ) -> tuple[list[tuple[datetime, datetime, Block]], dict, dict]:
    """Task minutes the model left out, placed by code in the earliest free time
    that keeps the task's chunks and the notes (on each day the routine time of
    the task's own category first), only on days with a routine (so sleep is
    known). All of them when the deadline falls within the run (its last
    chance) or there is none (as soon as possible); otherwise only what the task had on these days before the
    replan (`pushed`): a replan must not lose task time, but code should not
    pile later work onto today. Routine time of the task's own category counts
    as free (the routine block yields to the task).
    A day with no gap long enough gets one made before the next day is tried:
    blocks in `taken` with an id "kept:<n>" (flexible, unprotected routine)
    move to the nearest free time that day. Tasks are never split for it.
    Returns the task blocks, the moves, {n: (start, end)}, and the note that
    kept a task out of a day, {task id: '"source"'}."""
    out, moved, ruled = [], {}, {}
    taken = list(taken)
    seen = seen if seen is not None else {}
    for t in sorted((t for t in tasks if not t.done),
                    key=lambda t: (t.due is None, t.due or now)):
        need = after.get(t.id, 0)
        if t.due is not None and t.due.date() > fill_until:
            need = min(need, pushed.get(t.id, 0))
        last = min(t.due.date(), fill_until) if t.due and not overdue(t, now) else max(days)  # overdue: now
        if need <= 0:
            continue
        lo, hi = window(t, now)

        def place(d, a, n):
            nonlocal need
            end = a + timedelta(minutes=n)
            out.append((a, end, Block(day=d.isoformat(), start=f"{a:%H:%M}", end=_spans(d, [(a, end)]).split("-")[1],
                                      category=t.category, title=t.title, task_id=t.id, why="placed by code")))
            taken.append(Event(id="filled", calendar=t.category, title=t.title, start=a, end=end))
            seen.setdefault(t.category, []).append(d)
            need -= n
            return end

        def busy():
            return [e for e in taken if not (e.id.startswith("kept") and e.task_id is None
                                             and e.calendar == t.category)] + _reserved_events(reserved, t.category)

        if last > max(days):  # due on a later day of the run (planned one day at a time)
            chunk = min(t.min_chunk_min or t.duration_min, need)
            later = [max(days) + timedelta(days=k) for k in range(1, (last - max(days)).days + 1)]
            room = sum(n for d in later if routine_days.get(d)
                       for a, b in free_gaps(d, busy() + [Event(id="routine", calendar=x[2], title=x[3], start=x[0],
                                                                end=x[1]) for x in routine_days[d]
                                                          if x[2] != t.category or _guarded(x)], now)
                       if (n := minutes(max(a, lo), b if hi is None else min(b, hi))) >= chunk)
            need -= min(need, room)  # what the later days can take, their plans place
            if need <= 0:
                continue
            last = max(days)  # the rest goes now
        if last not in days:
            continue

        for d in sorted(x for x in days if x <= last and routine_days.get(x)):
            midnight = datetime.combine(d, time(0)).astimezone()
            if broken := _count_rules([(midnight, midnight, Block(day=d.isoformat(), start="00:00", end="00:00",
                                                                  category=t.category, title=""))], rules, seen)[1]:
                ruled[t.id] = broken[0].split("breaks the note ", 1)[1]
                continue  # a weekly note rules the category out that day: don't move anything for it
            # twice: the short last piece may fit a gap the full chunk skipped
            for own_slot in (True, False, True, False):
                gaps = free_gaps(d, busy(), now)
                if own_slot:  # the day's routine time of the task's category first, then any free time
                    spans = [(s, e) for s, e, cat, *_ in routine_days[d] if cat == t.category]
                    gaps = [(max(a, s), min(b, e)) for a, b in gaps for s, e in spans if min(b, e) > max(a, s)]
                for a, b in gaps:
                    a, b = max(a, lo), b if hi is None else min(b, hi)
                    while need > 0 and minutes(a, b) >= (chunk := min(t.min_chunk_min or t.duration_min, need)):
                        s_m = minutes(midnight, a)
                        # the longest piece from here the notes allow (a "not after" cuts it short)
                        n = next((n for n in range(min(need, minutes(a, b)), chunk - 1, -15)
                                  if window_rule(rules, t.category, s_m, s_m + n, d.weekday()) is None), None)
                        if n is None:
                            a += timedelta(minutes=15)
                            continue
                        a = place(d, a, n)
            while need > 0 and (room := _make_room(d, min(t.min_chunk_min or t.duration_min, need), t.category,
                                                   lo, hi, busy(), rules, now, taken + _reserved_events(reserved))):
                a, shifts = room
                for e, s, z in shifts:
                    taken = [replace(x, start=s, end=z) if x.id == e.id else x for x in taken]
                    moved[int(e.id.split(":")[1])] = (s, z)
                place(d, a, min(t.min_chunk_min or t.duration_min, need))
            if need <= 0:
                break
    return out, moved, ruled


def _make_room(d: date, n: int, category: str, lo: datetime, hi: datetime | None, busy: list[Event],
               rules: list[NoteRule], now: datetime, everything: list[Event]):
    """The earliest start for an n-minute block on day d that is blocked only
    by movable blocks (id "kept:<n>") in `busy`, each of which fits elsewhere
    that day, nearest its time (3 hours away at most) and clear of `everything`
    (all blocks and reserved time), keeping the notes: (start, [(event, new start, new end)]) or None."""
    midnight = datetime.combine(d, time(0)).astimezone()
    day_end = midnight + timedelta(days=1)
    a = max(lo, now, midnight)
    a += timedelta(minutes=-minutes(midnight, a) % 15)
    while a + timedelta(minutes=n) <= (day_end if hi is None else min(hi, day_end)):
        b = a + timedelta(minutes=n)
        way = [e for e in busy if e.start < b and e.end > a]
        if way and all(e.id.startswith("kept:") for e in way) and window_rule(
                rules, category, minutes(midnight, a), minutes(midnight, b), d.weekday()) is None:
            rest = [e for e in everything if e not in way] + [Event(id="new", calendar=category, title="", start=a, end=b)]
            shifts = []
            for e in way:
                # ponytail: 3h from its usual time at most (lunch at 19:00 is no lunch); per-category reach if it bites
                far = timedelta(hours=3)
                s = _nearest_start(rest, e.start, e.end - e.start, max(now, midnight, e.start - far),
                                   min(day_end, e.end + far))
                if s is None or window_rule(rules, e.calendar, minutes(midnight, s),
                                            minutes(midnight, s + (e.end - e.start)), d.weekday()) is not None:
                    break
                shifts.append((e, s, s + (e.end - e.start)))
                rest.append(replace(e, start=s, end=s + (e.end - e.start)))
            else:
                return a, shifts
        a += timedelta(minutes=15)
    return None


SLOTS_SYSTEM = (
    "You help plan one day in a person's calendar. Code has laid out their routine and found the free "
    "times. For each item choose one of its slots, copied exactly, and say why in a few words. Choose as the "
    "person would: overdue work and near deadlines first, higher priority earlier, work in the hours their "
    "routine gives that kind of work, and follow their notes. 'later' leaves a task for another day; take it "
    "only when the deadline allows. Two items must not take overlapping slots."
)


def slot_items(day: date, events: list[Event], now: datetime, tasks: list[Task], left: dict[str, int],
               routine_days: dict, rules: list[NoteRule], with_routine: bool = True) -> dict[str, tuple[str, dict]]:
    """What a small model chooses for a day, with up to five legal slots each:
    every open task (one block of it; code places the rest), and every flexible
    routine block an event pushed out of its usual time. {key: (line, {"HH:MM-HH:MM": Block})}"""
    midnight = datetime.combine(day, time(0)).astimezone()
    blocking = [e for e in events if not skippable(rules, e)]
    spans = routine_days.get(day, [])

    def span_event(x):
        return Event(id="routine", calendar=x[2], title=x[3], start=x[0], end=x[1])
    items = {}
    for t in tasks:
        n = left.get(t.id, 0)
        lo, hi = window(t, now)
        if t.done or n <= 0 or lo.date() > day or (hi is not None and hi <= midnight):
            continue
        chunk = min(t.min_chunk_min or n, n)
        size = min(n, max(chunk, 180))  # one block of at most ~3 hours; _fill places the rest when it must
        busy = blocking + [span_event(x) for x in spans if x[2] != t.category or _guarded(x)]
        own = [(x[0], x[1]) for x in spans if x[2] == t.category]
        gaps = sorted(((max(a, lo), b if hi is None else min(b, hi)) for a, b in free_gaps(day, busy, now)),
                      key=lambda g: (not any(s < g[1] and e > g[0] for s, e in own), g[0]))
        starts: list[list] = []
        for a, b in gaps:
            a += timedelta(minutes=-minutes(midnight, a) % 15)
            mine = []
            while minutes(a, b) >= chunk:
                length = min(size, minutes(a, b))
                s_m = minutes(midnight, a)
                if window_rule(rules, t.category, s_m, s_m + length, day.weekday()) is None:
                    mine.append((a, a + timedelta(minutes=length)))
                a += timedelta(minutes=max(length, 60))
            starts.append(mine)
        picked = [x for k in range(3) for mine in starts for x in mine[k:k + 1]][:5]  # each gap's first start first
        slots = {_spans(day, [(a, b)]): Block(day=day.isoformat(), start=f"{a:%H:%M}",
                                              end=_spans(day, [(a, b)]).split("-")[1], category=t.category,
                                              title=t.title, task_id=t.id) for a, b in sorted(picked)}
        if t.due is not None and not overdue(t, now) and t.due.date() > day:
            slots["later"] = None
        if slots:
            items[t.id] = (task_lines([t], left, now)[0], slots)
    for x in spans if with_routine else []:
        s, e, cat, title, fixed = x[:5]
        if fixed or s < now or not any(b.start < e and b.end > s for b in blocking if not b.all_day
                                       and (not b.managed or b.start < now)):
            continue
        others = blocking + [span_event(y) for y in spans if y is not x]
        free = free_gaps(day, others, now)
        moves = sorted((m for m in range(-120, 121, 15)), key=abs)
        fits = [(s + timedelta(minutes=m), e + timedelta(minutes=m)) for m in moves]
        fits = [(a, b) for a, b in fits if any(g <= a and b <= h for g, h in free)
                and window_rule(rules, cat, minutes(midnight, a), minutes(midnight, b), day.weekday()) is None][:5]
        if fits:
            key = f"{cat}: {title} (usually {_spans(day, [(s, e)])})"
            items[key] = (f"- [{key}] routine block an event pushed out of its usual time",
                          {_spans(day, [(a, b)]): Block(day=day.isoformat(), start=f"{a:%H:%M}",
                                                        end=_spans(day, [(a, b)]).split("-")[1], category=cat,
                                                        title=title, why="moved around an event")
                           for a, b in sorted(fits)})
    return items


def _choose(backend, day: date, items: dict, routine: str, events: list[Event], now: datetime) -> WeekPlan:
    """A small model picks one slot per item; the picks become the plan's blocks."""
    cal = [f"- {_fmt(e)} {e.calendar}: {e.title}" for e in sorted(events, key=lambda e: e.start)
           if e.start.date() == day and not e.all_day]
    prompt = "\n".join([f"Now: {DAY_NAMES[now.weekday()]} {now:%Y-%m-%d %H:%M}",
                        f"Plan: {DAY_NAMES[day.weekday()]} {day.isoformat()}", "", routine.strip(), "",
                        "# Calendar that day"] + (cal or ["- nothing"]) + ["", "# Choose a slot for each"]
                       + [f"{line}; slots: {', '.join(slots)}" for line, slots in items.values()])
    schema = {"type": "object", "required": list(items), "properties": {
        k: {"type": "object", "required": ["slot", "why"], "properties": {
            "slot": {"type": "string", "enum": list(slots)}, "why": {"type": "string", "maxLength": 60}}}
        for k, (_, slots) in items.items()}}
    answer = backend.choose(SLOTS_SYSTEM, prompt, schema)
    blocks = []
    for k, (_, slots) in items.items():
        pick = answer.get(k) or {}
        b = slots.get(pick.get("slot"))
        if b is not None:
            blocks.append(b.model_copy(update={"why": str(pick.get("why") or b.why)[:80]}))
    return WeekPlan(blocks=blocks)


def _plan_once(backend, days, routine, categories, events, notes, rules, now, health, history, expect,
               attempts, tasks, left, few_shot, reserved=None, routine_days=None, fill_until=None):
    """One request (plus corrections) for these days. A correction keeps the
    blocks that passed and asks only for the rest: a small model asked to redo
    the whole day tends to break what was already right. Returns the validated
    blocks, the calendar changes (blocks already in place are not repeated),
    the summary, what was dropped and the tasks that did not fit."""
    planned = set(days)
    previous = [e for e in events if e.managed and e.start.date() in planned and e.start >= now]
    shown = [e for e in events if e not in previous]
    pushed: dict[str, int] = {}
    for e in previous:
        if e.task_id:
            pushed[e.task_id] = pushed.get(e.task_id, 0) + minutes(e.start, e.end)
    small = getattr(backend, "one_day_at_a_time", False)
    all_routine = routine_days or {}  # code filling a task looks at the later days too
    routine_days = {d: v for d, v in all_routine.items() if d in planned}
    prompt = build_prompt(days, routine, categories, shown, previous, now, health, tasks, left, reserved=reserved,
                          routine_days=routine_days, rules=rules)
    open_ids = [t.id for t in _shown(list(tasks), days, [e for e in shown if not skippable(rules, e)], now,
                                     left or {}, reserved)]
    schema = plan_schema(categories, days, open_ids, notes, events, rules)
    note_text = _norm(notes)
    good: list[Block] = []
    over: list[PlanOver] = []
    request = prompt
    lost: list[str] = []
    slots = getattr(backend, "slots", False)  # the model only picks among slots code found (slot_items)
    placed, still, items = [], dict(left or {}), None
    for attempt in range(attempts):
        if slots:
            items = slot_items(days[0], shown + placed, now, list(tasks), still, routine_days, rules, not good)
            answer = _choose(backend, days[0], items, routine, shown, now) if items else WeekPlan()
        else:
            answer = backend.plan_week(system_prompt(few_shot), request, schema)
        blocks = good + answer.blocks
        if small and not good:
            blocks += _unmentioned(answer.blocks, previous, events, now)
            back, lost = _forgotten_routine(blocks, routine_days, [e for e in events if not skippable(rules, e)], now)
            blocks += back
        plan = WeekPlan(blocks=blocks, plan_over=over + answer.plan_over,
                        unscheduled=answer.unscheduled, summary=answer.summary)
        last = attempt == attempts - 1 or (slots and not items)  # nothing left to choose: another round can't help
        creates, problems = validate(plan, days, categories, events, notes, rules, now, history, expect,
                                     tasks=tasks, left=left, report_unplaced=last, reserved=reserved,
                                     routine_days=all_routine, fill_until=fill_until, pushed=pushed)
        if not problems or last:
            return (creates, diff(creates, previous), plan.summary, problems + lost,
                    [f"{u.task_id}: {u.reason}" for u in plan.unscheduled])
        accepted = {_change_key(c) for c in creates}
        good = [b for b in plan.blocks if _block_key(b) in accepted]
        over = [p for p in plan.plan_over if len(_norm(p.note)) >= 10 and _norm(p.note) in note_text]
        placed = [Event(id=f"placed-{i}", calendar=c.category, title=c.title, start=c.new_start, end=c.new_end)
                  for i, c in enumerate(creates)]
        still = dict(left or {})
        for c in creates:
            if c.task_id in still:
                still[c.task_id] -= minutes(c.new_start, c.new_end)
        request = (build_prompt(days, routine, categories, shown, previous, now, health, tasks, still, placed,
                                reserved, routine_days, rules)
                   + "\n\n# Already placed - they stay, do not return them again\n"
                   + "\n".join(f"- {b.day} {b.start}-{b.end} {b.category}: {b.title}" for b in good)
                   + "\n\n# Problems with the rest of your answer - return only the new blocks of the corrected plan\n"
                   + "\n".join(f"- {p}" for p in problems))
    raise AssertionError("unreachable")


def plan_days(backend, days: list[date], routine: str, categories: list[str], events: list[Event],
              notes: str, rules: list[NoteRule], now: datetime, health: str | None = None,
              history: dict[str, list[date]] | None = None, expect: set[date] | frozenset[date] = frozenset(),
              attempts: int = 3, tasks: list[Task] = (), left: dict[str, int] | None = None,
              few_shot: bool = True, reserved: Reserved | None = None,
              routine_days: dict | None = None) -> tuple[list[PlannedChange], str, list[str], list[str]]:
    """Ask, check, send the problems back; at most `attempts` rounds.
    Returns the calendar changes, the model's summary, what was dropped and the
    tasks it could not fit ("t2: reason").
    A small local model (`one_day_at_a_time`) gets one day per request; every
    block a day ends up with (new or kept as it was) counts toward the weekly
    limits and the task minutes of later days.
    A day with less than an hour left is not planned: asking a model about it
    only costs rounds; a task due that day is reported instead.
    When the small model fails on a day (too slow, broken answer) twice, that
    day alone is planned by code: its routine and its tasks (`_ByRule`)."""
    late = [d for d in days if datetime.combine(d + timedelta(days=1), time(0)).astimezone() - now < timedelta(hours=1)]
    days = [d for d in days if d not in late]
    left = dict(left or {})
    before = dict(left)
    unscheduled = [f"{t.id}: '{t.title}' is due today - no time left today" for t in tasks
                   if left.get(t.id, 0) > 0 and t.due is not None and t.due > now and t.due.date() in late]
    for u in unscheduled:
        left[u.split(":")[0]] = 0  # reported once; not again as unplaced on a later day
    if not days:
        return [], "", [], unscheduled
    small = getattr(backend, "one_day_at_a_time", False)
    history = {c: list(ds) for c, ds in (history or {}).items()}
    changes, summaries, dropped = [], [], []
    for group in [[d] for d in days] if small else [days]:
        def once(model, rounds=attempts):
            return _plan_once(model, group, routine, categories, events, notes, rules, now, health, history,
                              expect, rounds, tasks, left, few_shot, reserved, routine_days, max(days))
        result = failed = None
        for _ in range(2 if small else 1):
            try:
                result = once(backend)
                break
            except (LLMTimeout, ValueError) as exc:  # ValueError: an answer that isn't the plan's JSON
                if not small:
                    raise
                failed = exc
        if result is None:
            result = once(_ByRule(), 1)
            summaries.append(f"{group[0]:%a %Y-%m-%d} planned by rule: the model failed twice "
                             f"({' '.join(str(failed).split())[:100]}).")
        creates, ch, summary, dr, un = result
        changes += ch
        dropped += dr
        seen = {u.split(":")[0] for u in unscheduled}
        unscheduled += [u for u in un if u.split(":")[0] not in seen]  # one day at a time: report a task once
        if summary:
            summaries.append(summary)
        for c in creates:
            history.setdefault(c.category, []).append(c.new_start.date())
            if c.task_id in left:
                left[c.task_id] -= minutes(c.new_start, c.new_end)
    listed = {u.split(":")[0] for u in unscheduled}
    unscheduled += unplaced([t for t in tasks if t.due is None], left, listed, max(days), now, before)
    return changes, "\n".join(summaries), dropped, unscheduled


class _ByRule:
    """Stands in for a model that failed on a day: it adds nothing, so the day
    gets its routine back (`_forgotten_routine`) and its tasks (`_fill`) by code."""
    one_day_at_a_time = True

    def plan_week(self, system, prompt, schema=None):
        return WeekPlan()
