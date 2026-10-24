from __future__ import annotations
from datetime import datetime, date, time, timedelta
from dayoptimizer.core.models import Event, GarminSummary, PlannedChange, at, minutes
from dayoptimizer.core.constraints import (allowed_window, explain, free_windows, gap_rule, skippable,
                                            week_rule, window_rule)
from dayoptimizer.core.recovery import learn_region, training_advice
from dayoptimizer.core.rules import Rules

PLANNER_TITLES: frozenset[str] = frozenset({
    "Breakfast", "Lunch", "Dinner", "Deep work", "Own work", "Free time",
    "Wind-down", "Sleep", "Workout",
})

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
    default_wake = datetime.combine(day + timedelta(days=1), rules.day_start).astimezone()
    if tomorrow_first_fixed is not None:
        wake = min(tomorrow_first_fixed - timedelta(minutes=rules.morning_buffer_minutes),
                   default_wake)
    else:
        wake = default_wake
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

def _anchored(ev: Event) -> bool:
    """A commute belongs to the event it leads to: moving it away is meaningless."""
    return ev.calendar == "Transport" and ev.title.startswith("Commute:")

def _effectively_movable(rules: Rules, calendar: str, title: str) -> bool:
    """A block is effectively movable if its category is movable in config OR
    the planner itself created it (recognized by title): planner-created blocks
    are always the planner's to manage, even inside a user-fixed category."""
    return rules.is_movable(calendar) or _is_planner_managed(title, rules)

def resolve_conflicts(events, rules, day_start, day_end):
    midnight = datetime.combine(day_start.date(), time(0)).astimezone()
    changes: list[PlannedChange] = []
    change_index: dict[str, int] = {}
    ordered = sorted(events, key=lambda e: e.start)
    placed: list[Event] = []
    skipped: set[tuple[str, str]] = set()

    def _pair(a: Event, b: Event) -> tuple[str, str]:
        return (a.id, b.id) if a.id <= b.id else (b.id, a.id)

    def record(change: PlannedChange) -> None:
        if change.event_id is not None and change.event_id in change_index:
            earlier = changes[change_index[change.event_id]]
            if earlier.kind == change.kind == "move" and not change.requires_approval:
                change.reason = earlier.reason.removesuffix(" — moved earlier")
            changes[change_index[change.event_id]] = change
        else:
            if change.event_id is not None:
                change_index[change.event_id] = len(changes)
            changes.append(change)

    for ev in ordered:
        for _ in range(2 * len(placed) + 1):
            conflict = next((p for p in placed
                             if ev.start < p.end and p.start < ev.end
                             and not (ev.calendar == "Sleep" and p.calendar == "Sleep")
                             and _pair(ev, p) not in skipped), None)
            if conflict is None:
                break
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
                    skipped.add(_pair(ev, conflict))
                    continue
                mover, stay = other, sleep_block
                requires_approval = False
            elif _anchored(ev) != _anchored(conflict):
                mover = conflict if _anchored(ev) else ev
                stay = ev if mover is conflict else conflict
                requires_approval = not _effectively_movable(rules, mover.calendar, mover.title)
            else:
                ev_movable = _effectively_movable(rules, ev.calendar, ev.title)
                other_movable = _effectively_movable(rules, conflict.calendar, conflict.title)
                requires_approval = not ev_movable and not other_movable
                if ev_movable == other_movable:
                    mover = ev if rules.priority(ev.calendar) <= rules.priority(conflict.calendar) else conflict
                else:
                    mover = ev if ev_movable else conflict
                stay = conflict if mover is ev else ev
            duration = mover.end - mover.start
            others = [p for p in placed if p is not mover] + ([ev] if mover is not ev else [])
            others += _blocked_events(rules, day_start.date(), midnight, mover.calendar)
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
            continue
        if any(e.title == w.name for e in food):
            continue
        if any(e.start < we and e.end > ws for e in food):
            continue
        duration = timedelta(minutes=w.duration_minutes)
        window_label = f"{w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')}"
        not_before = max(p for p in (ws, now, day_start) if p is not None)
        start = _find_slot(free_slots(events, ws, we), duration, not_before)
        reason = f"scheduled meal — window {window_label}"
        if start is None and day_end is not None:
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
        candidates = [e - duration for s, e in slots if e - max(s, gym.end) >= duration]
        if candidates:
            new_start = max(candidates)
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
        return []
    slots = free_slots(events, day_start, cutoff)
    candidates = [(max(s, not_before), e) for s, e in slots if e - max(s, not_before) >= duration]
    if not candidates:
        return []
    _, slot_end = candidates[-1]
    start = slot_end - duration
    reason = f"workout {week_gym_count + 1}/{rules.gym_per_week} this week"
    return [PlannedChange(kind="create", category="Gym", title="Workout", reason=reason,
                          new_start=start, new_end=start + duration,
                          requires_approval=not _effectively_movable(rules, "Gym", "Workout"))]

def check_free_time(events, rules, day_start, day_end):
    total_free = sum(((e - s).total_seconds() / 60 for s, e in free_slots(events, day_start, day_end)), 0)
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

    def place(duration, category, title, reason, latest=False, at_end=False):
        slots = free_slots(_pad(working, buf), start_from, day_end)
        candidates = [(max(s, start_from), e) for s, e in slots
                      if e - max(s, start_from) >= duration
                      and (not at_end or e >= day_end - buf)]
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

    titles = [e.title for e in events]
    if "Wind-down" not in titles:
        place(timedelta(minutes=rules.wind_down_minutes), "Free time",
              "Wind-down",
              "no screens or exertion right before the sleep window", latest=True, at_end=True)
    for _ in range(rules.deep_work_blocks_per_day - titles.count("Deep work")):
        place(timedelta(minutes=rules.deep_work_minutes), "Learn", "Deep work",
              "focus block in a free slot")
    if rules.free_time_activity not in titles:
        place(timedelta(minutes=rules.min_free_minutes), "Free time", rules.free_time_activity,
              "guaranteed free-time minimum", latest=True)
    if is_workday:
        for _ in range(12):
            if place_filling_slot(timedelta(minutes=60), "Work", "Own work",
                                  "remaining large slot — personal tasks") is None:
                break
    return changes

def insert_transport(events, rules):
    """A trip to each place before the day's first event there and one back
    after its last: classes back to back on campus need no commute between
    them. A route in transport_routes names a category ("School: 45")
    or part of an address ("Main Street: 45"). Trips already in the
    Transport calendar (from an earlier replan) are not added again."""
    changes = []
    transports = [e for e in events if e.calendar == "Transport"]
    visits: dict[str, list[Event]] = {}
    for ev in sorted(events, key=lambda e: e.start):
        if ev.calendar == "Transport":
            continue
        key = next((k for k in rules.transport_routes
                    if k.lower() == ev.calendar.lower()
                    or (ev.location and k.lower() in ev.location.lower())), None)
        if key is not None:
            visits.setdefault(key, []).append(ev)
    near = timedelta(minutes=15)
    for key, evs in visits.items():
        trip = timedelta(minutes=rules.transport_routes[key])
        first, last = evs[0], max(evs, key=lambda e: e.end)
        for title, start, end in ((f"Commute: {first.title}", first.start - trip, first.start),
                                  (f"Commute: back from {last.title}", last.end, last.end + trip)):
            if any(t.start < end + near and t.end > start - near for t in transports):
                continue
            changes.append(PlannedChange(
                kind="create", category="Transport", title=title,
                reason=f"route '{key}' ({rules.transport_routes[key]} min)",
                new_start=start, new_end=end,
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
                         start=midnight, end=at(midnight, earliest)))
    if latest < 1440:
        out.append(Event(id="rule:late", calendar="(your notes)", title="not after",
                         start=at(midnight, latest), end=at(midnight, 1440)))
    for i, (start, end) in enumerate(free_windows(rules.note_rules, day.weekday(), category)):
        out.append(Event(id=f"rule:free{i}", calendar="(your notes)", title="keep free",
                         start=at(midnight, start), end=at(midnight, end)))
    return out

def enforce_notes(day, events, rules, now, day_start, day_end):
    """Blocks the planner placed that now break the user's notes (a rule added
    later, an older plan) move to the nearest allowed time. What the user put
    on the calendar themselves, or a fixed category, is theirs to change."""
    changes: list[PlannedChange] = []
    midnight = datetime.combine(day, time(0)).astimezone()
    working = list(events)
    for ev in sorted(events, key=lambda e: e.start):
        if ev.start < now or not (rules.is_movable(ev.calendar) and _is_planner_managed(ev.title, rules)):
            continue
        broken = window_rule(rules.note_rules, ev.calendar, minutes(midnight, ev.start),
                             minutes(midnight, ev.end), day.weekday())
        if broken is None:
            continue
        others = [e for e in working if e.id != ev.id] + _blocked_events(rules, day, midnight, ev.calendar)
        new_start = _nearest_start(others, ev.start, ev.end - ev.start, max(day_start, now), day_end)
        if new_start is None:
            changes.append(PlannedChange(kind="note", category=ev.calendar, title=ev.title, event_id=ev.id,
                                         reason=f"breaks {explain(broken)}, and there is no allowed time left today"))
            continue
        moved = Event(id=ev.id, calendar=ev.calendar, title=ev.title, start=new_start,
                      end=new_start + (ev.end - ev.start), location=ev.location)
        working = [moved if e.id == ev.id else e for e in working]
        changes.append(PlannedChange(kind="move", category=ev.calendar, title=ev.title, event_id=ev.id,
                                     new_start=moved.start, new_end=moved.end,
                                     reason=f"{explain(broken)} — nearest allowed time"))
    return changes

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
    routine = rules.typical_week.get(day.weekday(), [])
    upcoming = [Event(id=f"routine-slot:{i}", calendar=o.category, title=o.label,
                      start=at(midnight, o.start), end=at(midnight, o.end))
                for i, o in enumerate(routine) if at(midnight, o.start) >= now]
    for b in routine:
        start, end = at(midnight, b.start), at(midnight, b.end)
        nth = seen_labels[(b.category, b.label)] = seen_labels.get((b.category, b.label), 0) + 1
        if start < now:
            continue
        broken = (gap_rule(rules.note_rules, b.category, day, history)
                  or week_rule(rules.note_rules, b.category, day, history,
                               placed_per_category.get(b.category, 0)))
        if broken is not None:
            changes.append(PlannedChange(kind="note", category=b.category, title=b.label,
                                         reason=f"skipped today — {explain(broken)}"))
            continue
        advice, advice_reason = "keep", ""
        if rules.respect_recovery and garmin is not None and activities:
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
            held = [e for e in upcoming if not (e.calendar == b.category and e.title == b.label
                                                and e.start == start)
                    and (e.calendar == "Sleep" or rules.priority(e.calendar) >= rules.priority(b.category))]
            new_start = _nearest_start(against + held, start, end - start, search_from, day_end)
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
        changes.append(PlannedChange(kind="create", category=b.category, title=b.label, reason=reason,
                                     new_start=new_start, new_end=new_end))
    return changes

def plan_day(day, events, garmin, rules, now, tomorrow_first_fixed=None, week_gym_count: int = 0,
             next_day_events: list[Event] | None = None, is_workday: bool = True,
             activities: list | None = None, history: dict | None = None):
    day_start = _window_dt(day, rules.day_start)
    day_end = _window_dt(day, rules.day_end)
    changes: list[PlannedChange] = []
    working = [e for e in events if not skippable(rules.note_rules, e)]

    def run(phase_changes):
        nonlocal working
        phase_changes = [c for c in phase_changes
                         if c.kind != "create" or c.category in rules.categories]
        changes.extend(phase_changes)
        working = _project(working, phase_changes)

    run(resolve_conflicts(working, rules, day_start, day_end))
    run(enforce_notes(day, working, rules, now, day_start, day_end))
    run(adjust_gym(working, garmin, rules, day_start, day_end, now))
    if rules.has_routine:
        run(insert_transport(working, rules))
        run(place_routine(day, working, rules, now, day_start, day_end, garmin, activities or (),
                          history))
        run(check_free_time(working, rules, day_start, day_end))
        return _dedupe_moves(changes)
    run(schedule_gym(working, rules, day_start, day_end, now, garmin, week_gym_count))
    run(ensure_meals(working, rules, day, now, day_end, day_start))
    run(insert_transport(working, rules))

    sleep = suggest_sleep(garmin, rules, tomorrow_first_fixed, day)
    fill_end = day_end
    if sleep:
        fill_end = min(day_end, sleep.new_start)
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
