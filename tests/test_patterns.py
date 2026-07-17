from dayoptimizer.core.models import GarminSummary
from dayoptimizer.core.patterns import render_stats, suggest_adjustments, weekly_stats


def _s(date, sleep_h, score=70, bb=60, stress=40):
    return GarminSummary(date=date, sleep_seconds=int(sleep_h * 3600),
                         sleep_score=score, body_battery_start=bb, stress_avg=stress)


def test_weekly_stats_averages():
    hist = [_s("2026-07-06", 8), _s("2026-07-07", 7), _s("2026-07-08", 6)]
    st = weekly_stats(hist)
    assert st["days_with_data"] == 3
    assert st["avg_sleep_hours"] == 7.0
    assert st["avg_sleep_score"] == 70
    assert st["avg_body_battery"] == 60
    assert st["avg_stress"] == 40


def test_weekly_stats_empty():
    st = weekly_stats([])
    assert st["days_with_data"] == 0
    assert st["avg_sleep_hours"] is None
    assert st["sleep_trend"] == "insufficient data"


def test_sleep_trend_improving():
    # history is newest-first (Storage.garmin_history ordering):
    # recent 3 avg 8h vs previous 3 avg 6.5h -> improving
    hist = [_s("2026-07-12", 8), _s("2026-07-11", 8), _s("2026-07-10", 8),
            _s("2026-07-09", 6.5), _s("2026-07-08", 6.5), _s("2026-07-07", 6.5)]
    assert weekly_stats(hist)["sleep_trend"] == "improving"


def test_suggestions_thresholds():
    from dayoptimizer.core.rules import load_rules
    rules = load_rules("tests/fixtures/config.yaml")   # sleep_target_hours 8.0
    st = {"days_with_data": 7, "avg_sleep_hours": 7.0, "avg_sleep_score": 55,
          "avg_body_battery": 35, "avg_stress": 62, "sleep_trend": "stable"}
    tips = suggest_adjustments(st, rules)
    assert any("30 min earlier" in t for t in tips)      # sleep < target - 0.5h
    assert any("recovery" in t for t in tips)            # avg BB < 40
    assert any("wind-down" in t for t in tips)           # avg stress >= 60


def test_render_stats_contains_key_numbers():
    st = weekly_stats([_s("2026-07-12", 7.5)])
    out = render_stats(st)
    assert "7.5" in out and "1 day" in out
