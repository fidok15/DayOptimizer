"""Shapes and thresholds here mirror real Garmin data (half marathon Sunday,
94h recovery, readiness POOR score 1, recoveryTime in MINUTES)."""
from datetime import datetime, timedelta
from dayoptimizer.core.models import Activity, GarminSummary
from dayoptimizer.core.recovery import (block_region, learn_region, recovery_minutes_left,
                                        region_of, tired_regions, training_advice)

NOW = datetime(2026, 9, 22, 7, 0).astimezone()


def _act(type_key, start, minutes=60, aerobic=3.0, anaerobic=0.0, name=""):
    return Activity(id=type_key + start.isoformat(), type_key=type_key, name=name,
                    start=start, end=start + timedelta(minutes=minutes),
                    aerobic_te=aerobic, anaerobic_te=anaerobic)


RACE = _act("running", datetime(2026, 9, 20, 15, 38).astimezone(), 116, 5.0, 0.0, "Czestochowa Running")
# measured at 07:16 with 3427 min (57h) left, exactly as the watch reported
POOR = GarminSummary(date="2026-09-22", recovery_minutes=3427, readiness_level="POOR", readiness_score=1,
                     recovery_measured_at="2026-09-22T07:16:21.0", body_battery_start=70)
FRESH = GarminSummary(date="2026-09-22", recovery_minutes=120, readiness_level="GOOD",
                      recovery_measured_at="2026-09-22T07:16:21.0", body_battery_start=80)


def test_regions_and_hardness():
    assert region_of(RACE) == "legs" and region_of(_act("strength_training", NOW)) == "full"
    assert region_of(_act("lap_swimming", NOW)) == "upper"
    assert tired_regions([RACE], NOW) == {"legs": RACE}
    assert tired_regions([_act("walking", NOW - timedelta(hours=2), 20, 0.1)], NOW) == {}  # too easy
    assert tired_regions([RACE], NOW + timedelta(days=5)) == {}  # outside the window


def test_recovery_counts_down_from_when_it_was_measured():
    assert recovery_minutes_left(POOR, datetime(2026, 9, 22, 7, 16).astimezone()) == 3427
    assert recovery_minutes_left(POOR, datetime(2026, 9, 23, 7, 16).astimezone()) == 3427 - 1440
    assert recovery_minutes_left(None, NOW) == 0


def test_same_region_is_skipped_other_region_only_eased():
    advice, reason = training_advice("legs", POOR, [RACE], NOW)
    assert advice == "skip" and "57h" in reason and "Czestochowa" in reason and "walk" in reason
    advice, reason = training_advice("upper", POOR, [RACE], NOW)
    assert advice == "easy" and "different muscles" in reason


def test_moderate_recovery_only_eases_the_same_region():
    tired = GarminSummary(date="2026-09-22", recovery_minutes=30 * 60, readiness_level="MODERATE",
                          recovery_measured_at="2026-09-22T07:16:21.0")
    assert training_advice("legs", tired, [RACE], NOW)[0] == "easy"
    assert training_advice("upper", tired, [RACE], NOW)[0] == "keep"


def test_fresh_or_unknown_block_is_left_alone():
    assert training_advice("legs", FRESH, [RACE], NOW) == ("keep", "")
    assert training_advice(None, POOR, [RACE], NOW) == ("keep", "")  # not a training block
    assert training_advice("legs", None, [], NOW) == ("keep", "")  # no Garmin


def test_block_region_is_learned_from_the_watch_history():
    mondays = [_act("strength_training", datetime(2026, 9, d, 18, 10).astimezone()) for d in (7, 14)]
    saturdays = [_act("running", datetime(2026, 9, d, 9, 5).astimezone()) for d in (5, 12)]
    history = mondays + saturdays
    assert block_region(history, 0, 18 * 60, 19 * 60 + 30, now=NOW) == "full"
    assert block_region(history, 5, 9 * 60, 10 * 60, now=NOW) == "legs"
    assert block_region(history, 2, 9 * 60, 17 * 60, now=NOW) is None  # nothing ever recorded: not training
    assert block_region([_act("running", datetime(2026, 6, 1, 9, 5).astimezone())], 0, 9 * 60, 10 * 60, now=NOW) is None


def test_new_block_inherits_what_its_category_trains():
    from dayoptimizer.core.rules import RoutineBlock
    saturday_run = RoutineBlock(9 * 60, 10 * 60, "Gym", "Long run")
    new_tuesday = RoutineBlock(18 * 60, 19 * 60, "Gym", "Evening run")
    week = {5: [saturday_run], 1: [new_tuesday]}
    history = [_act("running", datetime(2026, 9, d, 9, 10).astimezone()) for d in (5, 12)]
    # nothing was ever recorded on a Tuesday evening, but Gym means running here
    assert block_region(history, 1, 18 * 60, 19 * 60, now=NOW) is None
    assert learn_region(history, week, 1, new_tuesday, now=NOW) == "legs"
    # a category the watch never saw stays untouched (Work is not training)
    desk = RoutineBlock(9 * 60, 17 * 60, "Work", "")
    assert learn_region(history, {0: [desk]}, 0, desk, now=NOW) is None
