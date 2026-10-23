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
    task, _ = task_from_request(req, CATS, MON, "t1", day_start=time(6))
    assert task.due == datetime.combine(date(2030, 10, 15), time(23, 59)).astimezone()
    # 'jutro zrób X' starts when the user's day starts, never at midnight in their sleep
    assert task.not_before == datetime.combine(date(2030, 10, 15), time(6, 0)).astimezone()


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
    assert win("rano") == (at(14, 5), at(14, 12))  # the night is not morning
    assert win("za 2h") == (at(14, 11, 30), None)
    assert win("in 30 min") == (at(14, 10), None)
    assert win("po pracy", [("Praca", at(14, 16))]) == (at(14, 16), None)
    assert win("po kinie", [("Praca", at(14, 16))]) == (None, None)
    late = datetime(2030, 10, 14, 15, 0).astimezone()
    t, _ = task_from_request(TaskRequest(title="x", category="Work", when="rano"), CATS, late, "t1")
    assert (t.not_before, t.due) == (at(15, 5), at(15, 12))
    t, _ = task_from_request(TaskRequest(title="x", category="Work", when="rano"), CATS, late, "t1",
                             day_start=time(7, 30))
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
