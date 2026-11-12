import json
from datetime import date, datetime, time

from dayoptimizer.llm.task_request import TaskRequest, task_from_request

CATS = ["Work", "Learn", "Home"]
MON = date(2030, 10, 14)


def test_full_request_becomes_a_task():
    req = TaskRequest(title="raport kwartalny", category="Work", duration_minutes=180, due_day="friday",
                      due_time="17:00", min_chunk_minutes=60, priority="high")
    task, problem = task_from_request(req, CATS, MON, "t4")
    assert problem is None
    assert task.id == "t4" and task.duration_min == 180 and task.min_chunk_min == 60
    assert task.due == datetime.combine(date(2030, 10, 18), time(17, 0)).astimezone()
    assert task.priority == "high" and task.not_before is None


def test_deadline_without_time_is_end_of_day_and_not_before_is_morning():
    req = TaskRequest(title="taxes", category="Home", duration_minutes=60, due_day="tomorrow",
                      not_before_day="tomorrow")
    task, _ = task_from_request(req, CATS, MON, "t1")
    assert task.due == datetime.combine(date(2030, 10, 15), time(23, 59)).astimezone()
    # 'jutro zrób X' fits between the user's sleep, never at midnight or 23:59
    task, _ = task_from_request(req, CATS, MON, "t1", awake=lambda d: (time(6, 30), time(22, 30)))
    assert task.not_before == datetime.combine(date(2030, 10, 15), time(6, 30)).astimezone()
    assert task.due == datetime.combine(date(2030, 10, 15), time(22, 30)).astimezone()


def test_no_duration_is_an_hour():
    task, problem = task_from_request(TaskRequest(title="report", category="Work"), CATS, MON, "t1")
    assert problem is None and task.duration_min == 60


def test_time_of_day_words_become_the_window():
    now = datetime(2030, 10, 14, 9, 30).astimezone()
    at = lambda d, h, m=0: datetime(2030, 10, d, h, m).astimezone()
    win = lambda when, events=(), **kw: (lambda t: (t.not_before, t.due))(task_from_request(
        TaskRequest(title="x", category="Work", when=when, **kw), CATS, now, "t1", events)[0])
    assert win("po południu") == (at(14, 12), at(14, 18))
    assert win("wieczorem", due_day="tomorrow") == (at(15, 18), at(15, 22))
    t, _ = task_from_request(TaskRequest(title="x", category="Work", when="wieczorem"), CATS, now, "t1",
                             awake=lambda d: (time(6), time(21)))
    assert t.due == at(14, 21)  # the evening ends when they go to sleep
    assert win("rano") == (at(14, 5), at(14, 12))  # the night is not morning
    assert win("za 2h") == (at(14, 11, 30), None)
    assert win("in 30 min") == (at(14, 10), None)
    assert win("po pracy", [("Praca", at(14, 16))]) == (at(14, 16), None)
    assert win("po kinie", [("Praca", at(14, 16))]) == (None, None)
    # a routine block of the task's day, named in English, with a part of the day
    breakfast = [("Breakfast", at(14, 7, 30)), ("Breakfast", at(15, 8))]
    assert win("rano po śniadaniu", breakfast, due_day="tomorrow") == (at(15, 8), at(15, 12))
    assert win("po śniadaniu", breakfast, due_day="tomorrow") == (at(15, 8), at(15, 23, 59))
    late = datetime(2030, 10, 14, 15, 0).astimezone()
    t, _ = task_from_request(TaskRequest(title="x", category="Work", when="rano"), CATS, late, "t1")
    assert (t.not_before, t.due) == (at(15, 5), at(15, 12))
    t, _ = task_from_request(TaskRequest(title="x", category="Work", when="rano"), CATS, late, "t1",
                             awake=lambda d: (time(7, 30), time(21)))
    assert t.not_before == at(15, 7, 30)  # the user's day start  # morning already gone: tomorrow's


def test_bad_inputs_are_explained():
    assert "categories" in task_from_request(
        TaskRequest(title="x", category="Gym", duration_minutes=30), CATS, MON, "t1")[1]
    assert "24 hours" in task_from_request(
        TaskRequest(title="x", category="Work", duration_minutes=1500), CATS, MON, "t1")[1]
    assert task_from_request(TaskRequest(), CATS, MON, "t1")[0] is None


def test_chunk_not_shorter_than_task_means_one_piece():
    req = TaskRequest(title="x", category="Work", duration_minutes=60, min_chunk_minutes=60)
    assert task_from_request(req, CATS, MON, "t1")[0].min_chunk_min is None


def test_ollama_parse_request_limits_task_category_to_users(monkeypatch):
    from dayoptimizer.llm.ollama_backend import OllamaBackend
    seen = {}

    def fake_chat(self, system, user, schema=None, timeout=180):
        seen["schema"] = schema
        return json.dumps({"tasks": [{"title": "report", "category": "Work", "duration_minutes": 120}]})

    monkeypatch.setattr(OllamaBackend, "_chat", fake_chat)
    req = OllamaBackend().parse_request("report 2h", "2030-10-14", "Monday 09:00", CATS)
    assert req.tasks[0].duration_minutes == 120
    assert seen["schema"]["$defs"]["TaskRequest"]["properties"]["category"]["enum"] == CATS


def test_a_reply_about_a_task_that_did_not_fit_is_read_by_code_when_easy():
    from dayoptimizer.llm.task_request import quick_fix
    got = {r: (f.action, f.day, f.time, f.minutes, f.chunk_minutes) if (f := quick_fix(r)) else None for r in [
        "usuń to", "nie rób tego", "drop it", "przesuń na piątek", "move it to Friday 14:00", "zrób to w 2h",
        "make it 90 min", "podziel po godzinie", "split into 1h pieces", "usuń przerwę", "nie wiem",
        "możesz zabrać day planning i przerwę"]}
    assert got == {
        "usuń to": ("drop_task", None, None, None, None), "nie rób tego": ("drop_task", None, None, None, None),
        "drop it": ("drop_task", None, None, None, None),
        "przesuń na piątek": ("new_deadline", "friday", None, None, None),
        "move it to Friday 14:00": ("new_deadline", "friday", "14:00", None, None),
        "zrób to w 2h": ("new_duration", None, None, 120, None), "make it 90 min": ("new_duration", None, None, 90, None),
        "podziel po godzinie": ("allow_split", None, None, None, 60),
        "split into 1h pieces": ("allow_split", None, None, None, 60),
        "usuń przerwę": None, "nie wiem": None, "możesz zabrać day planning i przerwę": None}  # the model's


def test_each_fix_changes_the_task():
    from dayoptimizer.core.models import Task
    from dayoptimizer.llm.task_request import TaskFix, apply_fix
    now = datetime.combine(MON, time(9)).astimezone()
    t = Task(id="t1", title="raport", category="Work", duration_min=180,
             due=datetime.combine(MON, time(23, 59)).astimezone())
    fix = lambda **kw: apply_fix(t, TaskFix(**kw), now)
    assert fix(action="drop_task")[0].done
    assert fix(action="new_duration", minutes=120)[0].duration_min == 120
    assert fix(action="allow_split", chunk_minutes=60)[0].min_chunk_min == 60
    new, said = fix(action="new_deadline", day="friday")
    assert new.due == datetime.combine(date(2030, 10, 18), time(23, 59)).astimezone()
    assert said == "move 'raport' deadline to Fri 18.10 23:59"
    assert fix(action="take_routine", blocks=["Day planning", "Break"])[0].may_take == ["Day planning", "Break"]
    assert fix(action="take_routine")[0].may_take == ["*"]
    assert fix(action="unclear") == (None, "")
    assert fix(action="new_deadline") == (None, "")


def test_between_two_hours_is_the_window():
    now = datetime(2030, 10, 14, 9, 30).astimezone()
    at = lambda d, h: datetime(2030, 10, d, h).astimezone()
    win = lambda when, **kw: (lambda t: (t.not_before, t.due))(task_from_request(
        TaskRequest(title="obiad", category="Home", when=when, **kw), CATS, now, "t1")[0])
    assert win("gdzieś między 14 a 16", due_day="tomorrow") == (at(15, 14), at(15, 16))
    assert win("between 14 and 16") == (at(14, 14), at(14, 16))


def test_quick_fix_leaves_next_weeks_day_to_the_model():
    from dayoptimizer.llm.task_request import quick_fix
    assert quick_fix("move it to next Friday") is None
    assert quick_fix("na przyszły piątek") is None
    assert quick_fix("friday").day == "friday"


def test_the_message_and_the_users_own_events_leave_routine_blocks_out():
    from dayoptimizer.core.rules import RoutineBlock
    from dayoptimizer.llm.task_request import skipped_routine, stands_in
    mon, tue = date(2026, 11, 9), date(2026, 11, 10)
    gym, breakfast = RoutineBlock(18 * 60, 19 * 60, "Gym", "Gym"), RoutineBlock(7 * 60, 8 * 60, "Food", "Breakfast")
    week = {0: [gym, breakfast], 1: [gym]}
    text = "zaplanuj mi jutrzejszy dzien, bez silowni, 2h nauka AWS"
    assert skipped_routine(text, week, [mon, tue], date(2026, 11, 8)) == {mon: ["Gym"]}  # only the day said
    assert skipped_routine("no gym, 2h AWS", week, [mon, tue], date(2026, 11, 8)) == {mon: ["Gym"], tue: ["Gym"]}
    assert skipped_routine("bez cukru, 2h AWS", week, [mon], date(2026, 11, 8)) == {}
    assert stands_in("sniadanie", "Food", breakfast) and not stands_in("Kino", "Food", breakfast)


def test_a_skip_belongs_to_its_own_clauses_day_and_an_event_must_name_the_block_whole():
    from dayoptimizer.core.rules import RoutineBlock
    from dayoptimizer.llm.task_request import skipped_routine, stands_in
    mon, tue = date(2026, 11, 9), date(2026, 11, 10)
    gym = RoutineBlock(18 * 60, 19 * 60, "Gym", "Gym")
    week = {0: [gym], 1: [gym]}
    assert skipped_routine("Monday no gym, Tuesday study", week, [mon, tue], date(2026, 11, 8)) == {mon: ["Gym"]}
    assert not stands_in("Breakfast shopping", "Food", RoutineBlock(7 * 60, 8 * 60, "Food", "Breakfast"))


def test_skips_read_lists_and_next_week():
    from dayoptimizer.core.rules import RoutineBlock
    from dayoptimizer.llm.task_request import skipped_routine
    mon, nxt = date(2030, 10, 14), date(2030, 10, 21)
    gym, bf = RoutineBlock(18 * 60, 19 * 60, "Gym", "Gym"), RoutineBlock(7 * 60, 8 * 60, "Food", "Breakfast")
    week = {0: [gym, bf]}
    assert skipped_routine("bez siłowni i śniadania", week, [mon], mon) == {mon: ["Gym", "Breakfast"]}
    assert skipped_routine("bez siłowni i 2h śniadania", week, [mon], mon) == {mon: ["Gym"]}
    assert skipped_routine("next Monday no gym", week, [mon, nxt], mon) == {nxt: ["Gym"]}


def test_a_skip_list_stops_at_the_sentence():
    from dayoptimizer.core.rules import RoutineBlock
    from dayoptimizer.llm.task_request import skipped_routine
    mon = date(2030, 10, 14)
    week = {0: [RoutineBlock(18 * 60, 19 * 60, "Gym", "Gym"), RoutineBlock(7 * 60, 8 * 60, "Food", "Breakfast")]}
    assert skipped_routine("no gym. Breakfast should stay", week, [mon], mon) == {mon: ["Gym"]}


def test_after_work_is_after_the_last_work_block_and_split_keeps_the_total():
    from datetime import date, datetime

    from dayoptimizer.llm.task_request import _after_event, split_lengths
    day = date(2030, 10, 14)
    events = [("Deep work", datetime(2030, 10, 14, 10)), ("Work", datetime(2030, 10, 14, 12)),
              ("Work", datetime(2030, 10, 14, 15))]
    assert _after_event("po pracy zakupy", events, day) == datetime(2030, 10, 14, 15)
    assert split_lengths("rozdział, 6h do czwartku, w kawałkach po 2h") == (360, 120)
    assert split_lengths("thesis chapter, 6h by Thursday, in 2h chunks") == (360, 120)
    assert split_lengths("raport 3h") == (None, None)


def test_split_lengths_skips_a_start_offset():
    from dayoptimizer.llm.task_request import split_lengths
    assert split_lengths("in 3h write report 6h in 2h chunks") == (360, 120)
    assert split_lengths("za 3h raport 6h po 2h") == (360, 120)
