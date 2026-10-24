from datetime import time
from pathlib import Path
import pytest
from dayoptimizer.core.rules import load_rules

CONFIG = Path(__file__).parent / "fixtures" / "config.yaml"

def test_fixed_and_flexible_categories():
    rules = load_rules(CONFIG)
    for cat in ["Important", "Meeting", "Work"]:
        assert not rules.is_movable(cat), f"{cat} must be fixed"
    for cat in ["Gym", "Food", "Free time", "Learn", "Sleep", "Transport"]:
        assert rules.is_movable(cat), f"{cat} must be movable"

def test_unknown_category_defaults_to_fixed():
    rules = load_rules(CONFIG)
    assert not rules.is_movable("BrandNewCategory")

def test_day_rules_present():
    rules = load_rules(CONFIG)
    assert rules.gym_per_week >= 1
    assert rules.min_free_minutes > 0
    assert len(rules.meal_windows) >= 2
    assert rules.meal_windows[0].start < rules.meal_windows[0].end

def test_config_local_overrides_base(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    (tmp_path / "config.local.yaml").write_text(
        "day_rules:\n  buffer_minutes: 0\n  free_time_activity: Reading\n")
    rules = load_rules(CONFIG)
    assert rules.buffer_minutes == 0
    assert rules.free_time_activity == "Reading"
    assert rules.gym_per_week >= 1

def test_no_local_file_keeps_defaults():
    rules = load_rules(CONFIG)
    assert rules.buffer_minutes == 15


def test_user_config_from_app_dir_overrides_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    (tmp_path / "config.local.yaml").write_text(
        "categories:\n  Climbing: {movable: true, priority: 5}\n"
        "day_rules:\n  gym_per_week: 2\n")
    rules = load_rules(Path("tests/fixtures/config.yaml"))
    assert rules.gym_per_week == 2
    assert rules.is_movable("Climbing") is True
    assert rules.is_movable("Meeting") is False


def test_explicit_user_path_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path / "ignored"))
    override = tmp_path / "override.yaml"
    override.write_text("day_rules:\n  min_free_minutes: 120\n")
    rules = load_rules(Path("tests/fixtures/config.yaml"), user_path=override)
    assert rules.min_free_minutes == 120


def test_day_start_end_parsed_from_config():
    rules = load_rules(CONFIG)
    assert rules.day_start == time(6, 0)
    assert rules.day_end == time(23, 0)


def test_day_start_end_default_when_keys_absent(tmp_path):
    lines = [l for l in CONFIG.read_text().splitlines()
             if "day_start" not in l and "day_end" not in l]
    old_config = tmp_path / "old_config.yaml"
    old_config.write_text("\n".join(lines))
    rules = load_rules(old_config)
    assert rules.day_start == time(6, 0)
    assert rules.day_end == time(23, 0)


def test_day_start_end_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    (tmp_path / "config.local.yaml").write_text(
        "day_rules:\n  day_start: '07:00'\n  day_end: '22:00'\n")
    rules = load_rules(CONFIG)
    assert rules.day_start == time(7, 0)
    assert rules.day_end == time(22, 0)


def test_work_days_default_when_absent():
    rules = load_rules(CONFIG)
    assert rules.work_days == frozenset({0, 1, 2, 3, 4})


def _with_work_days(value: str, tmp_path, name="custom_config.yaml"):
    lines = [l for l in CONFIG.read_text().splitlines() if "work_days" not in l]
    out = []
    for l in lines:
        out.append(l)
        if l.strip() == "day_rules:":
            out.append(f"  work_days: {value}")
    custom = tmp_path / name
    custom.write_text("\n".join(out))
    return custom


def test_work_days_parsed_from_config(tmp_path):
    custom = _with_work_days("[sat, sun]", tmp_path)
    rules = load_rules(custom)
    assert rules.work_days == frozenset({5, 6})


def test_work_days_invalid_name_raises_readable_error(tmp_path):
    custom = _with_work_days("[funday]", tmp_path, name="bad_config.yaml")
    with pytest.raises(ValueError) as e:
        load_rules(custom)
    msg = str(e.value)
    assert "funday" in msg
    for name in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        assert name in msg


def test_holiday_calendars_default_when_absent():
    rules = load_rules(CONFIG)
    assert rules.holiday_calendars == ["Public Holidays", "Holidays"]


def test_holiday_calendars_parsed_from_config(tmp_path):
    lines = [l for l in CONFIG.read_text().splitlines() if "holiday_calendars" not in l]
    lines.append('holiday_calendars: ["Święta"]')
    custom = tmp_path / "custom_holidays.yaml"
    custom.write_text("\n".join(lines))
    rules = load_rules(custom)
    assert rules.holiday_calendars == ["Święta"]


def test_inverted_day_window_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    (tmp_path / "config.local.yaml").write_text(
        "day_rules:\n  day_start: '22:00'\n  day_end: '05:00'\n")
    rules = load_rules(CONFIG)
    assert rules.day_start == time(6, 0)
    assert rules.day_end == time(23, 0)

def test_awake_is_between_the_nights_sleep_drawn_in_the_routine():
    from dataclasses import replace
    from datetime import date
    from dayoptimizer.core.rules import CategoryRule, RoutineBlock
    rules = load_rules(CONFIG)
    rules = replace(rules, categories={**rules.categories, "Rest": CategoryRule(movable=False, priority=5)},
                    typical_week={0: [RoutineBlock(0, 390, "Free time", "Sleep", protected=True),
                                      RoutineBlock(1350, 1440, "Rest", "Sleep")]})
    # the Monday sleep ends 06:30 (protected) and starts 22:30 (fixed category), whatever it is called
    assert rules.awake(date(2030, 10, 14)) == (time(6, 30), time(22, 30))
    # a day with no night drawn: the day window from the config
    assert rules.awake(date(2030, 10, 15)) == (rules.day_start, rules.day_end)


def test_routine_times_keep_the_clock_on_the_day_the_clocks_change(monkeypatch):
    import time as clock
    from datetime import date, datetime, timedelta
    from dayoptimizer.core.models import at, minutes
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    clock.tzset()
    try:
        midnight = datetime.combine(date(2026, 10, 25), time(0)).astimezone()  # 03:00 back to 02:00
        gym = at(midnight, 18 * 60 + 30)
        assert gym.strftime("%H:%M %z") == "18:30 +0100"
        assert minutes(midnight, gym) == 18 * 60 + 30
        assert at(midnight, 1440) == datetime.combine(date(2026, 10, 26), time(0)).astimezone()
        assert gym - midnight == timedelta(hours=19, minutes=30)  # elapsed time is an hour more
    finally:
        monkeypatch.undo()
        clock.tzset()
