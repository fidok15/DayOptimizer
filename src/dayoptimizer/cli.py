from __future__ import annotations
import argparse
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from dayoptimizer import paths
from dayoptimizer.apply import apply_changes
from dayoptimizer.core.calendar import CalendarClient
from dayoptimizer.core.garmin import summarize
from dayoptimizer.core.planner import plan_day
from dayoptimizer.core.rules import load_config_data, load_rules
from dayoptimizer.core.storage import Storage
from dayoptimizer.llm.backend import LLMUnavailable, format_changes, make_backend, resolve_day

console = Console()

def _load_config():
    cfg_path = Path(__file__).parent.parent.parent / "config.default.yaml"
    return load_rules(cfg_path), load_config_data(cfg_path)

def _fetch_garmin(storage, day: str):
    from dayoptimizer.core.garmin import GarminClient, GarminNotConfigured, garmin_configured
    if not garmin_configured():
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
    prompt = f"Fixed-event change: {change.category}: {change.title} — {change.reason}. Approve? [y/N] "
    try:
        answer = console.input(prompt, markup=False)
    except (EOFError, KeyboardInterrupt):
        return False  # no interactive stdin (bundle/background run) — park as pending
    return answer.strip().lower() in ("y", "yes")

def _run_plan(day: date, calendar, storage, rules, confirm=None):
    confirm = confirm if confirm is not None else _confirm
    day_start = datetime.combine(day, time(0)).astimezone()
    events_raw = calendar.list_events(day_start, day_start + timedelta(days=1))
    tomorrow_raw = calendar.list_events(day_start + timedelta(days=1), day_start + timedelta(days=2))
    # all-day events are calendar MARKERS (vacations, holidays, birthdays),
    # not time occupiers: they must never be busy time, a scheduling anchor,
    # or counted toward the weekly gym quota — but the cache (sync_events)
    # keeps seeing them unfiltered, since they are real calendar entries.
    events = [e for e in events_raw if not e.all_day]
    tomorrow = [e for e in tomorrow_raw if not e.all_day]
    tomorrow_fixed = [e for e in tomorrow if not rules.is_movable(e.calendar)]
    # a holiday makes the day a non-work day regardless of work_days: an
    # all-day event's `end` from EventKit may be modeled either as next-day
    # 00:00 (exclusive) or as day 23:59 (inclusive). Naively taking end.date()
    # would off-by-one the exclusive shape (a single-day holiday on `day`
    # with end == day+1 00:00 would spuriously cover day+1 too) — normalize
    # an exact-midnight end back one day so both shapes yield the event's
    # true last covered day.
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
    # what each category already did in the days before: needed for the user's
    # own rules ("no training two days in a row", "gym at most 3x a week")
    past = calendar.list_events(day_start - timedelta(days=8), day_start)
    history: dict[str, list[date]] = {}
    for e in past:
        if not e.all_day:
            history.setdefault(e.calendar, []).append(e.start.date())
    changes = plan_day(day, events, garmin, rules, now=now,
                       activities=_fetch_activities(storage, now), history=history,
                       tomorrow_first_fixed=min((e.start for e in tomorrow_fixed), default=None),
                       week_gym_count=week_gym_count,
                       # tonight's sleep usually starts after midnight — the planner
                       # needs tomorrow's events to see it already exists on replan
                       next_day_events=tomorrow,
                       is_workday=is_workday)
    applied, errors = apply_changes(changes, calendar, storage, confirm)
    return changes, applied, errors

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
        console.print("[red]No calendar access. Enable it in System Settings → Privacy & Security → Calendars.[/red]")
        return
    storage = Storage(paths.db_path())
    start_day = date.fromisoformat(args.date) if args.date else date.today()
    days = args.week if args.week else 1
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        if days > 1:
            console.print(f"\n[bold]=== {day:%A %Y-%m-%d} ===[/bold]")
        changes, applied, errors = _run_plan(day, calendar, storage, rules)
        console.print(format_changes(changes), markup=False)  # titles are untrusted text
        console.print(f"[green]Applied {len(applied)} changes.[/green]")
        _print_errors(errors)
    _print_pending(storage)

def cmd_apply(args, rules, config):
    calendar = CalendarClient()
    if not calendar.request_access():
        console.print("[red]No calendar access.[/red]")
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
            storage.log_change(
                f"[error] apply #{pid} {c.kind} {c.category}: {c.title}",
                f"calendar '{c.category}' not found — create or rename a calendar "
                "with this name in the Calendar app")
            console.print(f"#{pid} failed: calendar '{c.category}' not found — "
                          "create it and re-run the plan", markup=False)
            continue
        storage.log_change(f"[applied #{pid}] {c.kind} {c.category}: {c.title}", c.reason)
        applied += 1
    # failed rows are removed as well: they cannot succeed until the user
    # creates the calendar, and a later replan regenerates the proposal
    storage.delete_pending([pid for pid, _ in pending])
    console.print(f"Applied {applied} of {len(pending)} pending change(s).")

def cmd_check(args, rules, config):
    from dayoptimizer.check import run_check
    calendar = CalendarClient()
    if not calendar.request_access():
        console.print("[red]No calendar access. Enable it in System Settings → Privacy & Security → Calendars.[/red]")
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
    to_create, problems = events_to_create(req, rules.categories, now.date())
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
        console.print(_calendar_run(["add", payload]), markup=False)

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
        console.print("[red]No calendar access. Enable it in System Settings → Privacy & Security → Calendars.[/red]")
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
        changes, applied, errors = _run_plan(day, calendar, storage, rules)
        if len(days) > 1:
            console.print(f"\n{day:%A %Y-%m-%d}", style="bold")
        console.print(summarize(changes), markup=False)
        _print_errors(errors)
    _print_pending(storage)

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
        console.print(agent.install(args.interval))
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
    which cannot touch EventKit itself). Prints SYNCED n or NO_ACCESS for the caller."""
    calendar = CalendarClient()
    if not calendar.request_access():
        print("NO_ACCESS")
        return
    start = datetime.combine(date.fromisoformat(args.start), time(0, 0)).astimezone()
    end = start + timedelta(days=args.days)
    events = calendar.list_events(start, end)
    Storage(paths.db_path()).sync_events(events, start, end)
    print(f"SYNCED {len(events)}")

def cmd_calendars(args, rules, config):
    """Create a calendar in the Calendar app for every category that lacks one.
    Prints CREATED <names> / FAILED <name>: <why> lines for the caller."""
    calendar = CalendarClient()
    if not calendar.request_access():
        print("NO_ACCESS")
        return
    created = []
    for name, cat in config["categories"].items():
        try:
            if calendar.ensure_calendar(name, (cat or {}).get("color")):
                created.append(name)
        except KeyError as exc:
            print(f"FAILED {name}: {exc}")
    print("CREATED " + "\t".join(created))

def cmd_web(args, rules, config):
    from dayoptimizer.web import serve
    serve(port=args.port, open_browser=not args.no_open)

# Commands that read or write the calendar. macOS only lets the DayOptimizer app
# bundle do that (TCC), so from a terminal they are re-run inside the bundle.
CALENDAR_COMMANDS = {"plan", "apply", "check", "sync", "add", "calendars"}

def _in_bundle() -> bool:
    return "DayOptimizer.app" in sys.executable

def _calendar_run(argv: list[str]) -> str:
    from dayoptimizer.mcp_server import _bundle_run
    exe = paths.ensure_private_dir() / "DayOptimizer.app" / "Contents" / "MacOS" / "dayopt"
    if not exe.exists():
        return ("DayOptimizer isn't set up for calendar access yet. In the DayOptimizer "
                "folder run:  scripts/install.sh")
    # cli_args is one argument per line: keep each argument on one line
    return _bundle_run([a.replace("\n", " ") for a in argv]).rstrip()

def _first_run() -> bool:
    """No typical week drawn yet: the user hasn't done the setup."""
    from dayoptimizer.web import _local
    try:
        return not _local().get("typical_week")
    except Exception:
        return False

def main(argv: list[str] | None = None):
    paths.ensure_private_dir()
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
    rules, config = _load_config()
    parser = argparse.ArgumentParser(
        prog="dayoptimizer",
        description='dayoptimizer                optimize today around your calendar\n'
                    'dayoptimizer "<your day>"   e.g. "meeting at 14:00 for about an hour, then gym"\n'
                    'dayoptimizer setup          describe your typical week in the browser (first run)',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", metavar="command")
    p_plan = sub.add_parser("plan", help="replan the day (or several days)")
    p_plan.add_argument("--date", default=None, help="start date (YYYY-MM-DD, defaults to today)")
    p_plan.add_argument("--week", nargs="?", const=7, type=int, default=None,
                        help="plan N days from the start date (default 7)")
    p_apply = sub.add_parser("apply", help="apply pending approval-required changes")
    p_apply.add_argument("--ids", required=True, help="comma-separated pending ids")
    sub.add_parser("chat", help="keep telling DayOptimizer about your day, one line at a time")
    p_ask = sub.add_parser("ask", help='add what you say to the calendar and replan (same as dayoptimizer "...")')
    p_ask.add_argument("text")
    p_add = sub.add_parser("add")  # internal: ask hands confirmed events to the app bundle
    p_add.add_argument("events")
    sub.add_parser("check", help="stateless background cycle (sleep, new events, stress)")
    sub.add_parser("stats", help="14-day Garmin trends and suggestions")
    p_agent = sub.add_parser("agent", help="manage the background agent (launchd)")
    agent_sub = p_agent.add_subparsers(dest="agent_command", required=True)
    p_agent_install = agent_sub.add_parser("install", help="install and start the agent")
    p_agent_install.add_argument("--interval", type=int, default=900,
                                 help="run interval in seconds (default 900)")
    agent_sub.add_parser("uninstall", help="stop and remove the agent")
    agent_sub.add_parser("status", help="agent status")
    p_garmin = sub.add_parser("garmin", help="Garmin Connect account")
    garmin_sub = p_garmin.add_subparsers(dest="garmin_command", required=True)
    garmin_sub.add_parser("login", help="log in and store OAuth tokens (password is not persisted)")
    sub.add_parser("calendars", help="create a calendar in the Calendar app for each category")
    p_sync = sub.add_parser("sync", help="copy calendar events into the local cache")
    p_sync.add_argument("--from", dest="start", required=True, help="first day (YYYY-MM-DD)")
    p_sync.add_argument("--days", type=int, default=7)
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
    elif not first.startswith("-") and first not in sub.choices:
        argv = ["ask", " ".join(argv)]  # plain words: dayoptimizer "gym at 18"
    args = parser.parse_args(argv)
    if args.command in CALENDAR_COMMANDS and not _in_bundle() and sys.platform == "darwin":
        console.print("Working on your calendar...", style="dim")
        console.print(_calendar_run(argv), markup=False)
        return
    {"plan": cmd_plan, "apply": cmd_apply, "chat": cmd_chat, "check": cmd_check, "stats": cmd_stats,
     "agent": cmd_agent, "garmin": cmd_garmin, "sync": cmd_sync, "calendars": cmd_calendars, "ask": cmd_ask, "add": cmd_add,
     "setup": cmd_web, "web": cmd_web}[args.command](args, rules, config)

if __name__ == "__main__":
    main()
