"""Long-term Garmin patterns: weekly averages, sleep trend, plain-English tips."""
from __future__ import annotations
from dayoptimizer.core.models import GarminSummary
from dayoptimizer.core.rules import Rules


def _avg(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def weekly_stats(history: list[GarminSummary]) -> dict:
    """history is newest-first (Storage.garmin_history ordering)."""
    stats = {
        "days_with_data": len(history),
        "avg_sleep_hours": _avg([s.sleep_seconds / 3600 for s in history
                                 if s.sleep_seconds is not None] or [None]),
        "avg_sleep_score": _avg([s.sleep_score for s in history]),
        "avg_body_battery": _avg([s.body_battery_start for s in history]),
        "avg_stress": _avg([s.stress_avg for s in history]),
        "sleep_trend": "insufficient data",
    }
    sleeps = [s.sleep_seconds / 3600 for s in history if s.sleep_seconds is not None]
    if len(sleeps) >= 6:
        recent, previous = _avg(sleeps[:3]), _avg(sleeps[3:6])
        if recent - previous > 0.25:
            stats["sleep_trend"] = "improving"
        elif previous - recent > 0.25:
            stats["sleep_trend"] = "declining"
        else:
            stats["sleep_trend"] = "stable"
    return stats


def render_stats(stats: dict) -> str:
    n = stats["days_with_data"]
    if n == 0:
        return "No Garmin data recorded yet."
    parts = [f"{n} day{'s' if n != 1 else ''} of data"]
    if stats["avg_sleep_hours"] is not None:
        parts.append(f"avg sleep {stats['avg_sleep_hours']}h")
    if stats["avg_sleep_score"] is not None:
        parts.append(f"avg sleep score {stats['avg_sleep_score']}")
    if stats["avg_body_battery"] is not None:
        parts.append(f"avg Body Battery {stats['avg_body_battery']}")
    if stats["avg_stress"] is not None:
        parts.append(f"avg stress {stats['avg_stress']}")
    parts.append(f"sleep trend: {stats['sleep_trend']}")
    return ", ".join(parts)


def suggest_adjustments(stats: dict, rules: Rules) -> list[str]:
    tips: list[str] = []
    if stats["days_with_data"] == 0:
        return tips
    sleep = stats["avg_sleep_hours"]
    if sleep is not None and sleep < rules.sleep_target_hours - 0.5:
        tips.append(f"Average sleep {sleep}h is below your {rules.sleep_target_hours}h target — try going to bed 30 min earlier.")
    bb = stats["avg_body_battery"]
    if bb is not None and bb < 40:
        tips.append("Low average Body Battery — you may need more recovery; consider one workout less this week.")
    stress = stats["avg_stress"]
    if stress is not None and stress >= 60:
        tips.append("High average stress — consider a longer evening wind-down.")
    return tips
