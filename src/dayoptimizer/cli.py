from __future__ import annotations
import argparse
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from dayoptimizer import paths
from dayoptimizer.apply import _missing, apply_changes
from dayoptimizer.core.allday import conversion, timed_all_day
from dayoptimizer.core.calendar import CalendarClient
from dayoptimizer.core.garmin import summarize
from dayoptimizer.core.planner import plan_day
from dayoptimizer.core.rules import load_config_data, load_rules
from dayoptimizer.core.storage import Storage
from dayoptimizer.llm.backend import LLMUnavailable, format_changes, make_backend, pin_day, resolve_day

console = Console()

NO_ACCESS_HELP = ("DayOptimizer can't read your calendar: macOS access was denied. Turn on DayOptimizer in "
                  "System Settings → Privacy & Security → Calendars (open it with:  open "
                  "\"x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars\" ), "
                  "then run the command again.")

def _load_config():
    cfg_path = Path(__file__).parent.parent.parent / "config.default.yaml"
    return load_rules(cfg_path), load_config_data(cfg_path)

def _fetch_garmin(storage, day: str):
    from dayoptimizer.core.garmin import GarminClient, GarminNotConfigured, garmin_configured
    if not garmin_configured() or day > date.today().isoformat():
        return storage.get_garmin(day)
    try:
        summary = GarminClient().fetch_summary(day)
        storage.save_garmin(summary)
        return summary
    except GarminNotConfigured as exc:
        console.print(str(exc), markup=False, style="yellow")
        return storage.get_garmin(day)
    except Exception as exc:
        console.print(f"Garmin unavailable ({exc}) — using last cached data",
                      markup=False, style="yellow")
        return storage.get_garmin(day)

_ACTIVITY_WEEKS = 8
_ACTIVITY_REFRESH_HOURS = 6

def _fetch_activities(storage, now):
    """Recorded workouts of the last weeks, refreshed at most every few hours:
    the planner needs them to tell which routine blocks are training, and what
    they load. Garmin's API is rate-limited, so the cache does the work."""
    from dayoptimizer.core.garmin import GarminClient, garmin_configured
    since = now - timedelta(weeks=_ACTIVITY_WEEKS)
    last = storage.get_state("activities_synced")
    stale = True
    if last:
        try:
            stale = (now - datetime.fromisoformat(last)) > timedelta(hours=_ACTIVITY_REFRESH_HOURS)
        except ValueError:
            stale = True
    if garmin_configured() and stale:
        try:
            storage.save_activities(GarminClient().activities(since.date().isoformat(),
                                                              now.date().isoformat()))
            storage.set_state("activities_synced", now.isoformat())
        except Exception as exc:
            console.print(f"Garmin activities unavailable ({exc}) — using cached ones",
                          markup=False, style="yellow")
    return storage.activities_since(since)

def _confirm(change):
    if not sys.stdin.isatty():
        return False
    prompt = f"Fixed-event change: {change.category}: {change.title} — {change.reason}. Approve? [y/N] "
    try:
        answer = console.input(prompt, markup=False)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("y", "yes")

def _run_plan(day: date, calendar, storage, rules, confirm=None):
    confirm = confirm if confirm is not None else _confirm
    day_start = datetime.combine(day, time(0)).astimezone()
    events_raw = calendar.list_events(day_start, day_start + timedelta(days=1))
    tomorrow_raw = calendar.list_events(day_start + timedelta(days=1), day_start + timedelta(days=2))
    events = [e for e in events_raw if not e.all_day]
    title_timed = timed_all_day(events_raw, day)
    events += [t for t, _ in title_timed]
    tomorrow = [e for e in tomorrow_raw if not e.all_day]
    tomorrow_fixed = [e for e in tomorrow if not rules.is_movable(e.calendar)]
    def _all_day_last_date(e):
        return (e.end - timedelta(microseconds=1)).date() if e.end.time() == time(0, 0) else e.end.date()
    is_holiday = any(
        e.all_day and e.calendar in rules.holiday_calendars
        and e.start.date() <= day <= _all_day_last_date(e)
        for e in events_raw)
    is_workday = (day.weekday() in rules.work_days) and not is_holiday
    storage.sync_events(events_raw, day_start, day_start + timedelta(days=1))
    garmin = _fetch_garmin(storage, day.isoformat())
    if garmin:
        console.print(f"[dim]{summarize(garmin)}[/dim]")
    week_start = day - timedelta(days=day.weekday())
    week_start_dt = datetime.combine(week_start, time(0)).astimezone()
    week_events_raw = calendar.list_events(week_start_dt, week_start_dt + timedelta(days=7))
    week_events = [e for e in week_events_raw if not e.all_day]
    week_gym_count = sum(1 for e in week_events if e.calendar == "Gym" and e.start.date() != day)
    now = datetime.now().astimezone()
    past = calendar.list_events(day_start - timedelta(days=8), day_start)
    history: dict[str, list[date]] = {}
    for e in past:
        if not e.all_day:
            history.setdefault(e.calendar, []).append(e.start.date())
    changes = plan_day(day, events, garmin, rules, now=now,
                       activities=_fetch_activities(storage, now), history=history,
                       tomorrow_first_fixed=min((e.start for e in tomorrow_fixed), default=None),
                       week_gym_count=week_gym_count,
                       next_day_events=tomorrow,
                       is_workday=is_workday)
    stand_ins = {t.id for t, _ in title_timed}
    changes = [c for c in changes if c.event_id not in stand_ins] + [conversion(t, tt) for t, tt in title_timed]
    applied, errors = apply_changes(changes, calendar, storage, confirm)
    return changes, applied, errors

def _llm_plan(days: list[date], calendar, storage, rules, confirm=None):
    """Let a language model lay out the days (llm/week_plan.py checks its work).
    Anthropic first, then the local Ollama model; None when neither can plan,
    so the caller falls back to placing the routine by rule."""
    from dayoptimizer.llm import backend as llm
    from dayoptimizer.llm.week_plan import plan_days
    from dayoptimizer.routine import render_routine
    from dayoptimizer.core.models import PlannedChange
    from dayoptimizer.llm.task_rules import remaining
    tasks = storage.open_tasks()
    week_start = days[0] - timedelta(days=days[0].weekday())
    lo = datetime.combine(week_start - timedelta(days=7), time(0)).astimezone()
    hi = datetime.combine(max(days[-1], week_start + timedelta(days=6)) + timedelta(days=1), time(0)).astimezone()
    events = calendar.list_events(lo, hi)
    now = datetime.now().astimezone()
    # Blocks of a task that is done (or gone) are removed by code, with or without a model.
    open_ids = {t.id for t in tasks}
    stale = [e for e in events if e.managed and e.task_id and e.task_id not in open_ids and e.start >= now]
    if stale:
        apply_changes([PlannedChange(kind="delete", category=e.calendar, title=e.title, event_id=e.id,
                                     reason="its task is done") for e in stale], calendar, storage, lambda c: True)
        events = [e for e in events if e not in stale]
    if not rules.has_routine and not tasks:
        return None
    _, config = _load_config()
    backends = llm.planning_backends(config.get("llm", {}))
    if not backends:
        console.print("No language model to plan with (no ANTHROPIC_API_KEY in .env, Ollama not "
                      "running) — placing your routine by rule instead.", markup=False, style="yellow")
        return None
    planned = set(days)
    # ponytail: task blocks are read from 30 days back to 60 ahead; progress
    # outside that is missed. Store progress per task if that matters.
    task_blocks = calendar.list_events(now - timedelta(days=30), now + timedelta(days=60)) if tasks else []
    left = remaining(tasks, task_blocks, now, planned)
    routine_days = {d: [(datetime.combine(d, time(0)).astimezone() + timedelta(minutes=b.start),
                         datetime.combine(d, time(0)).astimezone() + timedelta(minutes=b.end),
                         b.category, b.title or b.category,
                         not getattr(getattr(rules, "categories", {}).get(b.category), "movable", True))
                        for b in rules.typical_week.get(d.weekday(), [])]
                    for d in days}
    reserved = {d: [(s, e, title, cat) for s, e, cat, title, fixed in spans if fixed]
                for d, spans in routine_days.items()}
    history: dict[str, list[date]] = {}
    for e in events:
        if not e.all_day and (e.start.date() not in planned or e.start < now):
            history.setdefault(e.calendar, []).append(e.start.date())
    window = [e for e in events if e.start.date() >= week_start]
    notes = config.get("notes") or ""
    routine = render_routine(config["categories"], config.get("typical_week") or {}, notes)
    health = None
    if date.today() in planned:
        garmin = _fetch_garmin(storage, date.today().isoformat())
        health = summarize(garmin) if garmin else None
    for backend in backends:
        name = type(backend).__name__.removesuffix("Backend")
        console.print(f"Planning with {name}...", style="dim")
        try:
            changes, summary, dropped, unscheduled = plan_days(
                backend, days, routine, list(config["categories"]), window, notes, rules.note_rules, now,
                health, history, {d for d in days if rules.typical_week.get(d.weekday())},
                tasks=tasks, left=left, reserved=reserved, routine_days=routine_days)
        except Exception as exc:
            console.print(f"{name} couldn't plan ({' '.join(str(exc).split())[:200]}) — trying the next option.",
                          markup=False, style="yellow")
            continue
        applied, errors = apply_changes(changes, calendar, storage, confirm or _confirm)
        return changes, applied, errors, summary, dropped, unscheduled
    console.print("No language model could plan — placing your routine by rule instead.",
                  markup=False, style="yellow")
    return None

def _plan_day(day: date, calendar, storage, rules, confirm=None):
    result = _llm_plan([day], calendar, storage, rules, confirm)
    if result is None:
        return _run_plan(day, calendar, storage, rules, confirm)
    return result[:3]

_MISSING_CALENDAR_RE = re.compile(r"^calendar '(.+)' not found")

def _summarize_errors(errors: list[str]) -> list[str]:
    """Dedupe repeated identical messages and fold every 'calendar X not
    found' message into a single aggregated line naming all the missing
    calendars, so N failing blocks for the same category don't repeat the
    same sentence N times."""
    missing_calendars: list[str] = []
    other: list[str] = []
    for msg in errors:
        m = _MISSING_CALENDAR_RE.match(msg)
        if m:
            name = m.group(1)
            if name not in missing_calendars:
                missing_calendars.append(name)
        elif msg not in other:
            other.append(msg)
    lines = []
    if missing_calendars:
        lines.append(f"Missing calendars: {', '.join(missing_calendars)} — "
                      "create them in the Calendar app")
    lines.extend(other)
    return lines

def _print_errors(errors: list[str]) -> None:
    if not errors:
        return
    console.print(f"{len(errors)} block(s) could not be written:", markup=False)
    for line in _summarize_errors(errors):
        console.print(line, markup=False)

def _print_pending(storage):
    pending = storage.get_pending()
    if not pending:
        return
    console.print("Pending approval (fixed events — apply with 'dayoptimizer apply --ids ...'):")
    for pid, c in pending:
        when = f" → {c.new_start:%Y-%m-%d %H:%M}" if c.new_start is not None else ""
        console.print(f"  #{pid} [{c.kind}] {c.category}: {c.title}{when} — {c.reason}", markup=False)

def cmd_plan(args, rules, config):
    calendar = CalendarClient()
    if not calendar.request_access():
        console.print(NO_ACCESS_HELP, markup=False, style="red")
        return
    storage = Storage(paths.db_path())
    start_day = date.fromisoformat(args.date) if args.date else date.today()
    days = args.week if args.week else 1
    result = _llm_plan([start_day + timedelta(days=i) for i in range(days)], calendar, storage, rules)
    if result is not None:
        changes, applied, errors, summary, dropped, unscheduled = result
        console.print(format_changes(changes), markup=False)
        console.print(f"[green]Applied {len(applied)} changes.[/green]")
        if summary:
            console.print(summary, markup=False)
        if dropped:
            console.print(f"Left out {len(dropped)} block(s) that broke a rule:", markup=False, style="yellow")
            for line in dropped:
                console.print(f"  {line}", markup=False)
        if unscheduled:
            console.print("Tasks that didn't fit:", markup=False, style="yellow")
            for line in unscheduled:
                console.print(f"  {line}", markup=False)
        _print_errors(errors)
        return
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        if days > 1:
            console.print(f"\n[bold]=== {day:%A %Y-%m-%d} ===[/bold]")
        changes, applied, errors = _run_plan(day, calendar, storage, rules)
        console.print(format_changes(changes), markup=False)
        console.print(f"[green]Applied {len(applied)} changes.[/green]")
        if rules.has_routine and not rules.typical_week.get(day.weekday()):
            console.print(f"[yellow]Your routine has nothing on {day:%A}s, so nothing was planned. "
                          "Draw that day in `dayoptimizer setup`.[/yellow]")
        _print_errors(errors)
    _print_pending(storage)

def cmd_apply(args, rules, config):
    calendar = CalendarClient()
    if not calendar.request_access():
        console.print(NO_ACCESS_HELP, markup=False, style="red")
        return
    storage = Storage(paths.db_path())
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    if not ids:
        console.print("No pending ids given.")
        return
    pending = storage.get_pending(ids)
    applied = 0
    for pid, c in pending:
        try:
            if c.kind == "move":
                calendar.move_event(c.event_id, c.new_start, c.new_end)
            elif c.kind == "create":
                calendar.create_event(c.category, c.title, c.new_start, c.new_end)
        except KeyError:
            storage.log_change(f"[error] apply #{pid} {c.kind} {c.category}: {c.title}", _missing(c))
            console.print(f"#{pid} failed: {_missing(c)}", markup=False)
            continue
        except RuntimeError as exc:
            storage.log_change(f"[error] apply #{pid} {c.kind} {c.category}: {c.title}", str(exc))
            console.print(f"#{pid} failed: {exc}", markup=False)
            continue
        storage.log_change(f"[applied #{pid}] {c.kind} {c.category}: {c.title}", c.reason)
        applied += 1
    storage.delete_pending([pid for pid, _ in pending])
    missing = sorted(set(ids) - {pid for pid, _ in pending})
    if missing:
        console.print(f"No pending change {', '.join(f'#{i}' for i in missing)} — already applied, "
                      "or replaced by a newer plan. Run  dayoptimizer plan  to see what's pending.")
    if pending:
        console.print(f"Applied {applied} of {len(pending)} pending change(s).")

def cmd_check(args, rules, config):
    from dayoptimizer.check import run_check
    from dayoptimizer.core.notify import notify
    calendar = CalendarClient()
    if not calendar.request_access():
        console.print(NO_ACCESS_HELP, markup=False, style="red")
        storage = Storage(paths.db_path())
        key = f"no_access:{date.today().isoformat()}"
        if not storage.get_state(key):
            notify("DayOptimizer", "No calendar access, so your day isn't being adjusted. "
                                   "Allow DayOptimizer in System Settings, Privacy & Security, Calendars.")
            storage.set_state(key, "1")
        return
    storage = Storage(paths.db_path())
    actions = run_check(calendar, storage, rules, datetime.now().astimezone())
    if actions:
        console.print(f"[green]Actions taken: {', '.join(actions)}[/green]")
    else:
        console.print("[dim]No actions.[/dim]")

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

def events_to_create(req, categories, today: date) -> tuple[list[tuple[str, str, datetime, datetime]], list[str]]:
    """Validate what the LLM extracted: (category, title, start, end) to create,
    plus a note for every event that can't be placed as said."""
    ok, problems = [], []
    for e in req.events:
        if e.category not in categories:
            problems.append(f"'{e.title}': no category '{e.category}' — skipped")
            continue
        day = resolve_day(e.day, today)
        if not e.start_time or not _HHMM.match(e.start_time):
            problems.append(f"'{e.title}': no time given — say when, e.g. 'gym at 18:00'")
            continue
        h, m = (int(x) for x in e.start_time.split(":"))
        start = datetime.combine(day, time(h, m)).astimezone()
        end = None
        if e.end_time and _HHMM.match(e.end_time):
            eh, em = (int(x) for x in e.end_time.split(":"))
            end = datetime.combine(day, time(eh, em)).astimezone()
        if end is None or end <= start:
            minutes = min(max(e.duration_minutes or 60, 5), 12 * 60)
            end = start + timedelta(minutes=minutes)
        ok.append((e.category, e.title[:100] or e.category, start, end))
    return ok, problems

def cmd_ask(args, rules, config):
    """`dayoptimizer "meeting at 14 for an hour, then gym"`: understand the text
    (here, in the terminal), show it, and on OK hand the events to `add`, which
    writes them to the calendar inside the app bundle and replans."""
    import json
    if not rules.categories:
        console.print("You have no categories yet, so there is nothing to file this under. "
                      "Add some in  dayoptimizer setup  first.", markup=False, style="yellow")
        return
    try:
        backend = make_backend(config["llm"])
        now = datetime.now()
        req = backend.parse_request(args.text, today=now.date().isoformat(), now=f"{now:%A %H:%M}",
                                    categories=list(rules.categories))
    except LLMUnavailable as exc:
        console.print(f"{exc}\nWithout it, `dayoptimizer` still optimizes today.", markup=False, style="yellow")
        return
    except Exception as exc:
        console.print(f"Couldn't understand that right now ({type(exc).__name__}). Try again in a moment.",
                      markup=False, style="yellow")
        return
    to_create, problems = events_to_create(pin_day(args.text, req), rules.categories, now.date())
    for p in problems:
        console.print(p, markup=False, style="yellow")
    if not to_create:
        console.print(req.reply or "Nothing to add. Say what and when, e.g. 'gym at 18:00'.", markup=False)
        return
    console.print("I'll add:")
    for category, title, start, end in to_create:
        console.print(f"  {start:%a %d.%m %H:%M}-{end:%H:%M}  {title}  ({category})", markup=False)
    if sys.stdin.isatty():
        try:
            answer = console.input("Add to your calendar and replan? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("", "y", "yes", "t", "tak"):
            console.print("Nothing changed.")
            return
    payload = json.dumps([{"category": c, "title": t, "start": s.isoformat(), "end": e.isoformat()}
                          for c, t, s, e in to_create], ensure_ascii=False)
    if _in_bundle() or sys.platform != "darwin":
        cmd_add(argparse.Namespace(events=payload), rules, config)
    else:
        console.print("Working on your calendar...", style="dim")
        _calendar_run(["add", payload])

def cmd_add(args, rules, config):
    """Internal: create the events `ask` confirmed, then replan their days."""
    import json
    try:
        items = json.loads(args.events)
        events = [(i["category"], str(i["title"])[:100], datetime.fromisoformat(i["start"]),
                   datetime.fromisoformat(i["end"])) for i in items]
    except (ValueError, KeyError, TypeError):
        console.print("Couldn't read the events to add.", style="red")
        return
    calendar = CalendarClient()
    if not calendar.request_access():
        console.print(NO_ACCESS_HELP, markup=False, style="red")
        return
    storage = Storage(paths.db_path())
    days = set()
    for category, title, start, end in events:
        if category not in rules.categories or end <= start:
            continue
        try:
            calendar.create_event(category, title, start, end)
        except KeyError:
            console.print(f"'{title}': there's no '{category}' calendar — create it in the Calendar app",
                          markup=False, style="yellow")
            continue
        storage.log_change(f"[added] {category}: {title} {start:%Y-%m-%d %H:%M}", "requested in plain words")
        console.print(f"Added {title} ({category}) {start:%a %H:%M}-{end:%H:%M}", markup=False, style="green")
        days.add(start.date())
    try:
        summarize = make_backend(config["llm"]).summarize_changes
    except LLMUnavailable:
        summarize = format_changes
    for day in sorted(days):
        changes, applied, errors = _plan_day(day, calendar, storage, rules)
        if len(days) > 1:
            console.print(f"\n{day:%A %Y-%m-%d}", style="bold")
        console.print(Markdown(summarize(changes)))
        _print_errors(errors)
    _print_pending(storage)

def _task_line(t) -> str:
    parts = [f"[{t.id}] {t.title} ({t.category}) {t.duration_min} min"]
    if t.due is not None:
        parts.append(f"due {t.due:%a %d.%m %H:%M}")
    if t.not_before is not None:
        parts.append(f"from {t.not_before:%a %d.%m}")
    if t.min_chunk_min:
        parts.append(f"chunks >= {t.min_chunk_min} min")
    if t.priority != "normal":
        parts.append(f"{t.priority} priority")
    return ", ".join(parts)

def cmd_task(args, rules, config):
    """`dayoptimizer task "report for Friday, 3h"`: understand the tasks (one or
    several, here in the terminal), save them and replan once up to the latest
    deadline, so the planner places them into free time. `task list` /
    `task done t3`."""
    from dayoptimizer.llm.task_request import task_from_request
    words = list(args.words)
    storage = Storage(paths.db_path())
    if words == ["list"]:
        tasks = storage.open_tasks()
        if not tasks:
            console.print('No open tasks. Add one:  dayoptimizer task "report for Friday, 3h"', markup=False)
        for t in tasks:
            console.print(_task_line(t), markup=False)
        return
    if len(words) == 2 and words[0] == "done":
        task = storage.get_task(words[1])
        if task is None or not storage.mark_task_done(words[1]):
            console.print(f"No task '{words[1]}'. See  dayoptimizer task list", markup=False, style="yellow")
            return
        console.print(f"Done: {words[1]}. Removing its planned blocks...", markup=False, style="green")
        _replan_for([task], rules, config)
        return
    if not rules.categories:
        console.print("You have no categories yet, so there is nothing to file this under. "
                      "Add some in  dayoptimizer setup  first.", markup=False, style="yellow")
        return
    now = datetime.now()
    try:
        parsed = make_backend(config["llm"]).parse_task(" ".join(words), now=f"{now:%A %Y-%m-%d %H:%M}",
                                                        categories=list(rules.categories))
    except LLMUnavailable as exc:
        console.print(f"{exc}\nUnderstanding a task needs a language model.", markup=False, style="yellow")
        return
    except Exception as exc:
        console.print(f"Couldn't understand that right now ({type(exc).__name__}). Try again in a moment.",
                      markup=False, style="yellow")
        return
    if not parsed.tasks:
        console.print(parsed.reply or "Say what the task is, e.g. 'report for Friday, 3h'.",
                      markup=False, style="yellow")
        return
    first = int(storage.next_task_id()[1:])
    tasks = []
    have = {(t.category, t.title.strip().casefold()): t.id for t in storage.open_tasks()}
    for req in parsed.tasks:
        task, problem = task_from_request(req, list(rules.categories), now.date(), f"t{first + len(tasks)}")
        if task is None:
            console.print(problem, markup=False, style="yellow")
        elif (task.category, task.title.strip().casefold()) in have:
            console.print(f"'{task.title}' is already open as {have[(task.category, task.title.strip().casefold())]} "
                          "— not added twice. See  dayoptimizer task list", markup=False, style="yellow")
        else:
            tasks.append(task)
    if not tasks:
        return
    console.print("New task:" if len(tasks) == 1 else "New tasks:")
    for task in tasks:
        console.print(f"  {_task_line(task)}", markup=False)
    if sys.stdin.isatty():
        try:
            answer = console.input("Save and place in your calendar? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("", "y", "yes", "t", "tak"):
            console.print("Nothing saved.")
            return
    for task in tasks:
        storage.save_task(task)
    console.print("Placing in your calendar...", style="dim")
    _replan_for(tasks, rules, config)

def _replan_for(tasks, rules, config):
    """Replan from today up to the latest deadline (a week at most), in the
    calendar bundle: that places new tasks and removes a finished one's blocks."""
    today = date.today()
    days = max(7 if t.due is None else max(1, min(7, (t.due.date() - today).days + 1)) for t in tasks)
    if _in_bundle() or sys.platform != "darwin":
        cmd_plan(argparse.Namespace(date=None, week=days), rules, config)
    else:
        _calendar_run(["plan", "--week", str(days)])

def cmd_chat(args, rules, config):
    """Keep asking in one session; each line is a `dayoptimizer "..."` request."""
    console.print("[bold]DayOptimizer[/bold] — tell me about your day ('exit' to quit).")
    while True:
        try:
            text = console.input("[cyan]> [/cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("exit", "quit", "q"):
            break
        if text:
            cmd_ask(argparse.Namespace(text=text), rules, config)

def cmd_agent(args, rules, config):
    from dayoptimizer import agent
    if args.agent_command == "install":
        console.print(agent.install(args.interval, args.at))
    elif args.agent_command == "uninstall":
        console.print(agent.uninstall())
    elif args.agent_command == "status":
        console.print(agent.status())

def cmd_garmin(args, rules, config):
    if args.garmin_command == "login":
        from getpass import getpass
        from dayoptimizer.core.garmin import GarminLoginError, garmin_finish_mfa, garmin_start_login
        email = console.input("Garmin email: ").strip()
        password = getpass("Garmin password (used once, never stored): ")
        try:
            needs_mfa, api = garmin_start_login(email, password)
            if needs_mfa:
                garmin_finish_mfa(api, console.input("Code from Garmin (email or authenticator app): ").strip())
            console.print("Connected to Garmin. Only the session tokens are stored (password not kept).")
        except GarminLoginError as exc:
            console.print(f"[red]{exc}[/red]")

def cmd_stats(args, rules, config):
    from dayoptimizer.core.patterns import render_stats, suggest_adjustments, weekly_stats
    from dayoptimizer import paths
    storage = Storage(paths.db_path())
    stats = weekly_stats(storage.garmin_history(14))
    console.print(render_stats(stats))
    for tip in suggest_adjustments(stats, rules):
        console.print(f"- {tip}")

def cmd_sync(args, rules, config):
    """Copy N days of the calendar into the local cache (used by the web import,
    which cannot touch EventKit itself). Prints SYNCED n or NO_ACCESS for the caller,
    then CAL <name>\t<#hex>\t<account> for every calendar, so the import can list empty ones too."""
    calendar = CalendarClient()
    if not calendar.request_access():
        print("NO_ACCESS")
        print(NO_ACCESS_HELP)
        return
    start = datetime.combine(date.fromisoformat(args.start), time(0, 0)).astimezone()
    end = start + timedelta(days=args.days)
    events = calendar.list_events(start, end)
    Storage(paths.db_path()).sync_events(events, start, end)
    print(f"SYNCED {len(events)}")
    for name, (color, account) in calendar.all_calendars().items():
        print(f"CAL {name}\t{color or ''}\t{account.replace(chr(9), ' ')}")

def cmd_calendars(args, rules, config):
    """Create a calendar in the Calendar app for every category that lacks one
    and give it the category's colour. Prints CREATED / RECOLORED <names>,
    FAILED <name>: <why> and COLOR <name> <#hex> lines for the caller, then
    CAL <name>\t<#hex>\t<account> for every calendar. --read only reports."""
    calendar = CalendarClient()
    if not calendar.request_access():
        print("NO_ACCESS")
        print(NO_ACCESS_HELP)
        return
    created, recolored = [], []
    for name, cat in config["categories"].items():
        color = (cat or {}).get("color")
        try:
            if not args.read and calendar.ensure_calendar(name, color):
                created.append(name)
            elif not args.read and color and calendar.set_color(name, color):
                recolored.append(name)
        except KeyError as exc:
            print(f"FAILED {name}: {exc}")
        actual = calendar.calendar_color(name)
        if actual:
            print(f"COLOR {name}\t{actual}")
    print("CREATED " + "\t".join(created))
    print("RECOLORED " + "\t".join(recolored))
    for name, (color, account) in calendar.all_calendars().items():
        print(f"CAL {name}\t{color or ''}\t{account.replace(chr(9), ' ')}")

def cmd_web(args, rules, config):
    from dayoptimizer.web import serve
    serve(port=args.port, open_browser=not args.no_open)

CALENDAR_COMMANDS = {"plan", "apply", "check", "sync", "add", "calendars"}

def _in_bundle() -> bool:
    return "DayOptimizer.app" in sys.executable

def _calendar_run(argv: list[str]) -> None:
    """Run a command in the calendar bundle, showing its output as it comes:
    a local model can plan for many minutes (Ctrl+C stops waiting, not the run)."""
    from dayoptimizer.mcp_server import _bundle_run
    exe = paths.ensure_private_dir() / "DayOptimizer.app" / "Contents" / "MacOS" / "dayopt"
    if not exe.exists():
        console.print("DayOptimizer isn't set up for calendar access yet. In the DayOptimizer "
                      "folder run:  scripts/install.sh", markup=False)
        return
    rest = _bundle_run([a.replace("\n", " ") for a in argv], timeout=None,
                       echo=lambda text: print(text, end="", flush=True))
    if rest.strip():
        console.print(rest.rstrip(), markup=False)

def _first_run() -> bool:
    """No typical week drawn yet: the user hasn't done the setup."""
    from dayoptimizer.web import _local
    try:
        return not _local().get("typical_week")
    except Exception:
        return False

def _iso_date(value: str) -> str:
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"'{value}' is not a date, use DD-MM-YYYY (e.g. 28-09-2026)")

def _hhmm(value: str) -> str:
    if not _HHMM.match(value):
        raise argparse.ArgumentTypeError(f"'{value}' is not a time, use HH:MM (e.g. 07:30)")
    return value

def _positive(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"'{value}' must be a whole number of at least 1")
    return int(value)

def _ids(value: str) -> str:
    if not re.fullmatch(r"\s*\d+\s*(,\s*\d+\s*)*,?\s*", value):
        raise argparse.ArgumentTypeError(f"'{value}' should be pending ids like 3,4")
    return value

_TAKES_WORDS = {"ask", "add", "agent", "garmin", "task"}

def main(argv: list[str] | None = None):
    paths.ensure_private_dir()
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
    try:
        rules, config = _load_config()
    except Exception as exc:
        raw = list(sys.argv[1:] if argv is None else argv)
        if raw[:1] in (["setup"], ["web"]):
            rules = config = None
        else:
            console.print(f"Your settings in {paths.user_config_path()} can't be read "
                          f"({type(exc).__name__}: {' '.join(str(exc).split())}).\nFix or delete that file, "
                          "or run  dayoptimizer setup  to draw your week again.",
                          markup=False, style="red")
            raise SystemExit(1)
    parser = argparse.ArgumentParser(
        prog="dayoptimizer",
        description='dayoptimizer                optimize today around your calendar\n'
                    'dayoptimizer "<your day>"   e.g. "meeting at 14:00 for about an hour, then gym"\n'
                    'dayoptimizer setup          describe your typical week in the browser (first run)',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", metavar="command")
    p_plan = sub.add_parser("plan", help="replan the day (or several days)")
    p_plan.add_argument("--date", default=None, type=_iso_date, help="start date (DD-MM-YYYY, defaults to today)")
    p_plan.add_argument("--week", nargs="?", const=7, type=_positive, default=None,
                        help="plan N days from the start date (default 7)")
    p_apply = sub.add_parser("apply", help="apply pending approval-required changes")
    p_apply.add_argument("--ids", required=True, type=_ids, help="comma-separated pending ids")
    sub.add_parser("chat", help="keep telling DayOptimizer about your day, one line at a time")
    p_ask = sub.add_parser("ask", help='add what you say to the calendar and replan (same as dayoptimizer "...")')
    p_ask.add_argument("text")
    p_add = sub.add_parser("add")
    p_add.add_argument("events")
    p_task = sub.add_parser("task", help='add work to place in free time: task "report for Friday, 3h"; '
                                         'several at once: task "tomorrow: laundry and exam prep, 2h each"; '
                                         'task list; task done t3')
    p_task.add_argument("words", nargs="+")
    sub.add_parser("check", help="stateless background cycle (sleep, new events, stress)")
    sub.add_parser("stats", help="14-day Garmin trends and suggestions")
    p_agent = sub.add_parser("agent", help="manage the background agent (launchd)")
    agent_sub = p_agent.add_subparsers(dest="agent_command", required=True)
    p_agent_install = agent_sub.add_parser("install", help="install and start the agent")
    p_agent_install.add_argument("--interval", type=_positive, default=900,
                                 help="run interval in seconds (default 900)")
    p_agent_install.add_argument("--at", action="append", type=_hhmm, default=None, metavar="HH:MM",
                                 help="run only at this time each day instead (repeat for several)")
    agent_sub.add_parser("uninstall", help="stop and remove the agent")
    agent_sub.add_parser("status", help="agent status")
    p_garmin = sub.add_parser("garmin", help="Garmin Connect account")
    garmin_sub = p_garmin.add_subparsers(dest="garmin_command", required=True)
    garmin_sub.add_parser("login", help="log in and store OAuth tokens (password is not persisted)")
    p_cals = sub.add_parser("calendars", help="create a calendar in the Calendar app for each category")
    p_cals.add_argument("--read", action="store_true", help="only report each category calendar's colour")
    p_sync = sub.add_parser("sync", help="copy calendar events into the local cache")
    p_sync.add_argument("--from", dest="start", required=True, type=_iso_date, help="first day (DD-MM-YYYY)")
    p_sync.add_argument("--days", type=_positive, default=7)
    p_web = sub.add_parser("setup", aliases=["web"],
                           help="describe your typical week in the browser (first run)")
    p_web.add_argument("--port", type=int, default=8765)
    p_web.add_argument("--no-open", action="store_true", help="do not open a browser tab")
    argv = list(sys.argv[1:] if argv is None else argv)
    first = argv[0] if argv else None
    if first is None:
        if _first_run() and not _in_bundle():
            console.print("Welcome! First, show DayOptimizer your typical week. Opening the setup page...")
            argv = ["setup"]
        else:
            argv = ["plan"]
    elif not first.startswith("-") and (
            first not in sub.choices
            or (first not in _TAKES_WORDS and len(argv) > 1 and not argv[1].startswith("-"))):
        argv = ["ask", " ".join(argv)]
    args = parser.parse_args(argv)
    if args.command in CALENDAR_COMMANDS and not _in_bundle() and sys.platform == "darwin":
        console.print("Working on your calendar...", style="dim")
        _calendar_run(argv)
        return
    {"plan": cmd_plan, "apply": cmd_apply, "chat": cmd_chat, "check": cmd_check, "stats": cmd_stats,
     "agent": cmd_agent, "garmin": cmd_garmin, "sync": cmd_sync, "calendars": cmd_calendars, "ask": cmd_ask, "add": cmd_add, "task": cmd_task,
     "setup": cmd_web, "web": cmd_web}[args.command](args, rules, config)

if __name__ == "__main__":
    main()
