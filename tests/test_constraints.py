from datetime import date
from dayoptimizer.core.constraints import (NoteRule, allowed_window, explain, free_windows,
                                           gap_rule, parse_rules, week_rule, window_rule)

RAW = [
    {"type": "not_before", "category": "Food", "time": "14:00", "source": "no lunch before 14"},
    {"type": "not_after", "time": "22:00", "source": "nothing after 22"},
    {"type": "keep_free", "weekday": "sun", "start": "18:00", "end": "22:00", "source": "family time"},
    {"type": "min_gap_days", "category": "Gym", "days": 2, "source": "no training two days in a row"},
    {"type": "max_per_week", "category": "Gym", "count": 3},
    {"type": "nonsense", "category": "Gym"},                      # unknown type
    {"type": "not_before", "category": "Food", "time": "99:99"},   # bad time
    {"type": "keep_free", "start": "20:00", "end": "19:00"},       # end before start
    {"type": "min_gap_days", "category": "Gym", "days": "many"},   # not a number
    "junk",
]


def test_parse_keeps_only_valid_rules():
    rules = parse_rules(RAW)
    assert [r.type for r in rules] == ["not_before", "not_after", "keep_free", "min_gap_days", "max_per_week"]
    assert rules[2].weekday == 6 and rules[2].start == 18 * 60
    assert parse_rules(None) == [] and parse_rules([]) == []


def test_windows_combine_per_category():
    rules = parse_rules(RAW)
    assert allowed_window(rules, "Food") == (14 * 60, 22 * 60)   # category rule + the global one
    assert allowed_window(rules, "Gym") == (0, 22 * 60)          # only the global one
    assert free_windows(rules, 6, "Gym") == [(18 * 60, 22 * 60)]
    assert free_windows(rules, 0, "Gym") == []


def test_window_rule_names_the_broken_note():
    rules = parse_rules(RAW)
    broken = window_rule(rules, "Food", 12 * 60, 13 * 60)
    assert broken.type == "not_before" and "no lunch before 14" in explain(broken)
    assert window_rule(rules, "Food", 15 * 60, 16 * 60) is None
    assert window_rule(rules, "Learn", 21 * 60, 23 * 60).type == "not_after"
    # a keep-free window only counts once we know the weekday
    assert window_rule(rules, "Gym", 19 * 60, 20 * 60) is None
    assert window_rule(rules, "Gym", 19 * 60, 20 * 60, weekday=6).type == "keep_free"
    assert window_rule(rules, "Gym", 19 * 60, 20 * 60, weekday=0) is None


def test_gap_and_week_limits():
    rules = parse_rules(RAW)
    day = date(2026, 9, 24)  # Thursday
    yesterday = {"Gym": [date(2026, 9, 23)]}
    assert gap_rule(rules, "Gym", day, yesterday).days == 2
    assert gap_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 22)]}) is None  # two days back is fine
    assert gap_rule(rules, "Food", day, {"Food": [date(2026, 9, 23)]}) is None
    this_week = {"Gym": [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]}
    assert week_rule(rules, "Gym", day, this_week).count == 3
    assert week_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 21)]}) is None
    assert week_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 21)]}, planned=2).count == 3
    assert week_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 14)]}) is None  # last week doesn't count


def test_explain_without_source():
    assert explain(NoteRule("not_before", minutes=60)) == "your rule (not_before)"


def test_a_second_limit_of_a_kind_is_dropped():
    # a model misreading "dinner around 21" as another "not before" must not
    # shrink Food to nothing on top of "no lunch before 14"
    rules = parse_rules([
        {"type": "not_before", "category": "Food", "time": "14:00", "source": "no lunch before 14"},
        {"type": "not_before", "category": "Food", "time": "21:00", "source": "dinner around 21"},
        {"type": "not_before", "category": "Gym", "time": "16:00"},
        {"type": "keep_free", "start": "12:00", "end": "13:00"},
        {"type": "keep_free", "weekday": "sun", "start": "18:00", "end": "22:00"},
    ])
    assert [(r.type, r.category, r.minutes) for r in rules if r.type == "not_before"] == [
        ("not_before", "Food", 14 * 60), ("not_before", "Gym", 16 * 60)]
    assert allowed_window(rules, "Food") == (14 * 60, 1440)
    assert len([r for r in rules if r.type == "keep_free"]) == 2  # windows stack, limits don't
