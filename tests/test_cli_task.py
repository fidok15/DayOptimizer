from types import SimpleNamespace
from dayoptimizer import cli, paths
from dayoptimizer.core.storage import Storage
from dayoptimizer.llm.task_request import TaskList, TaskRequest

RULES = SimpleNamespace(categories={"Work": {}, "Learn": {}})
CONFIG = {"llm": {}}


class Parser:
    def __init__(self, req):
        self.req = req

    def parse_task(self, text, now, categories):
        return TaskList(tasks=[self.req]) if isinstance(self.req, TaskRequest) else self.req


def run(monkeypatch, words, req=None):
    paths.ensure_private_dir()  # main() does this before any command
    calls = []
    monkeypatch.setattr(cli, "_in_bundle", lambda: False)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "_calendar_run", lambda argv: calls.append(argv) or "planned")
    monkeypatch.setattr(cli, "make_backend", lambda cfg: Parser(req))
    cli.cmd_task(SimpleNamespace(words=words), RULES, CONFIG)
    return calls


def test_task_is_saved_and_its_days_replanned(monkeypatch):
    req = TaskRequest(title="report", category="Work", duration_minutes=120, due_day="tomorrow")
    calls = run(monkeypatch, ["report", "tomorrow", "2h"], req)
    tasks = Storage(paths.db_path()).open_tasks()
    assert [(t.id, t.title, t.duration_min) for t in tasks] == [("t1", "report", 120)]
    assert calls == [["plan", "--week", "2"]]


def test_task_without_deadline_plans_a_week(monkeypatch):
    calls = run(monkeypatch, ["read", "book"], TaskRequest(title="read", category="Learn", duration_minutes=60))
    assert calls == [["plan", "--week", "7"]]


def test_task_without_length_saves_nothing(monkeypatch, capsys):
    calls = run(monkeypatch, ["report"], TaskRequest(title="report", category="Work"))
    assert calls == [] and Storage(paths.db_path()).open_tasks() == []
    assert "How long" in capsys.readouterr().out


def test_list_and_done(monkeypatch, capsys):
    run(monkeypatch, ["x"], TaskRequest(title="report", category="Work", duration_minutes=60))
    run(monkeypatch, ["list"])
    assert "[t1] report (Work) 60 min" in capsys.readouterr().out
    run(monkeypatch, ["done", "t1"])
    assert Storage(paths.db_path()).open_tasks() == []
    run(monkeypatch, ["done", "t7"])
    assert "No task 't7'" in capsys.readouterr().out


def test_main_routes_task_words_to_the_task_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_task", lambda args, rules, config: seen.setdefault("words", args.words))
    monkeypatch.setattr(cli, "_load_config", lambda: (RULES, CONFIG))
    cli.main(["task", "report", "for", "friday"])
    assert seen["words"] == ["report", "for", "friday"]


def test_done_only_removes_blocks_in_the_calendar_bundle_without_a_model(monkeypatch):
    run(monkeypatch, ["x"], TaskRequest(title="report", category="Work", duration_minutes=60))
    run(monkeypatch, ["y"], TaskRequest(title="read", category="Learn", duration_minutes=60))
    monkeypatch.setattr(cli, "make_backend", lambda cfg: (_ for _ in ()).throw(AssertionError("no model")))
    calls = []
    monkeypatch.setattr(cli, "_calendar_run", lambda argv: calls.append(argv))
    cli.cmd_task(SimpleNamespace(words=["done", "t1", "t2"]), RULES, CONFIG)
    assert calls == [["task", "done", "t1", "t2"]] and Storage(paths.db_path()).open_tasks() == []


def test_done_in_the_bundle_deletes_only_that_tasks_future_blocks(monkeypatch):
    from datetime import datetime, timedelta
    from dayoptimizer.core.models import Event
    run(monkeypatch, ["x"], TaskRequest(title="report", category="Work", duration_minutes=60))
    soon = datetime.now().astimezone() + timedelta(hours=2)
    mine = Event(id="a", calendar="Work", title="report", start=soon, end=soon + timedelta(hours=1),
                 managed=True, task_id="t1")
    other = Event(id="b", calendar="Work", title="x", start=soon, end=soon + timedelta(hours=1),
                  managed=True, task_id="t9")
    deleted = []

    class Cal:
        def request_access(self):
            return True

        def list_events(self, start, end):
            return [mine, other]

        def delete_event(self, event_id):
            deleted.append(event_id)

    monkeypatch.setattr(cli, "CalendarClient", Cal)
    monkeypatch.setattr(cli, "_in_bundle", lambda: True)
    cli.cmd_task(SimpleNamespace(words=["done", "t1"]), RULES, CONFIG)
    assert deleted == ["a"]


def test_several_tasks_are_saved_and_replanned_once(monkeypatch):
    parsed = TaskList(tasks=[
        TaskRequest(title="laundry", category="Work", duration_minutes=120, due_day="tomorrow"),
        TaskRequest(title="exam prep", category="Learn", duration_minutes=120, due_day="day_after_tomorrow")])
    calls = run(monkeypatch, ["x"], parsed)
    tasks = Storage(paths.db_path()).open_tasks()
    assert sorted((t.id, t.title) for t in tasks) == [("t1", "laundry"), ("t2", "exam prep")]
    assert calls == [["plan", "--week", "3"]]


def test_a_bad_task_is_reported_and_the_rest_saved(monkeypatch, capsys):
    parsed = TaskList(tasks=[TaskRequest(title="report", category="Work"),
                             TaskRequest(title="read", category="Learn", duration_minutes=60)])
    run(monkeypatch, ["x"], parsed)
    assert [t.title for t in Storage(paths.db_path()).open_tasks()] == ["read"]
    assert "How long will 'report' take?" in capsys.readouterr().out


def test_a_task_already_open_is_not_added_twice(monkeypatch, capsys):
    req = TaskRequest(title="report", category="Work", duration_minutes=60)
    run(monkeypatch, ["x"], req)
    calls = run(monkeypatch, ["x"], TaskRequest(title="Report ", category="Work", duration_minutes=60))
    assert [t.id for t in Storage(paths.db_path()).open_tasks()] == ["t1"] and calls == []
    assert "already open as t1" in capsys.readouterr().out


def test_no_tasks_says_the_models_reply(monkeypatch, capsys):
    calls = run(monkeypatch, ["hi"], TaskList(reply="That's not a task."))
    assert calls == [] and "That's not a task." in capsys.readouterr().out
