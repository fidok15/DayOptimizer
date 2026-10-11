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


def test_no_duration_asks_for_it():
    task, problem = task_from_request(TaskRequest(title="report", category="Work"), CATS, MON, "t1")
    assert task is None and "How long" in problem


def test_bad_inputs_are_explained():
    assert "categories" in task_from_request(
        TaskRequest(title="x", category="Gym", duration_minutes=30), CATS, MON, "t1")[1]
    assert "24 hours" in task_from_request(
        TaskRequest(title="x", category="Work", duration_minutes=1500), CATS, MON, "t1")[1]
    assert task_from_request(TaskRequest(reply="That's not a task."), CATS, MON, "t1") == (None, "That's not a task.")


def test_chunk_not_shorter_than_task_means_one_piece():
    req = TaskRequest(title="x", category="Work", duration_minutes=60, min_chunk_minutes=60)
    assert task_from_request(req, CATS, MON, "t1")[0].min_chunk_min is None


def test_ollama_parse_task_limits_category_to_users(monkeypatch):
    from dayoptimizer.llm.ollama_backend import OllamaBackend
    seen = {}

    def fake_chat(self, system, user, schema=None, timeout=180):
        seen["schema"] = schema
        return json.dumps({"title": "report", "category": "Work", "duration_minutes": 120})

    monkeypatch.setattr(OllamaBackend, "_chat", fake_chat)
    req = OllamaBackend().parse_task("report 2h", now="Monday 2030-10-14 09:00", categories=CATS)
    assert req.duration_minutes == 120
    assert seen["schema"]["properties"]["category"]["enum"] == CATS + [""]
