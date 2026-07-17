import stat
import pytest
from dayoptimizer.onboarding import ConfigError, save_user_config, validate_config

GOOD = """\
categories:
  Gym: {movable: true, priority: 5}
  Choir: {movable: false, priority: 7}
day_rules:
  gym_per_week: 2
  sleep_target_hours: 7.5
  meal_windows:
    - {name: "Breakfast", start: "07:30", end: "09:30", duration_minutes: 20}
transport_routes:
  office: 25
"""


def test_validate_good_config():
    cfg = validate_config(GOOD)
    assert cfg.categories["Choir"].movable is False
    assert cfg.day_rules.gym_per_week == 2
    assert cfg.transport_routes["office"] == 25


def test_unknown_keys_rejected():
    with pytest.raises(ConfigError) as e:
        validate_config("categories:\n  Gym: {movable: true, hackerz: 1}\n")
    assert "hackerz" in str(e.value)


def test_bad_time_format_rejected():
    bad = 'day_rules:\n  meal_windows:\n    - {name: "X", start: "7am", end: "09:00", duration_minutes: 20}\n'
    with pytest.raises(ConfigError):
        validate_config(bad)


def test_not_a_mapping_rejected():
    with pytest.raises(ConfigError):
        validate_config("- just\n- a list\n")


def test_category_name_limits():
    with pytest.raises(ConfigError):
        validate_config(f"categories:\n  '{'x' * 100}': {{movable: true}}\n")


def test_all_problems_reported_in_one_error():
    bad = (
        f"categories:\n  '{'x' * 100}': {{movable: true}}\n"
        "day_rules:\n"
        "  meal_windows:\n"
        '    - {name: "X", start: "7am", end: "09:00", duration_minutes: 20}\n'
    )
    with pytest.raises(ConfigError) as e:
        validate_config(bad)
    msg = str(e.value)
    assert "Invalid category name" in msg
    assert "start" in msg


def test_transport_route_value_bounds():
    with pytest.raises(ConfigError):
        validate_config("transport_routes: {office: 9999}\n")
    with pytest.raises(ConfigError):
        validate_config("transport_routes: {office: -5}\n")
    cfg = validate_config("transport_routes: {office: 25}\n")
    assert cfg.transport_routes["office"] == 25


def test_save_rejects_path_kwarg():
    with pytest.raises(TypeError):
        save_user_config(GOOD, path="/tmp/elsewhere.yaml")


def test_save_writes_0600_into_app_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    msg = save_user_config(GOOD)
    target = tmp_path / "config.local.yaml"
    assert target.exists()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert str(target) in msg


def test_save_rejects_invalid_without_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    with pytest.raises(ConfigError):
        save_user_config("categories: {Gym: {movable: 'maybe'}}")
    assert not (tmp_path / "config.local.yaml").exists()


def test_day_start_end_accepted():
    cfg = validate_config("day_rules:\n  day_start: '06:30'\n  day_end: '22:30'\n")
    assert cfg.day_rules.day_start == "06:30"
    assert cfg.day_rules.day_end == "22:30"


def test_day_start_end_bad_format_rejected():
    with pytest.raises(ConfigError):
        validate_config("day_rules:\n  day_start: '6am'\n")


def test_day_start_after_day_end_rejected():
    with pytest.raises(ConfigError) as e:
        validate_config("day_rules:\n  day_start: '22:00'\n  day_end: '06:00'\n")
    msg = str(e.value)
    assert "day_start" in msg and "day_end" in msg


def test_work_days_accepted():
    cfg = validate_config("day_rules:\n  work_days: [mon, tue, wed, thu, fri]\n")
    assert cfg.day_rules.work_days == ["mon", "tue", "wed", "thu", "fri"]


def test_work_days_bad_name_rejected_with_valid_names_listed():
    with pytest.raises(ConfigError) as e:
        validate_config("day_rules:\n  work_days: [funday]\n")
    msg = str(e.value)
    assert "funday" in msg
    for name in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        assert name in msg


def test_holiday_calendars_accepted():
    cfg = validate_config('holiday_calendars: ["Public Holidays", "Świeta"]\n')
    assert cfg.holiday_calendars == ["Public Holidays", "Świeta"]


def test_holiday_calendars_too_many_rejected():
    names = "\n".join(f'  - "Cal{i}"' for i in range(11))
    with pytest.raises(ConfigError):
        validate_config(f"holiday_calendars:\n{names}\n")


def test_holiday_calendars_name_too_long_rejected():
    with pytest.raises(ConfigError):
        validate_config(f'holiday_calendars: ["{"x" * 61}"]\n')


def test_holiday_calendars_empty_name_rejected():
    with pytest.raises(ConfigError):
        validate_config('holiday_calendars: [""]\n')


def test_work_days_more_than_seven_entries_rejected():
    with pytest.raises(ConfigError):
        validate_config(
            "day_rules:\n  work_days: [mon, tue, wed, thu, fri, sat, sun, mon]\n")
