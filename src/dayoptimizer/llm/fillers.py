"""Suggestions for the free time a plan leaves.

After the plan is checked and written, the gaps of 30 minutes or more (outside
the usual time of the routine, see `routine_time`) on
today and tomorrow go to the language model, which may suggest something
healthy or productive for them (a walk, a book, a call). Code checks every
suggestion: inside a gap, 30-90 minutes, one of the user's categories, the
notes' rules, the day's minimum free time, variety, nothing the user deleted
lately. A suggestion is the lowest-priority block: the planner doesn't see
it, and one that something else now overlaps (or whose day falls short of its
minimum free time) is removed. A gap is offered
once a day (no new ideas every 15 minutes); the time of a suggestion the user
deleted stays free that day.
"""
from __future__ import annotations
import json
import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pydantic import BaseModel
from dayoptimizer.core.constraints import window_rule
from dayoptimizer.core.models import Event, PlannedChange
from dayoptimizer.llm.task_rules import minutes
from dayoptimizer.llm.week_plan import (Block, DAY_NAMES, _count_rules, _hhmm, _intent, _minus, _spans, free_gaps,
                                         routine_spans)

SHORTEST, LONGEST = 30, 90
TITLE_MAX, WHY_MAX = 40, 120
VARIETY_DAYS = {"low": 1, "medium": 3, "high": 7}  # a title comes back only this many days apart
AVOID_DAYS = 30  # a suggestion the user deleted isn't made again for this long


class Filler(BaseModel):
    day: str
    start: str
    end: str
    category: str
    title: str
    why: str = ""
    new_idea: bool = False


class Fillers(BaseModel):
    fillers: list[Filler] = []


SYSTEM = (
    "You suggest how a person could use the free gaps in their day. Their day is already planned; "
    "you get the gaps it left and may fill some of them with something healthy, restful or productive "
    "that suits them.\n"
    "- Each suggestion lies inside one listed gap and lasts 30 to 90 minutes: pick a natural length, the "
    "rest of the gap stays free. At most one suggestion per gap, and never more minutes in a day than "
    "that day allows. Leaving a gap free is fine.\n"
    "- Fit the person: their notes, routine and own events show what they like and need. Mornings suit "
    "focus and learning, afternoons movement, practice or errands, evenings rest and people. Simple ideas "
    "work: a walk, reading a book, the cinema, stretching, calling a friend, cooking something new, a "
    "short online course or tutorial, journaling.\n"
    "- Vary: don't repeat what was suggested lately, never suggest what they removed. Something they have "
    "never done is welcome: then set new_idea true. Never copy one of their own events or name a person: "
    "suggest something of its own (\"call a friend\", not a friend's name).\n"
    "- category: the one of their categories that fits best, spelled exactly. Keep their notes (limits "
    "on training, times).\n"
    "- title: a few words in the language of their notes (English when there are none). why: a few words."
)

_SUFFIX = re.compile(r"\s*\((sugestia|suggestion)\)\s*$", re.I)


def polish(notes: str) -> bool:
    """Are the notes in Polish? (the only language besides English the planner speaks)"""
    return bool(re.search(r"[ąćęłńśźż]", notes or "", re.I))


def suffix(notes: str) -> str:
    """What marks a title as only an idea, in the language of the notes."""
    return "(sugestia)" if polish(notes) else "(suggestion)"


def system_prompt(notes: str) -> str:
    """The instructions, with the language of the titles said outright: a small model told only
    'the language of their notes' answers in English (live: 'Walk in nature (sugestia)')."""
    if not polish(notes):
        return SYSTEM + "\n- Write every title and why in English."
    return SYSTEM + ("\n- Write every title and why in Polish, never in English: e.g. \"Spacer\", \"Czytanie "
                     "książki\", \"Rozciąganie\", \"Telefon do przyjaciela\", \"Krótki kurs online\", \"Kino\".")


def bare(title: str) -> str:
    """A suggestion's title without its mark, for comparing: 'Czytanie (sugestia)' -> 'czytanie'."""
    return " ".join(_SUFFIX.sub("", title).casefold().split())


def day_gaps(day: date, events: list[Event], now: datetime, awake: tuple[time, time]) -> list:
    """The day's free time from now on within its waking hours, around every
    event (the user's and the planner's blocks alike)."""
    lo, hi = (datetime.combine(day, t).astimezone() for t in awake)
    busy = [replace(e, managed=False) for e in events if not e.all_day]
    gaps = [(max(a, lo), min(b, hi)) for a, b in free_gaps(day, busy, now)]
    return [(a, b) for a, b in gaps if b > a]


def routine_time(day: date, rules, events: list[Event]) -> list:
    """The usual time of the day's routine blocks, which a suggestion never
    takes, even where the calendar shows nothing (a block under way, one a
    replan didn't put back): only genuinely free time is filled. Not a block
    moved elsewhere that day, nor one the notes rule out that day."""
    spans, _ = routine_spans(rules.typical_week, getattr(rules, "categories", {}), [day])
    history: dict[str, list[date]] = {}
    for e in events:
        if not e.all_day:
            history.setdefault(e.calendar, []).append(e.start.date())
    out = []
    for span in spans[day]:
        s, e, cat, title = span[:4]
        same = [x for x in events if x.start.date() == day and x.calendar == cat
                and x.title.strip().casefold() == title.strip().casefold()]
        if same and not any(x.start < e and x.end > s for x in same) and not _intent(span):
            continue  # moved: its usual time is free (an open block never moves; it is filled later)
        mid = datetime.combine(day, time(0)).astimezone()
        block = Block(day=day.isoformat(), start=f"{s:%H:%M}", end=_spans(day, [(s, e)]).split("-")[1],
                      category=cat, title=title)
        if window_rule(rules.note_rules, cat, minutes(mid, s), minutes(mid, e), day.weekday()) or _count_rules(
                [(s, e, block)], rules.note_rules, history)[1]:
            continue  # the notes skip it that day
        out.append((s, e))
    return out


def _offered(storage, day: date) -> list:
    return [tuple(datetime.fromisoformat(x) for x in span)
            for span in json.loads(storage.get_state(f"fillers_offered:{day}", "[]"))]


def check(fillers: list[Filler], asks: dict, categories: list[str], rules, history: dict[str, list[date]],
          recent: list[tuple[date, str]], unwanted: set[str], budget: dict[date, int],
          own: frozenset[str] = frozenset()) -> tuple[list, list[str]]:
    """The suggestions that keep every rule as (start, end, filler), and why each other one was refused."""
    apart = VARIETY_DAYS.get(rules.variety, 3)
    history = {c: list(ds) for c, ds in history.items()}
    recent, budget = list(recent), dict(budget)
    kept, refused = [], []
    for f in fillers:
        # one line each (not every backend keeps the schema's limits): the title fits a calendar block
        f = f.model_copy(update={"title": _SUFFIX.sub("", " ".join(f.title.split()))[:TITLE_MAX].strip(),
                                 "why": " ".join(f.why.split())[:WHY_MAX]})
        d = next((x for x in asks if x.isoformat() == f.day), None)
        s_m, e_m = _hhmm(f.start), _hhmm(f.end)
        name, why = bare(f.title), None
        cap = min(LONGEST, budget[d]) if d is not None else LONGEST
        if s_m is not None and e_m is not None and e_m - s_m > cap >= SHORTEST:
            e_m = s_m + cap  # a small model takes the whole gap: cut it to what may be filled
            f = f.model_copy(update={"end": f"{e_m // 60:02d}:{e_m % 60:02d}"})
        if d is None:
            why = "not a day to fill"
        elif s_m is None or e_m is None or not SHORTEST <= e_m - s_m <= LONGEST:
            why = f"not {SHORTEST}-{LONGEST} min"
        elif f.category not in categories:
            why = "not one of the categories"
        else:
            midnight = datetime.combine(d, time(0)).astimezone()
            s, e = midnight + timedelta(minutes=s_m), midnight + timedelta(minutes=e_m)
            if not any(a <= s and e <= b for a, b in asks[d]):
                why = "not inside a free gap"
            elif any(ks < e and s < ke for ks, ke, _ in kept):
                why = "overlaps another suggestion"
            elif rule := window_rule(rules.note_rules, f.category, s_m, e_m, d.weekday()):
                why = f"breaks the note \"{rule.source}\""
            elif not name:
                why = "no title"
            elif name in unwanted:
                why = "you removed it lately"
            elif name in own:
                why = "a copy of one of your own events"
            elif any(n == name and abs((d - x).days) < apart for x, n in recent):
                why = "suggested lately (variety)"
            elif e_m - s_m > budget[d]:
                why = "would cut into the day's minimum free time"
            elif broken := _count_rules([(s, e, f)], rules.note_rules, history)[1]:
                why = "breaks the note " + broken[0].split("breaks the note ", 1)[1]
        if why:
            refused.append(f"{f.day} {f.start}-{f.end} {f.category}: {f.title}: {why}")
            continue
        kept.append((s, e, f))
        budget[d] -= e_m - s_m
        recent.append((d, name))
        history.setdefault(f.category, []).append(d)
    return kept, refused


def schema(categories: list[str], days: list[date], n: int) -> dict:
    s = Fillers.model_json_schema()
    f = s["$defs"]["Filler"]["properties"]
    f["category"]["enum"] = list(categories)
    f["day"]["enum"] = [d.isoformat() for d in days]
    f["title"]["maxLength"] = TITLE_MAX
    f["why"]["maxLength"] = 80
    s["properties"]["fillers"]["maxItems"] = n
    return s


def build_prompt(asks: dict, budget: dict, events: list[Event], notes: str, categories: list[str],
                 routine: list[str], own: list[str], recent: list[str], unwanted: list[str], now: datetime) -> str:
    lines = [f"Now: {DAY_NAMES[now.weekday()]} {now:%Y-%m-%d %H:%M}", f"Categories: {', '.join(categories)}",
             "", "# Their notes", notes.strip() or "(none)", "",
             f"# Their routine: {', '.join(routine) or '(none)'}",
             f"# Their own events lately: {', '.join(own) or '(none)'}",
             f"# Suggested lately: {', '.join(recent) or '(none)'}",
             f"# They removed these suggestions, never suggest them: {', '.join(unwanted) or '(none)'}"]
    for d, gaps in asks.items():
        cal = sorted((e for e in events if e.start.date() == d and not e.all_day), key=lambda e: e.start)
        lines += ["", f"## {DAY_NAMES[d.weekday()]} {d.isoformat()}"]
        lines += [f"- {e.start:%H:%M}-{e.end:%H:%M} {e.calendar}: {e.title}" for e in cal] or ["- nothing"]
        lines += [f"Gaps to fill: {_spans(d, gaps)}; at most {budget[d]} min this day"]
    return "\n".join(lines)


def suggest(backend, days: list[date], events: list[Event], storage, rules, notes: str, categories: list[str],
            now: datetime, hidden_since: datetime | None = None) -> tuple[list[PlannedChange], list[str]]:
    """Suggestions for today and tomorrow among `days`, as calendar changes:
    removals of suggestions something now overlaps, and new ones for gaps not
    offered before. Notices suggestions the user deleted on the way.
    `events`: the calendar after the plan, from 14 days back to a week ahead.
    `hidden_since`: the planner's `now`, from which on it didn't see suggestions
    (so may have put something over them); defaults to `now`.
    Returns the changes and why each refused suggestion was refused."""
    today = now.date()
    near = [today, today + timedelta(days=1)]
    offered = {d: _offered(storage, d) for d in near}
    rows = storage.fillers_since((today - timedelta(days=AVOID_DAYS)).isoformat())
    mine = [e for e in events if e.suggested and not e.all_day]
    by_id, by_time = {e.id: e for e in mine}, {(e.title, e.start): e for e in mine}
    stays = set()  # the ids of suggestions the user moved: their choice, never removed for an overlap
    for r in rows:
        d, start = date.fromisoformat(r["day"]), datetime.fromisoformat(r["start"])
        if r["status"] not in ("placed", "moved") or not r["event_id"] or d not in near:
            continue
        # a calendar resync (Google, CalDAV) may give it a new id: the same title and time is the same block
        e = by_id.get(r["event_id"]) or by_time.get((r["title"], start))
        if e is None:  # deleted by the user: not wanted, and its time stays free that day
            storage.update_filler(r["id"], status="deleted")
            r["status"] = "deleted"
            offered[d].append((start, datetime.fromisoformat(r["end"])))
            continue
        if e.id != r["event_id"] or e.start != start:
            r.update(event_id=e.id, status="moved" if e.start != start else r["status"])
            storage.update_filler(r["id"], event_id=e.id, status=r["status"], day=e.start.date().isoformat(),
                                  start=e.start.isoformat(), end=e.end.isoformat())
        if r["status"] == "moved":
            stays.add(e.id)
    others = [e for e in events if not e.suggested and not e.all_day]
    gone = [e for e in mine if e.start >= (hidden_since or now) and e.id not in stays
            and any(o.start < e.end and o.end > e.start for o in others)]
    changes = [PlannedChange(kind="delete", category=e.calendar, title=e.title, event_id=e.id,
                             reason="its time went to something else") for e in gone]
    for e in gone:  # its time may get a new suggestion
        for r in rows:
            if r["event_id"] == e.id:
                storage.update_filler(r["id"], status="removed")
        if e.start.date() in offered:
            offered[e.start.date()] = _minus(offered[e.start.date()], [(e.start, e.end)])
    busy = others + [e for e in mine if e not in gone]
    row_of = {r["event_id"]: r["id"] for r in rows}
    for d in near:  # later events left the day less than its minimum free time: the newest suggestions go
        whole = day_gaps(d, busy, datetime.combine(d, rules.day_start).astimezone(), (rules.day_start, rules.day_end))
        short = rules.min_free_minutes - sum(minutes(a, b) for a, b in whole)
        for e in sorted((e for e in busy if e.suggested and e.start >= now and e.start.date() == d
                         and e.id not in stays), key=lambda e: -row_of.get(e.id, 0)):
            if short <= 0:
                break
            busy.remove(e)
            short -= minutes(e.start, e.end)
            storage.update_filler(row_of.get(e.id, -1), status="removed")
            changes.append(PlannedChange(kind="delete", category=e.calendar, title=e.title, event_id=e.id,
                                         reason="the day needs its free time"))
    asks, budget = {}, {}
    for d in (d for d in days if d in near and rules.typical_week.get(d.weekday())):
        gaps = _minus(day_gaps(d, busy, now, (rules.day_start, rules.day_end)), routine_time(d, rules, busy))
        budget[d] = sum(minutes(a, b) for a, b in gaps) - rules.min_free_minutes
        new = [(a, b) for a, b in _minus(gaps, offered[d]) if minutes(a, b) >= SHORTEST]
        if new and budget[d] >= SHORTEST:
            asks[d] = new
    refused: list[str] = []
    if asks:
        recent = [(date.fromisoformat(r["day"]), r["title"]) for r in rows
                  if r["status"] in ("placed", "moved") and today - timedelta(days=7) <= date.fromisoformat(r["day"])]
        unwanted = list(dict.fromkeys(_SUFFIX.sub("", r["title"]) for r in rows if r["status"] == "deleted"))
        routine = list(dict.fromkeys(b.label for bs in rules.typical_week.values() for b in bs))
        own = list(dict.fromkeys(e.title for e in others if not e.managed and e.start < now))[-30:]
        prompt = build_prompt(asks, budget, busy, notes, categories, routine, own,
                              list(dict.fromkeys(_SUFFIX.sub("", t) for _, t in recent)), unwanted, now)
        answer, refused = None, ["no suggestions: the model's answer wasn't readable"]
        for _ in range(2):  # one retry for an answer that isn't the JSON asked for
            try:
                answer = backend.structured(system_prompt(notes), prompt, Fillers, schema(categories, list(asks),
                                                                           sum(map(len, asks.values()))))
                break
            except ValueError:
                continue
            except Exception as exc:  # no model now: the gaps are offered again next time
                refused = [f"no suggestions: {' '.join(str(exc).split())[:120]}"]
                break
        asks = asks if answer is not None else {}
    if asks:
        history: dict[str, list[date]] = {}
        for e in busy:
            history.setdefault(e.calendar, []).append(e.start.date())
        kept, refused = check(answer.fillers, asks, categories, rules, history,
                              [(d, bare(t)) for d, t in recent], {bare(t) for t in unwanted}, budget,
                              frozenset(bare(e.title) for e in others if not e.managed))
        mark = suffix(notes)
        changes += [PlannedChange(kind="create", category=f.category, title=f"{_SUFFIX.sub('', f.title).strip()} {mark}",
                                  reason=f.why or "free time", new_start=s, new_end=e, suggested=True)
                    for s, e, f in kept]
        for d, spans in asks.items():
            offered[d] += spans
    for d in near:
        storage.set_state(f"fillers_offered:{d}", json.dumps([[a.isoformat(), b.isoformat()] for a, b in offered[d]]))
    return changes, refused


def record(applied: list[PlannedChange], storage) -> None:
    """Remember the suggestions written to the calendar (variety, and noticing a deleted one)."""
    for c in applied:
        if c.kind == "create" and c.suggested:
            storage.save_filler(c.new_start, c.new_end, c.title, c.category, c.event_id)
