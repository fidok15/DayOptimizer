from datetime import date

from dayoptimizer.core.constraints import (
    NoteRule,
    allowed_window,
    explain,
    free_windows,
    gap_rule,
    parse_rules,
    week_rule,
    window_rule,
)

RAW = [
    {"type": "not_before", "category": "Food", "time": "14:00", "source": "no lunch before 14"},
    {"type": "not_after", "time": "22:00", "source": "nothing after 22"},
    {"type": "keep_free", "weekday": "sun", "start": "18:00", "end": "22:00", "source": "family time"},
    {"type": "min_gap_days", "category": "Gym", "days": 2, "source": "no training two days in a row"},
    {"type": "max_per_week", "category": "Gym", "count": 3},
    {"type": "nonsense", "category": "Gym"},
    {"type": "not_before", "category": "Food", "time": "99:99"},
    {"type": "keep_free", "start": "20:00", "end": "19:00"},
    {"type": "min_gap_days", "category": "Gym", "days": "many"},
    "junk",
]


def test_parse_keeps_only_valid_rules():
    rules = parse_rules(RAW)
    assert [r.type for r in rules] == ["not_before", "not_after", "keep_free", "min_gap_days", "max_per_week"]
    assert rules[2].weekday == 6 and rules[2].start == 18 * 60
    assert parse_rules(None) == [] and parse_rules([]) == []


def test_windows_combine_per_category():
    rules = parse_rules(RAW)
    assert allowed_window(rules, "Food") == (14 * 60, 22 * 60)
    assert allowed_window(rules, "Gym") == (0, 22 * 60)
    assert free_windows(rules, 6, "Gym") == [(18 * 60, 22 * 60)]
    assert free_windows(rules, 0, "Gym") == []


def test_window_rule_names_the_broken_note():
    rules = parse_rules(RAW)
    broken = window_rule(rules, "Food", 12 * 60, 13 * 60)
    assert broken.type == "not_before" and "no lunch before 14" in explain(broken)
    assert window_rule(rules, "Food", 15 * 60, 16 * 60) is None
    assert window_rule(rules, "Learn", 21 * 60, 23 * 60).type == "not_after"
    assert window_rule(rules, "Gym", 19 * 60, 20 * 60) is None
    assert window_rule(rules, "Gym", 19 * 60, 20 * 60, weekday=6).type == "keep_free"
    assert window_rule(rules, "Gym", 19 * 60, 20 * 60, weekday=0) is None


def test_gap_and_week_limits():
    rules = parse_rules(RAW)
    day = date(2026, 9, 24)
    yesterday = {"Gym": [date(2026, 9, 23)]}
    assert gap_rule(rules, "Gym", day, yesterday).days == 2
    assert gap_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 22)]}) is None
    assert gap_rule(rules, "Food", day, {"Food": [date(2026, 9, 23)]}) is None
    this_week = {"Gym": [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]}
    assert week_rule(rules, "Gym", day, this_week).count == 3
    assert week_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 21)]}) is None
    assert week_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 21)]}, planned=2).count == 3
    assert week_rule(rules, "Gym", day, {"Gym": [date(2026, 9, 14)]}) is None


def test_explain_without_source():
    assert explain(NoteRule("not_before", minutes=60)) == "your rule (not_before)"


def test_a_second_limit_of_a_kind_is_dropped():
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
    assert len([r for r in rules if r.type == "keep_free"]) == 2


def test_skippable_events_are_planned_over_and_never_moved():
    import dataclasses
    from datetime import date, datetime
    from pathlib import Path

    from dayoptimizer.core.constraints import describe, parse_rules, skippable
    from dayoptimizer.core.models import Event
    from dayoptimizer.core.planner import plan_day
    from dayoptimizer.core.rules import RoutineBlock, load_rules
    rules_rows = [{"type": "skippable", "category": "Important", "prefix": "Lecture -", "source": '"Lecture -" events can be skipped'},
                  {"type": "skippable", "category": "Important", "prefix": "", "source": "no prefix"}]
    parsed = parse_rules(rules_rows)
    assert len(parsed) == 1 and describe(parsed[0]) == 'Important: events starting with "Lecture -" may be planned over'
    d = datetime(2026, 7, 3).astimezone()
    lecture = Event(id="w", calendar="Important", title="Lecture - Maths", start=d.replace(hour=8), end=d.replace(hour=10))
    lab = Event(id="l", calendar="Important", title="Lab - Maths", start=d.replace(hour=12), end=d.replace(hour=13))
    assert skippable(parsed, lecture) and not skippable(parsed, lab)
    base = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
    rules = dataclasses.replace(base, note_rules=parsed,
                                typical_week={4: [RoutineBlock(8 * 60, 10 * 60, "Work", "Deep work"),
                                                  RoutineBlock(12 * 60, 13 * 60, "Work", "Review")]})
    changes = plan_day(date(2026, 7, 3), [lecture, lab], None, rules, now=d.replace(hour=5))
    created = {(c.title, f"{c.new_start:%H:%M}") for c in changes if c.kind == "create"}
    assert ("Deep work", "08:00") in created
    assert ("Review", "12:00") not in created
    assert not [c for c in changes if c.event_id == "w"]


def test_a_skippable_prefix_the_user_never_wrote_is_dropped():
    from dayoptimizer.web import _clean_rule
    row = {"type": "skippable", "category": "Uni", "prefix": "Lecture -", "source": 'Uni "Lecture -" events can be skipped'}
    assert _clean_rule(row, ["Uni"])["prefix"] == "Lecture -"
    assert _clean_rule({**row, "prefix": "C -"}, ["Uni"]) is None


def test_a_skippable_row_from_a_forbidding_sentence_is_dropped():
    from dayoptimizer.web import _clean_rule
    for prefix, source in [("L -", 'Ale już Projekt “P -“ czy Laby “L -“ nie możesz'),
                           ("EXAM", "but never skip anything starting with 'EXAM'"),
                           ("LAB", 'Classes starting with "LAB" must not be moved')]:
        assert _clean_rule({"type": "skippable", "category": "Uni", "prefix": prefix, "source": source},
                           ["Uni"]) is None
    ok = {"type": "skippable", "category": "Uni", "prefix": "W -", "source": 'Uni "W -" możesz nadpisywać, nie przejmuj się'}
    assert _clean_rule(ok, ["Uni"]) is not None


def test_a_skippable_prefix_must_be_the_quoted_text_when_there_is_one():
    from dayoptimizer.web import _clean_rule
    row = {"type": "skippable", "category": "Uni", "prefix": "Wykłady", "source": "Wykłady możesz nadpisywać"}
    context = 'Wykłady to wydarzenia z Uni, których tytuł zaczyna się od "W -"'
    assert _clean_rule(row, ["Uni"], context) is None
    assert _clean_rule({**row, "prefix": "W -"}, ["Uni"], context)["prefix"] == "W -"
    assert _clean_rule({**row, "prefix": "W -"}, ["Uni"]) is None
    assert _clean_rule({**row, "source": "Wykłady can be skipped"}, ["Uni"])["prefix"] == "Wykłady"


def test_a_skippable_category_is_the_calendar_the_sentence_names_or_any():
    from datetime import datetime

    from dayoptimizer.core.constraints import describe, parse_rules, skippable
    from dayoptimizer.core.models import Event
    from dayoptimizer.web import _clean_rule
    cats = ["Work", "Learn", "Politechnika"]
    row = {"type": "skippable", "category": "Work", "prefix": "W -",
           "source": 'Wykłady to wydarzenia z Politechniki, których tytuł zaczyna się od "W -"'}
    assert _clean_rule(row, cats)["category"] == "Politechnika"
    anywhere = _clean_rule({**row, "source": 'events starting with "W -" can be skipped'}, cats)
    assert anywhere["category"] is None
    rule = parse_rules([anywhere])
    d = datetime(2026, 7, 3, 8).astimezone()
    assert skippable(rule, Event(id="w", calendar="Uni", title="W - Maths", start=d, end=d))
    assert describe(rule[0]).startswith("Any calendar:")


def test_gap_rule_says_rest_days():
    from dayoptimizer.core.constraints import describe
    assert describe(NoteRule("min_gap_days", category="Gym", days=2)) == "Gym: at least 1 rest day(s) between"
