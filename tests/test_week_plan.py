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
        self.plans, self.prompts, self.schemas = list(plans), [], []

    def plan_week(self, system, prompt, schema=None):
        self.prompts.append(prompt)
        self.schemas.append(schema)
        return self.plans.pop(0)


def test_problems_go_back_to_the_model_until_the_plan_is_clean():
    bad = WeekPlan(blocks=[block(MON, "14:00", "14:30")])
    good = WeekPlan(blocks=[block(MON, "15:00", "15:30")], summary="ok")
    backend = Fake(bad, good)
    changes, summary, dropped, _ = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB], NOTES, [], NOW)
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
        def plan_week(self, system, prompt, schema=None):
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
    changes, applied, errors, _, _, _ = cli._llm_plan([MON], cal, storage, Rules(), confirm=lambda c: True)
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
    changes, _, dropped, _ = plan_days(backend, [MON, tue], "# routine", CATS, [], NOTES, rules, NOW)
    assert [(c.category, c.new_start.date()) for c in changes] == [("Gym", MON), ("Food", tue)]
    assert dropped == [] and len(backend.prompts) == 3
    assert "(plan this day)" in backend.prompts[1] and backend.prompts[1].count("(plan this day)") == 1


def test_a_block_ending_at_midnight_may_say_00_00():
    creates, problems = check(WeekPlan(blocks=[block(MON, "23:30", "00:00", "Food", "Late snack")]), events=())
    assert problems == [] and creates[0].new_end == at(MON, "00:00") + timedelta(days=1)


from dayoptimizer.core.models import Task
from dayoptimizer.llm.week_plan import Unscheduled, system_prompt

WCATS = CATS + ["Work"]


def task(**kw):
    base = dict(id="t1", title="Report", category="Work", duration_min=120, due=at(MON, "22:00"),
                min_chunk_min=60)
    base.update(kw)
    return Task(**base)


def tblock(start, end, task_id="t1", title="Report", cat="Work", d=MON):
    return Block(day=d.isoformat(), start=start, end=end, category=cat, title=title, task_id=task_id)


def tcheck(plan, tasks, left=None, days=(MON,)):
    left = left if left is not None else {t.id: t.duration_min for t in tasks}
    return validate(plan, list(days), WCATS, [LECTURE, LAB], NOTES, [], NOW, None, frozenset(),
                    tasks=tasks, left=left)


def test_task_blocks_are_kept_and_carry_the_task_id():
    creates, problems = tcheck(WeekPlan(blocks=[tblock("16:00", "17:00"), tblock("18:00", "19:00")]), [task()])
    assert problems == []
    assert [(c.task_id, c.new_start) for c in creates] == [("t1", at(MON, "16:00")), ("t1", at(MON, "18:00"))]


def test_task_due_today_must_be_placed_or_listed():
    _, problems = tcheck(WeekPlan(blocks=[tblock("16:00", "17:00")]), [task()])
    assert len(problems) == 1 and problems[0].startswith("t1: 60 min")
    listed = WeekPlan(blocks=[tblock("16:00", "17:00")],
                      unscheduled=[Unscheduled(task_id="t1", reason="no more free time")])
    assert tcheck(listed, [task()])[1] == []


def test_chunk_and_left_rules_apply_in_order():
    plan = WeekPlan(blocks=[tblock("16:00", "17:30"), tblock("18:00", "18:20"), tblock("19:00", "19:30")])
    creates, problems = tcheck(plan, [task()])
    assert [c.new_start for c in creates] == [at(MON, "16:00"), at(MON, "19:00")]
    assert "minimum chunk of 60" in problems[0]


def test_unknown_task_block_and_unscheduled_are_problems():
    plan = WeekPlan(blocks=[tblock("16:00", "17:00", task_id="t9")],
                    unscheduled=[Unscheduled(task_id="t8", reason="?")])
    creates, problems = tcheck(plan, [task(due=None)])
    assert creates == []
    assert any("task t9 is not an open task" in p for p in problems)
    assert any("unscheduled t8" in p for p in problems)


def test_prompt_lists_tasks_and_system_prompt_switches_examples():
    text = build_prompt([MON], "# routine", WCATS, [LECTURE], [], NOW, tasks=[task()], left={"t1": 90})
    assert "# Tasks" in text and "- [t1] Report (Work) 90 min left" in text
    assert "# Tasks" not in build_prompt([MON], "# routine", WCATS, [LECTURE], [], NOW)
    assert "Examples" in system_prompt(True) and "Examples" not in system_prompt(False)
    assert "task_id" in system_prompt(False)


def test_unscheduled_reasons_come_back_from_plan_days():
    plan = WeekPlan(blocks=[tblock("16:00", "17:00")],
                    unscheduled=[Unscheduled(task_id="t1", reason="60 min missing")])
    changes, _, dropped, unscheduled = plan_days(Fake(plan), [MON], "# routine", WCATS, [LECTURE, LAB], NOTES,
                                                 [], NOW, tasks=[task()], left={"t1": 120})
    assert dropped == [] and unscheduled == ["t1: 60 min missing"]
    assert changes[0].task_id == "t1"


def test_day_by_day_carries_task_minutes():
    tue = MON + timedelta(days=1)

    class Small(Fake):
        one_day_at_a_time = True

    t = task(due=at(tue, "22:00"), duration_min=120)
    backend = Small(WeekPlan(blocks=[tblock("16:00", "17:00")]),
                    WeekPlan(blocks=[tblock("16:00", "17:00", d=tue)]))
    changes, _, dropped, _ = plan_days(backend, [MON, tue], "# routine", WCATS, [], NOTES, [], NOW,
                                       tasks=[t], left={"t1": 120})
    assert dropped == [] and len(changes) == 2
    assert "- [t1] Report (Work) 60 min left" in backend.prompts[1]


def test_cli_plans_open_tasks_even_without_a_routine(monkeypatch):
    from dayoptimizer import cli

    class Cal:
        def __init__(self):
            self.created = []

        def list_events(self, start, end):
            return []

        def create_event(self, category, title, start, end, task_id=None):
            self.created.append((title, start, task_id))

    class NoRoutine:
        has_routine = False
        note_rules = []
        typical_week = {}

    backend = Fake(WeekPlan(blocks=[tblock("16:00", "18:00")],
                            unscheduled=[]))
    monkeypatch.setattr("dayoptimizer.llm.backend.planning_backends", lambda cfg: [backend])
    monkeypatch.setattr(cli, "_load_config", lambda: (None, {"categories": {c: {} for c in WCATS}, "llm": {}}))
    storage = cli.Storage(":memory:")
    storage.save_task(task())
    cal = Cal()
    changes, applied, errors, _, dropped, unscheduled = cli._llm_plan([MON], cal, storage, NoRoutine(),
                                                                      confirm=lambda c: True)
    assert cal.created == [("Report", at(MON, "16:00"), "t1")]
    assert dropped == [] and unscheduled == [] and errors == []
    assert "- [t1] Report (Work) 120 min left" in backend.prompts[0]


def test_cli_without_routine_or_tasks_does_not_plan(monkeypatch):
    from dayoptimizer import cli

    class NoRoutine:
        has_routine = False
        note_rules = []
        typical_week = {}

    class Empty:
        def list_events(self, start, end):
            return []

    assert cli._llm_plan([MON], Empty(), cli.Storage(":memory:"), NoRoutine()) is None


def test_a_block_under_way_is_not_overlapped():
    now = at(MON, "11:00")
    running = ev("r", "Work", "Report", MON, "10:00", "12:00", managed=True)
    creates, problems = validate(WeekPlan(blocks=[block(MON, "11:30", "12:30")]), [MON], CATS, [running],
                                 NOTES, [], now)
    assert creates == [] and "overlaps 'Report'" in problems[0]


def test_day_by_day_counts_blocks_kept_as_they_were():
    tue = MON + timedelta(days=1)

    class Small(Fake):
        one_day_at_a_time = True

    kept = Event(id="k", calendar="Work", title="Report", start=at(MON, "16:00"), end=at(MON, "17:00"),
                 managed=True, task_id="t1")
    backend = Small(WeekPlan(blocks=[tblock("16:00", "17:00")]),
                    WeekPlan(blocks=[tblock("16:00", "17:00", d=tue)]))
    changes, _, dropped, _ = plan_days(backend, [MON, tue], "# routine", WCATS, [kept], NOTES, [], NOW,
                                       tasks=[task(due=at(tue, "22:00"))], left={"t1": 120})
    assert "- [t1] Report (Work) 60 min left" in backend.prompts[1]
    assert [c.new_start for c in changes if c.kind == "create"] == [at(tue, "16:00")]


def test_cli_removes_future_blocks_of_finished_tasks_without_a_model(monkeypatch):
    from dayoptimizer import cli
    stale = Event(id="s", calendar="Work", title="Report", start=at(MON, "16:00"), end=at(MON, "17:00"),
                  managed=True, task_id="t1")

    class Cal:
        def __init__(self):
            self.deleted = []

        def list_events(self, start, end):
            return [stale] if start <= stale.start < end else []

        def delete_event(self, event_id):
            self.deleted.append(event_id)

    class NoRoutine:
        has_routine = False
        note_rules = []
        typical_week = {}

    monkeypatch.setattr(cli, "_load_config", lambda: (None, {"categories": {c: {} for c in WCATS}, "llm": {}}))
    storage = cli.Storage(":memory:")
    storage.save_task(task())
    storage.mark_task_done("t1")
    cal = Cal()
    assert cli._llm_plan([MON], cal, storage, NoRoutine(), confirm=lambda c: True) is None
    assert cal.deleted == ["s"]


from dayoptimizer.llm.week_plan import plan_schema


SKIP = parse_rules([{"type": "skippable", "category": "Uni", "prefix": "W -",
                     "source": 'Lectures starting with "W -" may be planned over.'}])


def test_plan_schema_allows_only_known_values():
    s = plan_schema(CATS, [MON], ["t1"], NOTES, [LECTURE, LAB], SKIP)
    blk = s["$defs"]["Block"]["properties"]
    assert blk["category"]["enum"] == CATS and blk["day"]["enum"] == [MON.isoformat()]
    assert blk["task_id"] == {"anyOf": [{"enum": ["t1"]}, {"type": "null"}], "default": None}
    over = s["$defs"]["PlanOver"]["properties"]
    assert over["event_id"]["enum"] == ["lec"]  # only events a note lets the planner plan over
    assert s["properties"]["plan_over"]["maxItems"] == 1
    assert s["properties"]["blocks"]["maxItems"] == 30
    assert 'Lectures starting with "W -" may be planned over.' in over["note"]["enum"]
    assert s["$defs"]["Unscheduled"]["properties"]["task_id"]["enum"] == ["t1"]


def test_plan_schema_without_tasks_notes_or_events_forbids_them():
    s = plan_schema(CATS, [MON], [], "", [])
    assert s["$defs"]["Block"]["properties"]["task_id"] == {"type": "null", "default": None}
    assert plan_schema(CATS, [MON], [], NOTES, [LECTURE, LAB])["properties"]["plan_over"]["maxItems"] == 0
    assert s["properties"]["plan_over"]["maxItems"] == 0
    assert s["properties"]["unscheduled"]["maxItems"] == 0


def test_plan_days_hands_the_model_its_schema():
    backend = Fake(WeekPlan())
    plan_days(backend, [MON], "# routine", CATS, [LECTURE], NOTES, [], NOW)
    assert backend.schemas[0]["$defs"]["Block"]["properties"]["category"]["enum"] == CATS


def test_prompt_gives_the_free_time_of_each_day_to_plan():
    text = build_prompt([MON], "# routine", CATS, [LECTURE, LAB], [], NOW)
    assert "- free: 00:00-10:00, 12:00-13:00, 15:00-24:00" in text
    assert text.count("- free:") == 1
    later = build_prompt([MON], "# routine", CATS, [LECTURE, LAB], [], at(MON, "12:30"))
    assert "- free: 12:30-13:00, 15:00-24:00" in later


def test_instructions_say_not_to_copy_events():
    assert "never copy" in system_prompt(False)
    assert "not copied" in system_prompt(True)


def test_task_lines_say_where_the_task_fits():
    t = task(due=at(MON, "22:00"), not_before=at(MON, "12:30"))
    text = build_prompt([MON], "# routine", WCATS, [LECTURE, LAB], [], NOW, tasks=[t], left={"t1": 120})
    assert "fits in: Mon 15:00-22:00" in text  # 12:30-13:00 is shorter than a 60 min chunk
    full = [ev("x", "Job", "Shift", MON, "00:00", "23:59")]
    assert "fits in: nowhere in the days you plan" in build_prompt([MON], "# routine", WCATS, full, [], NOW,
                                                                   tasks=[t], left={"t1": 120})


def test_a_correction_keeps_the_good_blocks_and_asks_only_for_the_rest():
    first = WeekPlan(blocks=[block(MON, "16:00", "17:00"), block(MON, "14:00", "14:30", title="Snack")])
    second = WeekPlan(blocks=[block(MON, "17:00", "17:30", title="Snack")])
    backend = Fake(first, second)
    changes, _, dropped, _ = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB], NOTES, [], NOW)
    assert dropped == []
    assert sorted((c.title, c.new_start) for c in changes) == [("Lunch", at(MON, "16:00")), ("Snack", at(MON, "17:00"))]
    assert "Already placed" in backend.prompts[1] and "16:00-17:00 Food: Lunch" in backend.prompts[1]
    assert "- free: 00:00-10:00, 12:00-13:00, 15:00-16:00, 17:00-24:00" in backend.prompts[1]


def test_a_correction_shows_task_minutes_left_after_kept_blocks():
    first = WeekPlan(blocks=[tblock("16:00", "17:00"), tblock("14:00", "15:00")])
    second = WeekPlan(blocks=[tblock("18:00", "19:00")])
    backend = Fake(first, second)
    changes, _, dropped, _ = plan_days(backend, [MON], "# routine", WCATS, [LECTURE, LAB], NOTES, [], NOW,
                                       tasks=[task()], left={"t1": 120})
    assert dropped == [] and len(changes) == 2
    assert "- [t1] Report (Work) 60 min left" in backend.prompts[1]


def test_one_piece_task_fits_only_where_it_fits_whole():
    t = task(min_chunk_min=None, due=at(MON, "23:00"))
    text = build_prompt([MON], "# routine", WCATS, [LECTURE, LAB], [], NOW, tasks=[t], left={"t1": 120})
    assert "fits in: Mon 00:00-10:00, 15:00-23:00" in text
    assert "in one piece (one block of 120 min)" in text


def test_a_too_long_task_block_is_cut_to_what_is_left():
    creates, problems = tcheck(WeekPlan(blocks=[tblock("16:00", "18:00")]), [task()], left={"t1": 60})
    assert problems == []
    assert [(c.new_start, c.new_end) for c in creates] == [(at(MON, "16:00"), at(MON, "17:00"))]


def test_after_the_last_round_code_reports_what_did_not_fit():
    changes, _, dropped, unscheduled = plan_days(Fake(WeekPlan()), [MON], "# routine", WCATS, [LECTURE, LAB],
                                                 NOTES, [], NOW, attempts=1, tasks=[task()], left={"t1": 120})
    assert dropped == [] and changes == []
    assert unscheduled == ["t1: 'Report' doesn't fit before Mon 2030-10-14 22:00 - missing 120 min"]


def test_surplus_block_of_a_fully_placed_task_is_dropped_quietly():
    creates, problems = tcheck(WeekPlan(blocks=[tblock("16:00", "18:00"), tblock("19:00", "20:00")]), [task()])
    assert problems == [] and [c.new_start for c in creates] == [at(MON, "16:00")]


def test_tasks_that_cannot_be_worked_on_in_the_planned_days_are_not_shown():
    tue = MON + timedelta(days=1)
    later = task(not_before=at(tue, "00:00"), due=at(tue, "18:00"))
    assert "[t1]" not in build_prompt([MON], "# routine", WCATS, [], [], NOW, tasks=[later], left={"t1": 120})
    backend = Fake(WeekPlan())
    plan_days(backend, [MON], "# routine", WCATS, [], NOTES, [], NOW, tasks=[later], left={"t1": 120})
    assert backend.schemas[0]["$defs"]["Block"]["properties"]["task_id"] == {"type": "null", "default": None}


def test_a_small_model_keeps_previous_blocks_it_did_not_mention():
    class Small(Fake):
        one_day_at_a_time = True

    old = [ev("a", "Food", "Lunch", MON, "12:00", "13:00", managed=True),
           ev("b", "Food", "Snack", MON, "16:00", "16:30", managed=True),
           ev("c", "Food", "Dinner", MON, "18:00", "19:00", managed=True)]
    backend = Small(WeekPlan(blocks=[block(MON, "17:00", "17:30", title="Snack"),
                                     block(MON, "18:30", "19:30", "Gym", "Gym")]))
    changes, _, dropped, _ = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB] + old, NOTES, [], NOW)
    assert dropped == []
    assert sorted((c.kind, c.title) for c in changes) == [("create", "Gym"), ("create", "Snack"),
                                                         ("delete", "Dinner"), ("delete", "Snack")]


def test_tasks_stay_out_of_fixed_routine_time():
    sleep = {MON: [(at(MON, "00:00"), at(MON, "07:00"), "Sleep")]}
    text = build_prompt([MON], "# routine", WCATS, [LECTURE, LAB], [], NOW, tasks=[task()], left={"t1": 120},
                        reserved=sleep)
    assert "fits in: Mon 07:00-10:00, 12:00-13:00, 15:00-22:00" in text
    creates, problems = validate(WeekPlan(blocks=[tblock("05:00", "06:00")]), [MON], WCATS, [LECTURE, LAB], NOTES,
                                 [], NOW, None, frozenset(), tasks=[task(due=None)], left={"t1": 120}, reserved=sleep)
    assert creates == [] and "fixed routine 'Sleep'" in problems[0]


def test_a_block_titled_like_an_open_task_counts_as_that_task():
    creates, problems = tcheck(WeekPlan(blocks=[block(MON, "16:00", "18:00", "Work", "report")]), [task()])
    assert problems == [] and creates[0].task_id == "t1"


def test_cli_reserves_fixed_and_protected_routine_blocks_for_tasks(monkeypatch):
    from dayoptimizer import cli
    from dayoptimizer.core.rules import CategoryRule, RoutineBlock

    class Cal:
        def list_events(self, start, end):
            return []

        def create_event(self, category, title, start, end, task_id=None):
            pass

    class R:
        has_routine = True
        note_rules = []
        typical_week = {MON.weekday(): [RoutineBlock(0, 420, "Sleep", "Sen"), RoutineBlock(720, 780, "Food", "Lunch"),
                                        RoutineBlock(1080, 1140, "Work", "Standup", protected=True)]}
        categories = {"Sleep": CategoryRule(movable=False), "Food": CategoryRule(movable=True),
                      "Work": CategoryRule(movable=True)}

    backend = Fake(WeekPlan())
    monkeypatch.setattr("dayoptimizer.llm.backend.planning_backends", lambda cfg: [backend])
    monkeypatch.setattr(cli, "_load_config", lambda: (None, {"categories": {c: {} for c in WCATS + ["Sleep"]},
                                                             "llm": {}}))
    storage = cli.Storage(":memory:")
    storage.save_task(task(due=None))
    cli._llm_plan([MON], Cal(), storage, R(), confirm=lambda c: True)
    # a protected block keeps out even a task of its own category
    assert "fits in: Mon 07:00-18:00, 19:00-24:00" in backend.prompts[0]
    assert "18:00-19:00 Work: Standup (protected)" in backend.prompts[0]


def test_plan_schema_keeps_free_text_short():
    s = plan_schema(CATS, [MON], [], "", [])
    assert s["properties"]["summary"]["maxLength"] == 300
    assert s["$defs"]["Block"]["properties"]["why"]["maxLength"] == 80
    assert s["$defs"]["Block"]["properties"]["title"]["maxLength"] == 60


SLEEP_LUNCH = {MON: [(at(MON, "00:00"), at(MON, "07:00"), "Gym", "Sleep", True),
                     (at(MON, "12:00"), at(MON, "13:00"), "Food", "Lunch", False)]}


def test_each_day_to_plan_lists_its_routine():
    text = build_prompt([MON], "# routine", CATS, [LECTURE, LAB], [], NOW, routine_days=SLEEP_LUNCH)
    assert "- routine: 00:00-07:00 Gym: Sleep (fixed), 12:00-13:00 Food: Lunch" in text


def test_a_small_model_gets_its_forgotten_fixed_routine_blocks_back():
    class Small(Fake):
        one_day_at_a_time = True

    backend = Small(WeekPlan(blocks=[block(MON, "12:00", "13:00")]))
    changes, _, dropped, _ = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB], NOTES, [], NOW,
                                       routine_days=SLEEP_LUNCH)
    assert dropped == []
    assert sorted((c.title, c.new_start) for c in changes) == [("Lunch", at(MON, "12:00")), ("Sleep", at(MON, "00:00"))]


class Small(Fake):
    one_day_at_a_time = True


TUE = MON + timedelta(days=1)


def sleep_only(*days):
    return {d: [(at(d, "00:00"), at(d, "07:00"), "Gym", "Sleep", True)] for d in days}


# a task block the planner had put at 10:00, now under a lecture that came later
PUSHED = Event(id="old", calendar="Work", title="Report", start=at(MON, "10:00"), end=at(MON, "12:00"),
               managed=True, task_id="t1")


def test_code_puts_back_task_minutes_a_replan_pushed_out():
    # a replan of Monday only: the task is due Wednesday, its Monday block is now under a lecture
    backend = Small(WeekPlan(), WeekPlan(), WeekPlan())
    changes, _, dropped, unscheduled = plan_days(
        backend, [MON], "# routine", WCATS, [LECTURE, LAB, PUSHED], NOTES, [], NOW,
        tasks=[task(due=at(MON + timedelta(days=2), "17:00"))], left={"t1": 120},
        reserved={MON: [(at(MON, "00:00"), at(MON, "07:00"), "Sleep")]}, routine_days=sleep_only(MON))
    work = [(c.new_start, c.new_end, c.task_id) for c in changes if c.task_id and c.kind == "create"]
    assert work == [(at(MON, "07:00"), at(MON, "09:00"), "t1")]
    assert unscheduled == []


def test_code_fills_a_task_on_its_last_planned_day_not_the_first():
    backend = Small(*[WeekPlan() for _ in range(6)])
    changes, _, _, unscheduled = plan_days(
        backend, [MON, TUE], "# routine", WCATS, [LECTURE, LAB], NOTES, [], NOW,
        tasks=[task(due=at(TUE, "22:00"))], left={"t1": 120}, routine_days=sleep_only(MON, TUE))
    assert [(c.new_start, c.new_end) for c in changes if c.task_id] == [(at(TUE, "07:00"), at(TUE, "09:00"))]
    assert unscheduled == []


def test_blocks_outside_the_routine_are_dropped_and_routine_blocks_keep_their_length():
    plan = WeekPlan(blocks=[block(MON, "17:00", "18:00", "Food", "Food"), block(MON, "15:00", "17:00")])
    creates, problems = validate(plan, [MON], CATS, [LECTURE, LAB], NOTES, [], NOW, routine_days=SLEEP_LUNCH)
    assert problems == []
    assert [(c.title, c.new_start, c.new_end) for c in creates] == [("Lunch", at(MON, "15:00"), at(MON, "16:00"))]


def test_a_small_model_gets_its_forgotten_meal_back_near_its_usual_time():
    lunch = {MON: [(at(MON, "15:00"), at(MON, "16:00"), "Food", "Lunch", False)]}
    call = ev("call", "Uni", "Call", MON, "15:00", "15:30")
    backend = Small(WeekPlan())
    changes, _, dropped, _ = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB, call], NOTES, [], NOW,
                                       routine_days=lunch)
    assert dropped == []
    assert [(c.title, c.new_start, c.new_end) for c in changes] == [("Lunch", at(MON, "15:30"), at(MON, "16:30"))]


def test_a_category_with_only_a_time_rule_does_not_let_filler_blocks_through():
    rules = parse_rules([{"type": "not_after", "category": "Food", "time": "21:00", "source": "x"}])
    plan = WeekPlan(blocks=[block(MON, "17:00", "18:00", "Food", "Free time")])
    creates, problems = validate(plan, [MON], CATS, [LECTURE, LAB], NOTES, rules, NOW, routine_days=SLEEP_LUNCH)
    assert creates == [] and problems == []


def test_a_routine_block_the_model_put_on_an_event_is_refilled_once_and_a_second_sleep_is_not_forgotten():
    routine = {MON: SLEEP_LUNCH[MON] + [(at(MON, "23:00"), at(MON, "23:59"), "Gym", "Sleep", True)]}
    backend = Small(WeekPlan(blocks=[block(MON, "00:00", "07:00", "Gym", "Sleep"), block(MON, "14:00", "14:30")]),
                    WeekPlan(blocks=[block(MON, "15:00", "15:30")]), WeekPlan())
    changes, _, _, _ = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB], NOTES, [], NOW,
                                 routine_days=routine)
    assert sorted((c.title, c.new_start) for c in changes) == [
        ("Lunch", at(MON, "12:00")), ("Sleep", at(MON, "00:00")), ("Sleep", at(MON, "23:00"))]


def test_code_puts_the_last_short_piece_of_a_task_in_an_earlier_small_gap():
    busy = [ev("a", "Uni", "Morning", MON, "07:00", "10:00"), LECTURE, ev("b", "Uni", "Call", MON, "12:30", "13:00"),
            LAB, ev("c", "Uni", "Evening", MON, "16:30", "23:59")]
    plan = WeekPlan(blocks=[block(MON, "00:00", "07:00", "Gym", "Sleep")])
    creates, problems = validate(plan, [MON], WCATS, busy, NOTES, [], NOW, tasks=[task(due=at(MON, "23:00"))],
                                 left={"t1": 120}, routine_days=sleep_only(MON), fill_until=MON)
    assert sorted((c.new_start, c.new_end) for c in creates if c.task_id) == [
        (at(MON, "12:00"), at(MON, "12:30")), (at(MON, "15:00"), at(MON, "16:30"))]


def test_a_task_without_a_deadline_is_not_lost_when_a_replan_pushes_it_out():
    backend = Small(WeekPlan(), WeekPlan(), WeekPlan())
    changes, _, _, _ = plan_days(backend, [MON], "# routine", WCATS, [LECTURE, LAB, PUSHED], NOTES, [], NOW,
                                 tasks=[task(due=None)], left={"t1": 120}, routine_days=sleep_only(MON))
    assert [(c.new_start, c.new_end) for c in changes if c.task_id and c.kind == "create"] == [
        (at(MON, "07:00"), at(MON, "09:00"))]


def test_code_does_not_pile_a_later_task_onto_a_one_day_plan():
    backend = Small(WeekPlan(), WeekPlan(), WeekPlan())
    changes, _, _, _ = plan_days(backend, [MON], "# routine", WCATS, [LECTURE, LAB], NOTES, [], NOW,
                                 tasks=[task(duration_min=600, due=at(MON + timedelta(days=5), "17:00"))],
                                 left={"t1": 600}, routine_days=sleep_only(MON))
    assert [c for c in changes if c.task_id] == []


def test_code_placed_task_blocks_keep_the_weekly_notes():
    rules = parse_rules([{"type": "max_per_week", "category": "Work", "count": 1, "source": "work once a week"}])
    plan = WeekPlan(blocks=[block(MON, "00:00", "07:00", "Gym", "Sleep")])
    creates, _ = validate(plan, [MON], WCATS, [LECTURE, LAB], NOTES, rules, NOW,
                          history={"Work": [TUE]}, tasks=[task()], left={"t1": 120},
                          routine_days=sleep_only(MON), fill_until=MON)
    assert [c for c in creates if c.task_id] == []


def test_a_commute_right_before_an_event_with_a_place_is_not_filler():
    gym = Event(id="g", calendar="Uni", title="Gym class", start=at(MON, "17:00"), end=at(MON, "18:00"),
                location="Gym street 1")
    plan = WeekPlan(blocks=[block(MON, "16:30", "17:00", "Commute", "Commute")])
    creates, problems = validate(plan, [MON], CATS, [LECTURE, LAB, gym], NOTES, [], NOW, routine_days=SLEEP_LUNCH)
    assert problems == [] and [c.title for c in creates] == ["Commute"]


def test_a_fixed_block_the_model_put_on_an_event_still_comes_back_at_its_usual_time():
    routine = {MON: [(at(MON, "12:00"), at(MON, "13:00"), "Food", "Lunch", False),
                     (at(MON, "22:00"), at(MON, "23:59"), "Gym", "Sleep", True)]}
    late = ev("late", "Uni", "Late lab", MON, "21:00", "22:00")
    backend = Small(WeekPlan(blocks=[block(MON, "12:00", "13:00"), block(MON, "21:00", "23:00", "Gym", "Sleep")]),
                    WeekPlan(), WeekPlan())
    changes, _, _, _ = plan_days(backend, [MON], "# routine", CATS, [LECTURE, LAB, late], NOTES, [], NOW,
                                 routine_days=routine)
    assert sorted((c.title, c.new_start) for c in changes) == [("Lunch", at(MON, "12:00")), ("Sleep", at(MON, "22:00"))]


def test_a_day_with_under_an_hour_left_is_not_asked_about():
    backend = Small(WeekPlan(blocks=[block(TUE, "12:00", "13:00")]))
    changes, _, _, _ = plan_days(backend, [MON, TUE], "# routine", CATS, [LECTURE, LAB], NOTES, [], at(MON, "23:30"))
    assert len(backend.prompts) == 1 and "Plan these days: Tuesday" in backend.prompts[0]
    assert [c.new_start for c in changes] == [at(TUE, "12:00")]


DEEP = (at(MON, "15:00"), at(MON, "19:00"), "Work", "Deep work", True)


def test_a_task_takes_its_categorys_fixed_routine_slot_and_the_routine_yields():
    plan = WeekPlan(blocks=[block(MON, "15:00", "19:00", "Work", "Deep work"), tblock("16:00", "18:00")])
    creates, problems = validate(plan, [MON], WCATS, [LECTURE, LAB], NOTES, [], NOW, None, frozenset(),
                                 tasks=[task()], left={"t1": 120}, routine_days={MON: [DEEP]},
                                 reserved={MON: [(DEEP[0], DEEP[1], "Deep work", "Work")]})
    assert problems == []
    assert sorted((c.new_start, c.new_end, c.title) for c in creates) == [
        (at(MON, "15:00"), at(MON, "16:00"), "Deep work"), (at(MON, "16:00"), at(MON, "18:00"), "Report"),
        (at(MON, "18:00"), at(MON, "19:00"), "Deep work")]


def test_fixed_routine_of_another_category_still_keeps_tasks_out():
    gym = {MON: [(at(MON, "16:00"), at(MON, "18:00"), "Training", "Gym")]}
    creates, problems = validate(WeekPlan(blocks=[tblock("16:00", "18:00")]), [MON], WCATS, [LECTURE, LAB], NOTES,
                                 [], NOW, None, frozenset(), tasks=[task(due=None)], left={"t1": 120}, reserved=gym)
    assert creates == [] and "fixed routine 'Training'" in problems[0]


def test_code_fills_a_task_into_its_categorys_routine_when_the_day_is_full():
    def r(a, b, cat, title):
        return (at(MON, a), at(MON, b), cat, title, True)
    spans = [r("00:00", "07:00", "Gym", "Sleep"), r("07:00", "10:00", "Food", "Breakfast"),
             r("12:00", "13:00", "Food", "Lunch"), r("15:00", "23:59", "Work", "Deep work")]
    backend = Small(*[WeekPlan() for _ in range(3)])
    changes, _, _, unscheduled = plan_days(
        backend, [MON], "# routine", WCATS, [LECTURE, LAB], NOTES, [], NOW, tasks=[task()], left={"t1": 120},
        reserved={MON: [(s, e, t, c) for s, e, c, t, _ in spans]}, routine_days={MON: spans})
    work = sorted((c.new_start, c.new_end, c.title) for c in changes if c.category == "Work")
    assert work == [(at(MON, "15:00"), at(MON, "17:00"), "Report"), (at(MON, "17:00"), at(MON, "23:59"), "Deep work")]
    assert unscheduled == []


def test_a_task_without_deadline_goes_first_to_its_routine_slot_then_earliest_free_time():
    deep = (at(MON, "15:00"), at(MON, "19:00"), "Work", "Deep work", False)
    for routine, start in (({MON: sleep_only(MON)[MON] + [deep], TUE: sleep_only(TUE)[TUE]}, "15:00"),
                           (sleep_only(MON, TUE), "07:00")):
        changes, _, _, unscheduled = plan_days(
            Small(*[WeekPlan() for _ in range(6)]), [MON, TUE], "# routine", WCATS, [LECTURE, LAB], NOTES, [],
            NOW, tasks=[task(due=None)], left={"t1": 120}, routine_days=routine)
        assert [c.new_start for c in changes if c.task_id] == [at(MON, start)] and unscheduled == []


def test_a_protected_meal_stays_put_when_a_small_model_puts_a_task_on_it():
    routine = {MON: [(at(MON, "16:00"), at(MON, "17:00"), "Food", "Dinner", False, True)]}
    reserved = {MON: [(at(MON, "16:00"), at(MON, "17:00"), "Dinner", None)]}
    backend = Small(WeekPlan(blocks=[tblock("16:00", "18:00")]))
    changes, _, dropped, _ = plan_days(backend, [MON], "# routine", WCATS, [LECTURE, LAB], NOTES, [], NOW,
                                       attempts=1, tasks=[task(due=None)], left={"t1": 120},
                                       reserved=reserved, routine_days=routine)
    assert ("Dinner", at(MON, "16:00")) in [(c.title, c.new_start) for c in changes]
    assert not any(c.task_id and c.new_start < at(MON, "17:00") < c.new_end for c in changes)
    assert "fixed routine 'Dinner'" in dropped[0]


def test_a_routine_block_with_no_room_left_is_reported_not_lost():
    lunch = {MON: [(at(MON, "13:00"), at(MON, "14:00"), "Food", "Lunch", False)]}
    wall = ev("wall", "Uni", "All day lab", MON, "10:00", "17:00")
    changes, _, dropped, _ = plan_days(Small(WeekPlan()), [MON], "# routine", CATS, [wall], NOTES, [], NOW,
                                       routine_days=lunch)
    assert changes == [] and dropped == ["Mon 13:00-14:00 Food: Lunch: no free time near its usual time"]


def test_code_fills_a_task_over_an_event_the_notes_let_it_plan_over():
    rules = parse_rules([{"type": "skippable", "category": "Uni", "prefix": "W -", "source": "x"}])
    busy = [ev("a", "Uni", "Morning", MON, "07:00", "10:00"), LECTURE, ev("b", "Uni", "Rest", MON, "12:00", "23:59")]
    sleep = WeekPlan(blocks=[block(MON, "00:00", "07:00", "Gym", "Sleep")])
    creates, _ = validate(sleep, [MON], WCATS, busy, NOTES, rules, NOW, tasks=[task(due=at(MON, "23:00"))],
                          left={"t1": 120}, routine_days=sleep_only(MON), fill_until=MON)
    assert [(c.new_start, c.new_end) for c in creates if c.task_id] == [(at(MON, "10:00"), at(MON, "12:00"))]


def test_a_day_the_model_fails_twice_is_planned_by_rule_and_the_rest_by_the_model():
    from dayoptimizer.llm.backend import LLMTimeout

    class Flaky(Small):
        def plan_week(self, system, prompt, schema=None):
            plan = super().plan_week(system, prompt, schema)
            if isinstance(plan, Exception):
                raise plan
            return plan

    backend = Flaky(LLMTimeout("too slow"), ValueError("bad json"), WeekPlan(blocks=[block(TUE, "12:00", "13:00")]))
    changes, summary, _, unscheduled = plan_days(
        backend, [MON, TUE], "# routine", WCATS, [LECTURE, LAB], NOTES, [], NOW, attempts=1,
        tasks=[task(due=at(MON, "22:00"))], left={"t1": 120},
        routine_days=sleep_only(MON) | {TUE: sleep_only(TUE)[TUE] + [(at(TUE, "12:00"), at(TUE, "13:00"), "Food", "Lunch", False)]})
    assert sorted((c.title, c.new_start) for c in changes) == [
        ("Lunch", at(TUE, "12:00")), ("Report", at(MON, "07:00")), ("Sleep", at(MON, "00:00")),
        ("Sleep", at(TUE, "00:00"))]
    assert summary.startswith("Mon 2030-10-14 planned by rule: the model failed twice (bad json)")
    assert unscheduled == []


def test_a_task_due_on_a_day_too_late_to_plan_and_one_that_got_no_time_are_reported():
    late = at(MON, "23:30")
    tasks = [task(due=at(MON, "23:50")), task(id="t2", title="Taxes", due=None, not_before=at(TUE, "23:00"))]
    _, _, _, unscheduled = plan_days(Small(WeekPlan()), [MON, TUE], "# routine", WCATS, [], NOTES, [], late,
                                     attempts=1, tasks=tasks, left={"t1": 120, "t2": 120})
    assert unscheduled == ["t1: 'Report' is due today - no time left today",
                           "t2: 'Taxes' (no deadline) got no time in the planned days"]


def test_a_flexible_block_moves_to_make_room_for_a_task_and_a_protected_one_does_not():
    busy = [ev("a", "Uni", "Morning", MON, "07:00", "10:00"), LECTURE, LAB, ev("b", "Uni", "Evening", MON, "17:00", "23:59")]
    plan = WeekPlan(blocks=[block(MON, "00:00", "07:00", "Gym", "Sleep"), block(MON, "15:00", "16:00", "Food", "Free time")])
    for kept in (False, True):
        routine = {MON: sleep_only(MON)[MON] + [(at(MON, "15:00"), at(MON, "16:00"), "Food", "Free time", False, kept)]}
        tasks = [task(min_chunk_min=None, due=at(MON, "23:00"))]
        creates, _ = validate(plan, [MON], WCATS, busy, NOTES, [], NOW, tasks=tasks, left={"t1": 120},
                              report_unplaced=True, routine_days=routine, fill_until=MON)
        got = sorted((c.title, c.new_start, c.new_end) for c in creates if c.title != "Sleep")
        assert got == ([("Free time", at(MON, "15:00"), at(MON, "16:00"))] if kept else
                       [("Free time", at(MON, "12:00"), at(MON, "13:00")), ("Report", at(MON, "15:00"), at(MON, "17:00"))])


def test_code_places_an_overdue_task_the_model_left_out():
    plan = WeekPlan(blocks=[block(MON, "00:00", "07:00", "Gym", "Sleep")])
    creates, problems = validate(plan, [MON], WCATS, [LECTURE, LAB], NOTES, [], NOW,
                                 tasks=[task(due=NOW - timedelta(days=1))], left={"t1": 120},
                                 routine_days=sleep_only(MON), fill_until=MON)
    assert [(c.new_start, c.new_end) for c in creates if c.task_id] == [(at(MON, "07:00"), at(MON, "09:00"))]


SLOT_ROUTINE = {MON: [(at(MON, "00:00"), at(MON, "07:00"), "Gym", "Sleep", True, False),
                      (at(MON, "08:00"), at(MON, "10:00"), "Work", "Deep work", False, False),
                      (at(MON, "12:00"), at(MON, "13:00"), "Food", "Lunch", False, True),
                      (at(MON, "13:30"), at(MON, "14:00"), "Food", "Snack", False, False)]}


def test_slots_keep_out_of_events_and_other_routine_but_may_go_over_a_skippable_lecture():
    from dayoptimizer.llm.week_plan import slot_items
    items = slot_items(MON, [LECTURE, LAB], NOW, [task(), task(id="t2", due=at(TUE, "12:00"))],
                       {"t1": 120, "t2": 120}, SLOT_ROUTINE, SKIP)
    # the lecture may be planned over, the lab and the lunch may not; the own routine slot counts as free
    assert list(items["t1"][1]) == ["07:00-09:00", "09:00-11:00", "11:00-12:00", "15:00-17:00", "17:00-19:00"]
    assert "later" in items["t2"][1] and "later" not in items["t1"][1]
    # a flexible routine block under the lab gets the nearest free times, up to two hours away
    assert list(items["Food: Snack (usually 13:30-14:00)"][1]) == [
        "11:30-12:00", "15:00-15:30", "15:15-15:45", "15:30-16:00"]


class Picker:
    """A small model in slot mode that always takes the last slot offered."""
    one_day_at_a_time = True
    slots = True

    def choose(self, system, prompt, schema):
        return {k: {"slot": v["properties"]["slot"]["enum"][-1], "why": "last"}
                for k, v in schema["properties"].items()}


def test_slot_mode_turns_the_picks_into_the_plan():
    changes, _, dropped, unscheduled = plan_days(
        Picker(), [MON], "# routine", WCATS + ["Food"], [LECTURE, LAB], NOTES, SKIP, NOW,
        tasks=[task()], left={"t1": 120}, routine_days=SLOT_ROUTINE)
    assert [(c.new_start, c.new_end, c.reason) for c in changes if c.task_id] == [
        (at(MON, "17:00"), at(MON, "19:00"), "last")]
    assert ("Snack", at(MON, "15:30")) in [(c.title, c.new_start) for c in changes]
    assert unscheduled == []
