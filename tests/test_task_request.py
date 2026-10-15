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
    assert task.not_before == datetime.combine(date(2030, 10, 15), time(0, 0)).astimezone()


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
    assert win("rano") == (at(14, 0), at(14, 12))
    assert win("za 2h") == (at(14, 11, 30), None)
    assert win("in 30 min") == (at(14, 10), None)
    assert win("po pracy", [("Praca", at(14, 16))]) == (at(14, 16), None)
    assert win("po kinie", [("Praca", at(14, 16))]) == (None, None)
    late = datetime(2030, 10, 14, 15, 0).astimezone()
    t, _ = task_from_request(TaskRequest(title="x", category="Work", when="rano"), CATS, late, "t1")
    assert (t.not_before, t.due) == (at(15, 0), at(15, 12))  # morning already gone: tomorrow's


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
