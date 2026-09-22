"""Recovery-aware training advice.

Garmin's recovery time says when the body is ready for the next HARD session,
not that you must sit still: easy work and a different body region stay fine.
So a routine training block is only dropped when it would load a region the
recent hard work already tired out; otherwise it is kept, at most flagged as
"keep it easy". Which region a block loads is learned from the watch's own
history (what was actually recorded during that block in past weeks), so
nothing has to be tagged by hand — and a block the watch never saw a workout
in (Work, Food, ...) is never touched.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from dayoptimizer.core.models import Activity, GarminSummary

# Garmin activity typeKey -> the body region it loads
LEG_TYPES = ("running", "trail_run", "treadmill_running", "track_running", "virtual_run",
             "hiking", "walking", "cycling", "road_biking", "mountain_biking",
             "indoor_cycling", "virtual_ride", "elliptical", "stair_climbing",
             "inline_skating", "skate_skiing", "resort_skiing", "backcountry_skiing")
UPPER_TYPES = ("swimming", "lap_swimming", "open_water_swimming", "rowing", "indoor_rowing",
               "climbing", "indoor_climbing", "bouldering")

def region_of(activity: Activity) -> str:
    """legs | upper | full — full covers strength and anything unmapped."""
    key = activity.type_key.lower()
    if any(t in key for t in LEG_TYPES):
        return "legs"
    if any(t in key for t in UPPER_TYPES):
        return "upper"
    return "full"

def was_hard(activity: Activity) -> bool:
    """Hard enough to matter for recovery: a real training effect, or long."""
    return (activity.aerobic_te >= 2.0 or activity.anaerobic_te >= 1.5
            or (activity.end - activity.start) >= timedelta(minutes=45))

def recovery_minutes_left(garmin: GarminSummary | None, now: datetime) -> int:
    """Garmin's remaining recovery time, counted down from when it was measured."""
    if garmin is None or garmin.recovery_minutes is None:
        return 0
    left = garmin.recovery_minutes
    if garmin.recovery_measured_at:
        try:
            measured = datetime.fromisoformat(garmin.recovery_measured_at).astimezone()
            left -= (now - measured).total_seconds() / 60
        except ValueError:
            pass
    return max(0, int(left))

def tired_regions(activities: list[Activity], now: datetime, hours: int = 72) -> dict[str, Activity]:
    """Regions loaded by hard work inside the recovery window: region -> the
    hardest such activity (used to explain the advice)."""
    out: dict[str, Activity] = {}
    for a in activities:
        if a.start < now - timedelta(hours=hours) or not was_hard(a):
            continue
        region = region_of(a)
        best = out.get(region)
        if best is None or a.aerobic_te + a.anaerobic_te > best.aerobic_te + best.anaerobic_te:
            out[region] = a
    return out

def block_region(activities: list[Activity], weekday: int, start_min: int, end_min: int,
                 weeks: int = 8, now: datetime | None = None) -> str | None:
    """What this routine block usually is, from the watch's history: the most
    common region of workouts recorded in its hours on that weekday. None means
    the watch never recorded a workout there, so it isn't a training block."""
    now = now or datetime.now().astimezone()
    counts: dict[str, int] = {}
    for a in activities:
        if a.start < now - timedelta(weeks=weeks) or a.start.weekday() != weekday:
            continue
        minute = a.start.hour * 60 + a.start.minute
        if start_min - 90 <= minute <= end_min:  # started around the block's hours
            region = region_of(a)
            counts[region] = counts.get(region, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda r: counts[r])

def learn_region(activities: list[Activity], typical_week: dict, weekday: int, block,
                  now: datetime | None = None) -> str | None:
    """The region a routine block loads. First its own hours on its own weekday;
    failing that (a block the user just drew), what the same category trains in
    its other blocks — so a new training block isn't mistaken for desk time."""
    own = block_region(activities, weekday, block.start, block.end, now=now)
    if own is not None:
        return own
    counts: dict[str, int] = {}
    for day, blocks in typical_week.items():
        for other in blocks:
            if other.category != block.category or (day == weekday and other.start == block.start):
                continue
            region = block_region(activities, day, other.start, other.end, now=now)
            if region:
                counts[region] = counts.get(region, 0) + 1
    return max(counts, key=lambda r: counts[r]) if counts else None

def training_advice(region: str | None, garmin: GarminSummary | None, activities: list[Activity],
                    now: datetime, lighter_hours: int = 24, skip_hours: int = 48) -> tuple[str, str]:
    """(advice, reason) for a training block, where advice is keep | easy | skip."""
    if region is None or garmin is None:
        return "keep", ""
    left = recovery_minutes_left(garmin, now)
    hours = left / 60
    battery = garmin.body_battery_start
    severe = hours >= skip_hours or (battery is not None and battery < 25)
    moderate = (hours >= lighter_hours or garmin.hrv_status == "LOW"
                or (battery is not None and battery < 40)
                or garmin.readiness_level in ("POOR", "LOW"))
    if not (severe or moderate):
        return "keep", ""
    tired = tired_regions(activities, now)
    cause = tired.get(region) or (tired.get("full") if region != "full" else None)
    if region == "full" and cause is None and tired:
        cause = max(tired.values(), key=lambda a: a.aerobic_te + a.anaerobic_te)
    state = f"{int(hours)}h of recovery left" if hours >= 1 else "recovery is low"
    if garmin.readiness_level:
        state += f", readiness {garmin.readiness_level.lower()}"
    if cause is not None:
        source = f"{cause.name or cause.type_key} on {cause.start:%a}"
        if severe:
            return "skip", f"{state} after {source} — skipping today, keep it to a walk or mobility"
        return "easy", f"{state} after {source} — keep it easy today"
    if severe:
        return "easy", f"{state} — different muscles than your recent hard work, but keep it easy"
    return "keep", ""
