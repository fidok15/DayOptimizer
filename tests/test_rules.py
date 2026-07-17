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
    assert rules.gym_per_week >= 1  # non-overridden keys survive the merge

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
    assert rules.is_movable("Meeting") is False  # defaults still present


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
    # simulate an old config predating day_start/day_end
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
    # validate_config only sees the user's snippet, so a partial override can
    # merge into an inverted window; load_rules must keep the planner
    # functional (background runs) by reverting to the defaults, not raising
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    (tmp_path / "config.local.yaml").write_text(
        "day_rules:\n  day_start: '22:00'\n  day_end: '05:00'\n")
    rules = load_rules(CONFIG)
    assert rules.day_start == time(6, 0)
    assert rules.day_end == time(23, 0)
