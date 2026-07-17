from __future__ import annotations
from datetime import datetime, timedelta
from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.notify import notify
from dayoptimizer.core.planner import PLANNER_TITLES


def decide(now: datetime, today: str, garmin: GarminSummary | None,
           new_foreign_events: list[Event], state: dict[str, str]) -> list[str]:
    """Pure decision function — no I/O. Returns the actions the background
    cycle should take, in a fixed order (morning, event, stress)."""
    actions: list[str] = []

    if garmin is not None and garmin.sleep_seconds is not None and not state.get(f"morning:{today}"):
        actions.append("morning_replan")

    if new_foreign_events:
        actions.append("event_replan")

    stressed = garmin is not None and (
        (garmin.stress_avg is not None and garmin.stress_avg >= 60)
        or (garmin.body_battery_start is not None and garmin.body_battery_start < 25)
    )
    if stressed and now.hour >= 12 and not state.get(f"stress:{today}"):
        actions.append("stress_adjust")

    return actions


def _is_foreign(title: str, extra: set[str] | frozenset[str] = frozenset()) -> bool:
    return (title not in PLANNER_TITLES and title not in extra
            and not title.startswith("Commute:"))


def run_check(calendar, storage, rules, now: datetime, plan_fn=None, fetch_garmin_fn=None) -> list[str]:
    """Stateless-ish background cycle: sync a 3-day window around today,
    fetch Garmin, decide what to do, and act on it. Never touches fixed
    events without a human in the loop (confirm always denies)."""
    # Lazy import: cli.py pulls in CalendarClient/GarminClient at module load
    # time, which we don't want to pay for (or need) when unit-testing check.py
    # in isolation or running it without those services configured.
    if plan_fn is None:
        from dayoptimizer.cli import _run_plan as plan_fn
    if fetch_garmin_fn is None:
        from dayoptimizer.cli import _fetch_garmin as fetch_garmin_fn

    today_date = now.date()
    today = today_date.isoformat()

    window_start = datetime.combine(today_date - timedelta(days=1), datetime.min.time()).astimezone()
    window_end = datetime.combine(today_date + timedelta(days=2), datetime.min.time()).astimezone()
    events = calendar.list_events(window_start, window_end)
    # sync_events now reports events that are new OR rescheduled (start/end
    # changed) since last sync — e.g. the user dragging a block around in
    # Calendar. Why this can't self-trigger a replan loop: cli._run_plan
    # calls storage.sync_events() BEFORE apply_changes() applies our own
    # moves to the calendar. So the cache still holds the PRE-move
    # start/end when we sync, and only catches up on the NEXT cycle's
    # sync_events call — at which point the moved event's title is one of
    # PLANNER_TITLES (e.g. "Deep work", "Own work") and _is_foreign below
    # filters it out. A user's own edit (e.g. dragging "Standup") keeps its
    # foreign title and correctly triggers event_replan for its day.
    # Third case: the planner relocating a USER-titled movable event (e.g.
    # a personal "Bike ride" under the Gym category) also leaves a stale
    # cache entry with a foreign title — that fires ONE spurious
    # event_replan on the next cycle, which is a no-op (plan_day is
    # deterministic and the plan already reflects the move) and settles.
    changed_events = storage.sync_events(events, window_start, window_end)
    new_foreign_events = [e for e in changed_events
                          if _is_foreign(e.title, extra={rules.free_time_activity})]

    garmin = fetch_garmin_fn(storage, today)

    state = {}
    for key in (f"morning:{today}", f"stress:{today}"):
        value = storage.get_state(key)
        if value:
            state[key] = value

    actions = decide(now, today, garmin, new_foreign_events, state)

    performed: list[str] = []
    for action in actions:
        if action == "event_replan":
            # sync_events reports a given id as changed only once per actual
            # change (new or rescheduled), so every distinct day among
            # new_foreign_events must be replanned now — otherwise a day's
            # events are silently dropped forever.
            days = sorted({e.start.date() for e in new_foreign_events})
            total_applied = 0
            total_errors = 0
            reasons = []
            for day in days:
                changes, applied, errors = plan_fn(day, calendar, storage, rules,
                                                    confirm=lambda c: False)
                total_applied += len(applied)
                total_errors += len(errors)
                if changes:
                    reasons.append(changes[0].reason)
            reason = f" — {reasons[0]}" if reasons else ""
            skipped = f" ({total_errors} skipped — see recent_changes)" if total_errors else ""
            notify("DayOptimizer",
                   f"{action}: {total_applied} changes across {len(days)} days{reason}{skipped}")
        else:
            changes, applied, errors = plan_fn(today_date, calendar, storage, rules,
                                                confirm=lambda c: False)
            reason = f" — {changes[0].reason}" if changes else ""
            skipped = f" ({len(errors)} skipped — see recent_changes)" if errors else ""
            notify("DayOptimizer", f"{action}: {len(applied)} changes{reason}{skipped}")
            if action == "morning_replan":
                storage.set_state(f"morning:{today}", now.isoformat())
            elif action == "stress_adjust":
                storage.set_state(f"stress:{today}", now.isoformat())
        performed.append(action)

    return performed
