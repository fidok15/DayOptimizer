from __future__ import annotations
import argparse
import re
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
from dayoptimizer.llm.anthropic_backend import AnthropicBackend
from dayoptimizer.llm.backend import format_changes

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
    changes = plan_day(day, events, garmin, rules, now=datetime.now().astimezone(),
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

def cmd_chat(args, rules, config):
    calendar = CalendarClient()
    if not calendar.request_access():
        console.print("[red]No calendar access.[/red]")
        return
    storage = Storage(paths.db_path())
    backend = AnthropicBackend(model=config["llm"]["model"])
    console.print("[bold]DayOptimizer[/bold] — say what to do ('exit' to quit).")
    while True:
        try:
            text = console.input("[cyan]> [/cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("exit", "quit", "q"):
            break
        if not text:
            continue
        try:
            intent = backend.parse_intent(text, today=date.today().isoformat())
            day = date.fromisoformat(intent.date) if intent.date else date.today()
            if intent.action in ("plan_day", "show_plan"):
                changes, applied, errors = _run_plan(day, calendar, storage, rules)
                console.print(backend.summarize_changes(changes), markup=False)
                _print_errors(errors)
            elif intent.action == "add_event":
                start_h = intent.start_time or "16:00"
                h, m = (int(x) for x in start_h.split(":"))
                start = datetime.combine(day, time(h, m)).astimezone()
                dur = timedelta(minutes=intent.duration_minutes or 60)
                category = intent.category or "Learn"
                calendar.create_event(category, intent.title or intent.category or "Block",
                                      start, start + dur)
                console.print(f"Added {category} {start:%Y-%m-%d %H:%M}. Recomputing the day...",
                              markup=False, style="green")
                changes, _, errors = _run_plan(day, calendar, storage, rules)
                console.print(backend.summarize_changes(changes), markup=False)
                _print_errors(errors)
            elif intent.action == "move_event":
                console.print("[yellow]Moving by title is coming in V2 — for now say 'plan the day', the planner reschedules on its own.[/yellow]")
            else:
                console.print("I can: plan the day, add an event, show the plan. Try e.g. 'plan tomorrow'.")
        except Exception as exc:
            console.print(f"Something went wrong this turn ({exc}) — try again.",
                          markup=False, style="yellow")
            continue

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
        from dayoptimizer.core.garmin import garmin_login
        email = console.input("Garmin email: ").strip()
        password = getpass("Garmin password (used once, never stored): ")
        try:
            console.print(garmin_login(email, password))
        except Exception as exc:
            console.print(f"[red]Login failed: {exc}[/red]")

def cmd_stats(args, rules, config):
    from dayoptimizer.core.patterns import render_stats, suggest_adjustments, weekly_stats
    from dayoptimizer import paths
    storage = Storage(paths.db_path())
    stats = weekly_stats(storage.garmin_history(14))
    console.print(render_stats(stats))
    for tip in suggest_adjustments(stats, rules):
        console.print(f"- {tip}")

def main():
    paths.ensure_private_dir()
    load_dotenv()
    rules, config = _load_config()
    parser = argparse.ArgumentParser(prog="dayoptimizer")
    sub = parser.add_subparsers(dest="command", required=True)
    p_plan = sub.add_parser("plan", help="replan the day (or several days)")
    p_plan.add_argument("--date", default=None, help="start date (YYYY-MM-DD, defaults to today)")
    p_plan.add_argument("--week", nargs="?", const=7, type=int, default=None,
                        help="plan N days from the start date (default 7)")
    p_apply = sub.add_parser("apply", help="apply pending approval-required changes")
    p_apply.add_argument("--ids", required=True, help="comma-separated pending ids")
    sub.add_parser("chat", help="chat with the LLM")
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
    args = parser.parse_args()
    {"plan": cmd_plan, "apply": cmd_apply, "chat": cmd_chat, "check": cmd_check, "stats": cmd_stats,
     "agent": cmd_agent, "garmin": cmd_garmin}[args.command](args, rules, config)

if __name__ == "__main__":
    main()
