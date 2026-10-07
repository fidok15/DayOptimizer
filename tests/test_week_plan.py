from datetime import date, datetime, time, timedelta
from dayoptimizer.core.constraints import parse_rules
from dayoptimizer.core.models import Event
from dayoptimizer.llm.week_plan import Block, PlanOver, WeekPlan, build_prompt, diff, plan_days, validate

MON = date(2030, 10, 14)
NOW = datetime(2026, 10, 7, 12, 0).astimezone()
CATS = ["Gym", "Food", "Commute"]
NOTES = 'Gym at most 2 times a week. Lectures starting with "W -" may be planned over.'


def at(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m)).astimezone()


def ev(id, cal, title, d, start, end, managed=False):
    return Event(id=id, calendar=cal, title=title, start=at(d, start), end=at(d, end), managed=managed)


def block(d, start, end, cat="Food", title="Lunch"):
    return Block(day=d.isoformat(), start=start, end=end, category=cat, title=title)


LECTURE = ev("lec", "Uni", "W - Math", MON, "10:00", "12:00")
LAB = ev("lab", "Uni", "L - Physics", MON, "13:00", "15:00")


def check(plan, events=(LECTURE, LAB), rules=(), history=None, days=(MON,)):
    return validate(plan, list(days), CATS, list(events), NOTES, list(rules), NOW, history)


def test_keeps_a_clean_block():
    creates, problems = check(WeekPlan(blocks=[block(MON, "12:00", "13:00")]))
    assert problems == []
    assert [(c.title, c.new_start, c.new_end) for c in creates] == [("Lunch", at(MON, "12:00"), at(MON, "13:00"))]


def test_drops_a_block_over_a_user_event():
    creates, problems = check(WeekPlan(blocks=[block(MON, "14:00", "14:30")]))
    assert creates == [] and "L - Physics" in problems[0]


def test_plan_over_needs_the_users_own_sentence():
    over = WeekPlan(blocks=[block(MON, "11:00", "11:30")],
                    plan_over=[PlanOver(event_id="lec", note='Lectures starting with "W -" may be planned over')])
    assert check(over)[1] == []
    made_up = WeekPlan(blocks=[block(MON, "11:00", "11:30")],
                       plan_over=[PlanOver(event_id="lec", note="the user does not care about lectures")])
    creates, problems = check(made_up)
    assert creates == [] and len(problems) == 2


def test_blocks_must_not_overlap_each_other_or_the_past_or_bad_input():
    plan = WeekPlan(blocks=[block(MON, "16:00", "17:00"), block(MON, "16:30", "17:30", title="Snack"),
                            block(date(2026, 10, 7), "08:00", "09:00"), block(MON, "18:00", "17:00"),
                            block(MON, "19:00", "20:00", cat="Nope")])
    creates, problems = check(plan, days=(date(2026, 10, 7), MON))
    assert [c.title for c in creates] == ["Lunch"]
    assert len(problems) == 4


def test_count_rules_hold_across_history_and_plan():
    rules = parse_rules([{"type": "max_per_week", "category": "Gym", "count": 2, "source": "Gym at most 2"},
                         {"type": "min_gap_days", "category": "Gym", "days": 2, "source": "rest between"}])
    days = [MON + timedelta(days=i) for i in range(1, 7)]
    plan = WeekPlan(blocks=[block(d, "18:00", "19:00", "Gym", "Gym") for d in days])
    creates, problems = check(plan, events=(), rules=rules, history={"Gym": [MON]}, days=days)
    assert [c.new_start.date() for c in creates] == [MON + timedelta(days=2)]
    assert len(problems) == 5


def test_diff_keeps_identical_blocks_and_deletes_the_rest_of_the_old_plan():
    same = ev("a", "Food", "Lunch", MON, "12:00", "13:00", managed=True)
    gone = ev("b", "Gym", "Gym", MON, "18:00", "19:00", managed=True)
    creates, _ = check(WeekPlan(blocks=[block(MON, "12:00", "13:00"), block(MON, "16:00", "16:30", title="Snack")]))
    out = diff(creates, [same, gone])
    assert [(c.kind, c.title) for c in out] == [("delete", "Gym"), ("create", "Snack")]
    assert out[0].event_id == "b"


class Fake:
    def __init__(self, *plans):
        self.plans, self.prompts = list(plans), []

    def plan_week(self, system, prompt):
        self.prompts.append(prompt)
        return self.plans.pop(0)


def test_problems_go_back_to_the_model_until_the_plan_is_clean():
    bad = WeekPlan(blocks=[block(MON, "14:00", "14:30")])
    good = WeekPlan(blocks=[block(MON, "15:00", "15:30")], summary="ok")
    backend = Fake(bad, good)
    changes, summary, dropped = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB], NOTES, [], NOW)
    assert summary == "ok" and dropped == []
    assert [c.new_start for c in changes] == [at(MON, "15:00")]
    assert "L - Physics" in backend.prompts[1] and "corrected plan" in backend.prompts[1]


def test_prompt_lists_the_week_with_event_ids_and_marks_days_to_plan():
    text = build_prompt([MON], "# routine", CATS, [LECTURE], [], NOW)
    assert "[lec] 10:00-12:00 Uni: W - Math" in text
    assert f"Monday {MON.isoformat()} (plan this day)" in text
    assert "Sunday 2030-10-20" in text


def test_cli_falls_back_to_the_next_model_when_one_fails(monkeypatch):
    from dayoptimizer import cli

    class Broken:
        def plan_week(self, system, prompt):
            raise RuntimeError("invalid x-api-key")

    class Cal:
        def __init__(self):
            self.created = []

        def list_events(self, start, end):
            return [e for e in (LECTURE, LAB) if start <= e.start < end]

        def create_event(self, category, title, start, end):
            self.created.append((category, title, start))

    class Rules:
        has_routine = True
        note_rules = []
        typical_week = {}

    good = Fake(WeekPlan(blocks=[block(MON, "16:00", "17:00")]))
    monkeypatch.setattr("dayoptimizer.llm.backend.planning_backends", lambda cfg: [Broken(), good])
    monkeypatch.setattr(cli, "_load_config", lambda: (None, {"categories": {c: {} for c in CATS}, "llm": {}}))
    cal = Cal()
    storage = cli.Storage(":memory:")
    changes, applied, errors, _, _ = cli._llm_plan([MON], cal, storage, Rules(), confirm=lambda c: True)
    assert cal.created == [("Food", "Lunch", at(MON, "16:00"))] and errors == []
    assert len(good.prompts) == 1


def test_an_empty_plan_for_a_routine_day_is_a_problem():
    creates, problems = validate(WeekPlan(), [MON], CATS, [], NOTES, [], NOW, None, {MON})
    assert creates == [] and "no blocks planned" in problems[0]


def test_a_local_model_plans_one_day_at_a_time_and_limits_carry_over():
    rules = parse_rules([{"type": "max_per_week", "category": "Gym", "count": 1, "source": "Gym once"}])
    tue = MON + timedelta(days=1)

    class Small(Fake):
        one_day_at_a_time = True

    backend = Small(WeekPlan(blocks=[block(MON, "18:00", "19:00", "Gym", "Gym")]),
                    WeekPlan(blocks=[block(tue, "18:00", "19:00", "Gym", "Gym")]),
                    WeekPlan(blocks=[block(tue, "12:00", "13:00")]))
    changes, _, dropped = plan_days(backend, [MON, tue], "# routine", CATS, [], NOTES, rules, NOW)
    assert [(c.category, c.new_start.date()) for c in changes] == [("Gym", MON), ("Food", tue)]
    assert dropped == [] and len(backend.prompts) == 3
    assert "(plan this day)" in backend.prompts[1] and backend.prompts[1].count("(plan this day)") == 1


def test_a_block_ending_at_midnight_may_say_00_00():
    creates, problems = check(WeekPlan(blocks=[block(MON, "23:30", "00:00", "Food", "Late snack")]), events=())
    assert problems == [] and creates[0].new_end == at(MON, "00:00") + timedelta(days=1)
