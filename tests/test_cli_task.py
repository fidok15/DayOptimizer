from types import SimpleNamespace
from dayoptimizer import cli, paths
from dayoptimizer.core.storage import Storage
from dayoptimizer.llm.task_request import TaskRequest

RULES = SimpleNamespace(categories={"Work": {}, "Learn": {}})
CONFIG = {"llm": {}}


class Parser:
    def __init__(self, req):
        self.req = req

    def parse_task(self, text, now, categories):
        return self.req


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
