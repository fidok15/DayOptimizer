from __future__ import annotations
from datetime import datetime, date, time, timedelta
from dayoptimizer.core.models import Event, GarminSummary, PlannedChange
from dayoptimizer.core.constraints import (allowed_window, explain, free_windows, gap_rule,
                                            week_rule, window_rule)
from dayoptimizer.core.recovery import learn_region, training_advice
from dayoptimizer.core.rules import Rules

# Titles of events the planner itself creates/manages. The background watcher
# (check.py) uses this to tell "foreign" events (user- or externally-added,
# meaning something changed and a replan may be warranted) from the planner's
# own churn (which would otherwise look like a new event on every sync).
PLANNER_TITLES: frozenset[str] = frozenset({
    "Breakfast", "Lunch", "Dinner", "Deep work", "Own work", "Free time",
    "Wind-down", "Sleep", "Workout",
})
# Consumers must also account for the config-dependent titles this set can't
# list statically: the custom `free_time_activity` and "Commute:" blocks.
# check.py's _is_foreign takes them as `extra`; _is_planner_managed below
# handles them for movability.

def free_slots(events, day_start, day_end):
    busy = sorted([e for e in events if e.end > day_start and e.start < day_end],
                  key=lambda e: e.start)
    slots, cursor = [], day_start
    for e in busy:
        if e.start > cursor:
            slots.append((cursor, e.start))
        cursor = max(cursor, e.end)
    if cursor < day_end:
        slots.append((cursor, day_end))
    return slots

def suggest_sleep(garmin, rules, tomorrow_first_fixed, day):
    need_hours = rules.sleep_target_hours
    reason = f"target {need_hours}h of sleep"
    causes = []
    if garmin:
        if garmin.sleep_score is not None and garmin.sleep_score < 60:
            causes.append(f"low sleep score ({garmin.sleep_score})")
        if (garmin.sleep_seconds is not None
                and garmin.sleep_seconds < rules.sleep_target_hours * 3600 * 0.9):
            h, m = divmod(garmin.sleep_seconds // 60, 60)
            causes.append(f"sleep too short ({h}h{m:02d}m)")
    if causes:
        need_hours += 0.5
        reason = " and ".join(causes) + " — adding 30 min of recovery"
    default_wake = datetime.combine(day, time(8, 0)).astimezone() + timedelta(days=1)
    if tomorrow_first_fixed is not None:
        # a late first event must not push wake-up past the default — sleeping
        # in just because the morning is empty defeats a stable rhythm
        wake = min(tomorrow_first_fixed - timedelta(minutes=rules.morning_buffer_minutes),
                   default_wake)
    else:
        wake = default_wake
    # safety floor independent of tomorrow_first_fixed: an all-day calendar
    # marker (vacation/holiday spanning midnight) or any other anomalously
    # early "fixed" anchor must never pull wake into the previous evening.
    wake_floor = datetime.combine(day + timedelta(days=1), time(5, 0)).astimezone()
    wake = max(wake, wake_floor)
    bedtime = wake - timedelta(hours=need_hours)
    return PlannedChange(kind="note", category="Sleep", title="Sleep window",
                         reason=reason, new_start=bedtime, new_end=wake)

def _find_slot(slots, duration, not_before):
    for s, e in slots:
        start = max(s, not_before)
        if e - start >= duration:
            return start
    return None

def _is_planner_managed(title: str, rules: Rules) -> bool:
    return (title in PLANNER_TITLES or title == rules.free_time_activity
            or title.startswith("Commute:") or title in rules.routine_titles)

def _effectively_movable(rules: Rules, calendar: str, title: str) -> bool:
    """A block is effectively movable if its category is movable in config OR
    the planner itself created it (recognized by title): planner-created blocks
    are always the planner's to manage, even inside a user-fixed category."""
    return rules.is_movable(calendar) or _is_planner_managed(title, rules)

def resolve_conflicts(events, rules, day_start, day_end):
    midnight = datetime.combine(day_start.date(), time(0)).astimezone()
    changes: list[PlannedChange] = []
    change_index: dict[str, int] = {}  # event_id -> index in `changes`; later bumps overwrite, not stack
    ordered = sorted(events, key=lambda e: e.start)
    placed: list[Event] = []
    # sleep pairings that were noted, not resolved (both blocks stay put):
    # excluded from further conflict search so the current event's REMAINING
    # conflicts still get resolved instead of re-finding the same pairing
    skipped: set[tuple[str, str]] = set()

    def _pair(a: Event, b: Event) -> tuple[str, str]:
        return (a.id, b.id) if a.id <= b.id else (b.id, a.id)

    def record(change: PlannedChange) -> None:
        if change.event_id is not None and change.event_id in change_index:
            changes[change_index[change.event_id]] = change
        else:
            if change.event_id is not None:
                change_index[change.event_id] = len(changes)
            changes.append(change)

    for ev in ordered:
        # ev may overlap more than one already-placed event (e.g. it spans two
        # fixed blocks); keep re-resolving until it's conflict-free or moved itself.
        # bound: each iteration either moves one placed conflict out of the way
        # or permanently skips one sleep pairing — each at most once per placed
        # event — plus one final conflict-free pass.
        for _ in range(2 * len(placed) + 1):
            # Sleep-vs-Sleep overlaps are duplicate representations of the same
            # night (e.g. one block crossing midnight, one created at 00:00 by
            # an earlier replan) — not competing blocks; never "resolve" them.
            conflict = next((p for p in placed
                             if ev.start < p.end and p.start < ev.end
                             and not (ev.calendar == "Sleep" and p.calendar == "Sleep")
                             and _pair(ev, p) not in skipped), None)
            if conflict is None:
                break
            # Sleep is nocturnal — it must never be relocated into the day. The
            # other side yields if it's movable; otherwise flag and leave both.
            if ev.calendar == "Sleep" or conflict.calendar == "Sleep":
                sleep_block = ev if ev.calendar == "Sleep" else conflict
                other = conflict if sleep_block is ev else ev
                if not _effectively_movable(rules, other.calendar, other.title):
                    record(PlannedChange(
                        kind="note", category="Sleep", title=sleep_block.title,
                        reason=(f"sleep window overlaps fixed '{other.title}' "
                                f"({other.calendar}) — sleep is never moved into "
                                "the day; user decision required"),
                        event_id=sleep_block.id, requires_approval=True))
                    # this pairing stays unresolved by design — skip it and keep
                    # resolving ev's other conflicts (a break here would
                    # silently drop them)
                    skipped.add(_pair(ev, conflict))
                    continue
                mover, stay = other, sleep_block
                requires_approval = False
            else:
                ev_movable = _effectively_movable(rules, ev.calendar, ev.title)
                other_movable = _effectively_movable(rules, conflict.calendar, conflict.title)
                # both fixed: still propose moving one of them, but gate it on approval
                requires_approval = not ev_movable and not other_movable
                # pick which one moves: the movable one; on a tie, lower priority
                if ev_movable == other_movable:
                    mover = ev if rules.priority(ev.calendar) <= rules.priority(conflict.calendar) else conflict
                else:
                    mover = ev if ev_movable else conflict
                stay = conflict if mover is ev else ev
            duration = mover.end - mover.start
            others = [p for p in placed if p is not mover] + ([ev] if mover is not ev else [])
            # the user's notes bind a moved block as much as a placed one
            others += _blocked_events(rules, day_start.date(), midnight, mover.calendar)
            # nearest free time either side: dinner 19:30 shoved to 22:30 when
            # 18:00 is free is no plan anyone would draw
            new_start = _nearest_start(others, mover.start, duration, day_start, day_end)
            moved_earlier = new_start is not None and new_start < mover.start
            if new_start is None:
                if requires_approval:
                    record(PlannedChange(
                        kind="note", category=ev.calendar, title=ev.title,
                        reason=f"conflict between two fixed events: '{conflict.title}' and '{ev.title}' — user decision required",
                        event_id=ev.id, requires_approval=True))
                else:
                    record(PlannedChange(
                        kind="note", category=mover.calendar, title=mover.title,
                        reason="no free slot left that day — not moved", event_id=mover.id))
                break
            moved = Event(id=mover.id, calendar=mover.calendar, title=mover.title,
                          start=new_start, end=new_start + duration, location=mover.location)
            if requires_approval:
                reason = (f"conflict between two fixed events: '{conflict.title}' and "
                          f"'{ev.title}' — approval required")
            else:
                reason = f"collides with '{stay.title}' ({stay.calendar})"
                if moved_earlier:
                    reason += " — moved earlier"
            record(PlannedChange(
                kind="move", category=mover.calendar, title=mover.title,
                reason=reason, event_id=mover.id, new_start=moved.start, new_end=moved.end,
                requires_approval=requires_approval))
            if mover is ev:
                ev = moved
                break
            placed.remove(conflict)
            placed.append(moved)
        placed.append(ev)
    return changes

def _window_dt(day, t):
    return datetime.combine(day, t).astimezone()

def ensure_meals(events, rules, day, now=None, day_end=None, day_start=None):
    changes = []
    food = [e for e in events if e.calendar == "Food"]
    for w in rules.meal_windows:
        ws, we = _window_dt(day, w.start), _window_dt(day, w.end)
        if now is not None and we <= now:
            continue  # window already over — don't create meals in the past
        # replan idempotency: a meal the planner already created may have been
        # shifted outside its window — a same-titled Food event anywhere today
        # still satisfies it. Untitled/user food overlapping the window counts too.
        # (relies on callers passing only the planned day's events, so a title
        # match is always a same-day meal)
        if any(e.title == w.name for e in food):
            continue
        if any(e.start < we and e.end > ws for e in food):
            continue
        duration = timedelta(minutes=w.duration_minutes)
        window_label = f"{w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')}"
        # meal windows are user habit hours; the day window still floors them —
        # nothing is planned before day_start
        not_before = max(p for p in (ws, now, day_start) if p is not None)
        start = _find_slot(free_slots(events, ws, we), duration, not_before)
        reason = f"scheduled meal — window {window_label}"
        if start is None and day_end is not None:
            # window blocked — shift the meal to the nearest slot after the window
            after = we if day_start is None else max(we, day_start)
            start = _find_slot(free_slots(events, after, day_end), duration, after)
            reason = f"window {window_label} blocked — moved right after it"
        if start is None:
            changes.append(PlannedChange(kind="note", category="Food", title=w.name,
                                         reason=f"no room for {w.name} in window {w.start}-{w.end}"))
        else:
            changes.append(PlannedChange(
                kind="create", category="Food", title=w.name, reason=reason,
                new_start=start, new_end=start + duration,
                requires_approval=not _effectively_movable(rules, "Food", w.name)))
    return changes

def adjust_gym(events, garmin, rules, day_start, day_end, now):
    if garmin is None:
        return []
    low_bb = garmin.body_battery_start is not None and garmin.body_battery_start < 40
    low_hrv = garmin.hrv_status == "LOW"
    if not (low_bb or low_hrv):
        return []
    reason = ("low Body Battery" if low_bb else "HRV below baseline") + " — training later, more recovery"
    changes = []
    for gym in [e for e in events if e.calendar == "Gym" and e.start > now]:
        duration = gym.end - gym.start
        others = [e for e in events if e.id != gym.id]
        slots = free_slots(others, day_start, day_end)
        # latest possible start within each viable slot (not just the slot's own start)
        candidates = [e - duration for s, e in slots if e - max(s, gym.end) >= duration]
        if candidates:
            new_start = max(candidates)  # latest possible slot
            changes.append(PlannedChange(kind="move", category="Gym", title=gym.title,
                                         reason=reason, event_id=gym.id,
                                         new_start=new_start, new_end=new_start + duration,
                                         requires_approval=not _effectively_movable(
                                             rules, gym.calendar, gym.title)))
        else:
            changes.append(PlannedChange(kind="note", category="Gym", title=gym.title,
                                         reason=reason + "; no later slot — consider a lighter workout or skipping",
                                         event_id=gym.id))
    return changes

def schedule_gym(events, rules, day_start, day_end, now, garmin, week_gym_count: int):
    if week_gym_count >= rules.gym_per_week:
        return []
    if any(e.calendar == "Gym" and e.start < day_end and e.end > day_start for e in events):
        return []
    if garmin is not None:
        low_bb = garmin.body_battery_start is not None and garmin.body_battery_start < 40
        low_hrv = garmin.hrv_status == "LOW"
        if low_bb or low_hrv:
            return []
    duration = timedelta(minutes=rules.gym_duration_minutes)
    cutoff = min(day_end, day_start.replace(hour=21, minute=0, second=0, microsecond=0))
    not_before = max(day_start, now)
    if cutoff <= not_before:
        return []  # workout hours entirely excluded by the day window (or already past)
    slots = free_slots(events, day_start, cutoff)
    candidates = [(max(s, not_before), e) for s, e in slots if e - max(s, not_before) >= duration]
    if not candidates:
        return []
    _, slot_end = candidates[-1]  # latest viable slot ending by the cutoff
    start = slot_end - duration
    reason = f"workout {week_gym_count + 1}/{rules.gym_per_week} this week"
    return [PlannedChange(kind="create", category="Gym", title="Workout", reason=reason,
                          new_start=start, new_end=start + duration,
                          requires_approval=not _effectively_movable(rules, "Gym", "Workout"))]

def check_free_time(events, rules, day_start, day_end):
    total_free = sum(((e - s).total_seconds() / 60 for s, e in free_slots(events, day_start, day_end)), 0)
    # explicit Free time blocks count as free, even though the calendar is "busy" there
    for e in events:
        if e.calendar == "Free time" and e.end > day_start and e.start < day_end:
            total_free += (min(e.end, day_end) - max(e.start, day_start)).total_seconds() / 60
    if total_free >= rules.min_free_minutes:
        return []
    return [PlannedChange(kind="note", category="Free time", title="Not enough free time",
                          reason=f"only {int(total_free)} min of free time (minimum {rules.min_free_minutes}) — day overloaded")]

def _pad(events, buf):
    """Copies of events grown by the inter-block buffer on both sides, so slot
    search naturally keeps breathing room around everything already planned."""
    return [Event(id=e.id, calendar=e.calendar, title=e.title,
                  start=e.start - buf, end=e.end + buf, location=e.location)
            for e in events]

def fill_day(events, rules, day_start, day_end, now, is_workday: bool = True):
    """Fill remaining free slots with a productive-day structure: wind-down
    before bed, deep-work blocks, an explicit free-time block, and — on
    workdays only — an own-work filler block. Rest days (weekends, public
    holidays) still get wind-down/deep-work/free-time structure; they just
    never get "Own work" created for them."""
    changes = []
    buf = timedelta(minutes=rules.buffer_minutes)
    start_from = max(day_start, now)
    working = list(events)

    def place(duration, category, title, reason, latest=False):
        slots = free_slots(_pad(working, buf), start_from, day_end)
        candidates = [(max(s, start_from), e) for s, e in slots
                      if e - max(s, start_from) >= duration]
        if not candidates:
            return None
        if latest:
            s, e = candidates[-1]
            start = e - duration
        else:
            start, _ = candidates[0]
        block = Event(id=f"fill:{title}:{start.isoformat()}", calendar=category,
                      title=title, start=start, end=start + duration)
        working.append(block)
        changes.append(PlannedChange(kind="create", category=category, title=title,
                                     reason=reason, new_start=start, new_end=block.end,
                                     requires_approval=not _effectively_movable(rules, category, title)))
        return block

    def place_filling_slot(min_duration, category, title, reason):
        """Like place(), but the block spans the ENTIRE free slot found
        (not just min_duration) — used for "Own work" so a long free
        afternoon becomes one continuous block instead of fixed-size
        chunks separated by the inter-block buffer."""
        slots = free_slots(_pad(working, buf), start_from, day_end)
        candidates = [(max(s, start_from), e) for s, e in slots
                      if e - max(s, start_from) >= min_duration]
        if not candidates:
            return None
        start, end = candidates[0]
        block = Event(id=f"fill:{title}:{start.isoformat()}", calendar=category,
                      title=title, start=start, end=end)
        working.append(block)
        changes.append(PlannedChange(kind="create", category=category, title=title,
                                     reason=reason, new_start=start, new_end=block.end,
                                     requires_approval=not _effectively_movable(rules, category, title)))
        return block

    # replan idempotency: blocks a previous run already created (possibly
    # shifted since) must not be created again — count them by title
    titles = [e.title for e in events]
    if "Wind-down" not in titles:
        place(timedelta(minutes=rules.wind_down_minutes), "Free time",
              "Wind-down",
              "no screens or exertion right before the sleep window", latest=True)
    for _ in range(rules.deep_work_blocks_per_day - titles.count("Deep work")):
        place(timedelta(minutes=rules.deep_work_minutes), "Learn", "Deep work",
              "focus block in a free slot")
    if rules.free_time_activity not in titles:
        place(timedelta(minutes=rules.min_free_minutes), "Free time", rules.free_time_activity,
              "guaranteed free-time minimum", latest=True)
    if is_workday:
        for _ in range(12):  # one continuous block per remaining >=60 min slot, bounded
            if place_filling_slot(timedelta(minutes=60), "Work", "Own work",
                                  "remaining large slot — personal tasks") is None:
                break
    return changes

def insert_transport(events, rules):
    changes = []
    transports = [e for e in events if e.calendar == "Transport"]
    for ev in events:
        if not ev.location or ev.calendar == "Transport":
            continue
        minutes = next((m for key, m in rules.transport_routes.items() if key.lower() in ev.location.lower()), None)
        if minutes is None:
            continue
        if any(abs((t.end - ev.start).total_seconds()) < 15 * 60 for t in transports):
            continue
        title = f"Commute: {ev.title}"
        changes.append(PlannedChange(
            kind="create", category="Transport", title=title,
            reason=f"route '{ev.location}' ({minutes} min)",
            new_start=ev.start - timedelta(minutes=minutes), new_end=ev.start,
            requires_approval=not _effectively_movable(rules, "Transport", title)))
    return changes

def _project(events, changes):
    """Return a new events list with `move`/`create` changes applied, so the
    next planning phase sees the effect of the previous one instead of the
    original (now stale) event positions."""
    by_id = {e.id: i for i, e in enumerate(events)}
    projected = list(events)
    for c in changes:
        if c.new_start is None or c.new_end is None:
            continue
        if c.kind == "move" and c.event_id is not None and c.event_id in by_id:
            old = projected[by_id[c.event_id]]
            projected[by_id[c.event_id]] = Event(
                id=old.id, calendar=old.calendar, title=old.title,
                start=c.new_start, end=c.new_end, location=old.location)
        elif c.kind == "create":
            projected.append(Event(
                id=f"planned:{c.category}:{c.new_start.isoformat()}",
                calendar=c.category, title=c.title,
                start=c.new_start, end=c.new_end))
    return projected

def _dedupe_moves(changes):
    """If multiple phases moved the same event, keep only the last move for
    that event_id (the later phase saw the more up-to-date projected state)."""
    last_move_at: dict[str, int] = {}
    for i, c in enumerate(changes):
        if c.kind == "move" and c.event_id is not None:
            last_move_at[c.event_id] = i
    return [c for i, c in enumerate(changes)
            if not (c.kind == "move" and c.event_id is not None and last_move_at[c.event_id] != i)]

def _nearest_start(events, usual, duration, lo, hi):
    """Free start closest to `usual` for a block of `duration` inside [lo, hi]."""
    best = None
    for s, e in free_slots(events, lo, hi):
        if e - s < duration:
            continue
        start = min(max(usual, s), e - duration)
        if best is None or abs(start - usual) < abs(best - usual):
            best = start
    return best

def _blocked_events(rules, day, midnight, category):
    """Pseudo-events for the times the user's notes rule out for this category:
    outside its allowed window, and any keep-free window that day. Feeding them
    to the slot search makes the notes as binding as a real calendar event."""
    earliest, latest = allowed_window(rules.note_rules, category)
    out = []
    if earliest > 0:
        out.append(Event(id="rule:early", calendar="(your notes)", title="not before",
                         start=midnight, end=midnight + timedelta(minutes=earliest)))
    if latest < 1440:
        out.append(Event(id="rule:late", calendar="(your notes)", title="not after",
                         start=midnight + timedelta(minutes=latest), end=midnight + timedelta(days=1)))
    for i, (start, end) in enumerate(free_windows(rules.note_rules, day.weekday(), category)):
        out.append(Event(id=f"rule:free{i}", calendar="(your notes)", title="keep free",
                         start=midnight + timedelta(minutes=start), end=midnight + timedelta(minutes=end)))
    return out

def place_routine(day, events, rules, now, day_start, day_end, garmin=None, activities=(),
                  history=None):
    """Put the user's routine for this weekday into the day: each block at its
    usual time when that is free. A clash moves a flexible block to the nearest
    free time (within the planning window) and only notes a fixed one; the
    user's own events always win. Idempotent: a block whose category and title
    are already on the calendar that day, or whose category already fills its
    usual time, is left alone."""
    changes: list[PlannedChange] = []
    midnight = datetime.combine(day, time(0)).astimezone()
    working = list(events)
    history = history or {}
    placed_per_category: dict[str, int] = {}
    seen_labels: dict[tuple[str, str], int] = {}
    for b in rules.typical_week.get(day.weekday(), []):
        start, end = midnight + timedelta(minutes=b.start), midnight + timedelta(minutes=b.end)
        # the Nth block with this title is already there once the day holds N of
        # them (a routine may repeat a title: work before and after lunch)
        nth = seen_labels[(b.category, b.label)] = seen_labels.get((b.category, b.label), 0) + 1
        if start < now:
            continue  # the usual time has passed (or is under way) today
        # rules the user wrote down: a broken limit drops the block with the reason
        broken = (gap_rule(rules.note_rules, b.category, day, history)
                  or week_rule(rules.note_rules, b.category, day, history,
                               placed_per_category.get(b.category, 0)))
        if broken is not None:
            changes.append(PlannedChange(kind="note", category=b.category, title=b.label,
                                         reason=f"skipped today — {explain(broken)}"))
            continue
        advice, advice_reason = "keep", ""
        if rules.respect_recovery and garmin is not None and activities:
            # only blocks the watch has seen workouts in count as training
            region = learn_region(list(activities), rules.typical_week, day.weekday(), b, now=now)
            advice, advice_reason = training_advice(
                region, garmin, list(activities), now,
                rules.recovery_lighter_hours, rules.recovery_skip_hours)
        if advice == "skip":
            changes.append(PlannedChange(kind="note", category=b.category, title=b.label,
                                         reason=advice_reason))
            continue
        same = [e for e in working if e.calendar == b.category and e.title == b.label]
        if len(same) >= nth or any(e.calendar == b.category and e.start < end and e.end > start
                                   for e in working):
            continue
        usual = f"{start:%H:%M}-{end:%H:%M}"
        blocked = _blocked_events(rules, day, midnight, b.category)
        against = working + blocked
        clash = [e for e in against if e.start < end and e.end > start]
        if not clash:
            new_start, reason = start, f"your routine ({usual})"
        elif rules.is_movable(b.category):
            search_from = max(day_start, now)
            broken_window = window_rule(rules.note_rules, b.category, b.start, b.end, day.weekday())
            new_start = _nearest_start(against, start, end - start, search_from, day_end)
            if broken_window is not None:
                reason = f"your routine has it at {usual}, but {explain(broken_window)} — nearest allowed time"
            else:
                reason = f"your routine has it at {usual}, but '{clash[0].title}' is there — nearest free time"
            if new_start is None:
                changes.append(PlannedChange(kind="note", category=b.category, title=b.label,
                                             reason=f"no free time today for your usual {usual}"))
                continue
        else:
            broken_window = window_rule(rules.note_rules, b.category, b.start, b.end, day.weekday())
            why = (explain(broken_window) if broken_window is not None
                   else f"'{clash[0].title}'")
            changes.append(PlannedChange(kind="note", category=b.category, title=b.label,
                                         reason=f"your usual {usual} clashes with {why}"))
            continue
        if advice_reason:
            reason += f" — {advice_reason}"
        new_end = new_start + (end - start)
        working.append(Event(id=f"routine:{b.label}:{new_start.isoformat()}", calendar=b.category,
                             title=b.label, start=new_start, end=new_end))
        placed_per_category[b.category] = placed_per_category.get(b.category, 0) + 1
        # the user drew this block themselves: creating it needs no approval
        changes.append(PlannedChange(kind="create", category=b.category, title=b.label, reason=reason,
                                     new_start=new_start, new_end=new_end))
    return changes

def plan_day(day, events, garmin, rules, now, tomorrow_first_fixed=None, week_gym_count: int = 0,
             next_day_events: list[Event] | None = None, is_workday: bool = True,
             activities: list | None = None, history: dict | None = None):
    day_start = _window_dt(day, rules.day_start)
    day_end = _window_dt(day, rules.day_end)
    changes: list[PlannedChange] = []
    working = events

    def run(phase_changes):
        nonlocal working
        changes.extend(phase_changes)
        working = _project(working, phase_changes)

    run(resolve_conflicts(working, rules, day_start, day_end))
    run(adjust_gym(working, garmin, rules, day_start, day_end, now))
    if rules.has_routine:
        # the user's own week replaces the generic meal/gym/sleep/filler generators
        run(place_routine(day, working, rules, now, day_start, day_end, garmin, activities or (),
                          history))
        run(insert_transport(working, rules))
        run(check_free_time(working, rules, day_start, day_end))
        return _dedupe_moves(changes)
    run(schedule_gym(working, rules, day_start, day_end, now, garmin, week_gym_count))
    run(ensure_meals(working, rules, day, now, day_end, day_start))
    run(insert_transport(working, rules))

    sleep = suggest_sleep(garmin, rules, tomorrow_first_fixed, day)
    fill_end = day_end
    if sleep:
        fill_end = min(day_end, sleep.new_start)
        # A sleep block for THIS night can sit on either side of midnight: a
        # planner-created one usually starts at/after 00:00, i.e. among the
        # NEXT day's events, outside this day's event window. Overlap-test the
        # night (the proposed window widened back to the evening onset, so a
        # same-night block ending right at midnight still counts) across both
        # days' events — otherwise every replan re-creates tonight's sleep.
        # The 20:00 onset assumes proposed bedtimes land at ~20:30 or later
        # (wake floor 05:00 minus even a stretched target), so widening only
        # ever reaches back into the evening, never into the afternoon.
        night_start = min(sleep.new_start, _window_dt(day, time(20, 0)))
        pool = working + (next_day_events or [])
        has_sleep_event = any(e.calendar == "Sleep"
                              and e.start < sleep.new_end and e.end > night_start
                              for e in pool)
        if not has_sleep_event:
            run([PlannedChange(kind="create", category="Sleep", title="Sleep",
                               reason=sleep.reason,
                               new_start=sleep.new_start, new_end=sleep.new_end,
                               requires_approval=not _effectively_movable(rules, "Sleep", "Sleep"))])
    run(fill_day(working, rules, day_start, fill_end, now, is_workday))
    run(check_free_time(working, rules, day_start, day_end))
    return _dedupe_moves(changes)
