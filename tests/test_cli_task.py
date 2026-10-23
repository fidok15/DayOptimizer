import json
from datetime import time
from types import SimpleNamespace
from dayoptimizer import cli, paths
from dayoptimizer.core.storage import Storage
from dayoptimizer.llm.backend import DayRequest, NewEvent, TaskRequest

RULES = SimpleNamespace(categories={"Work": {}, "Learn": {}}, awake=lambda d: (time(5), time(23, 59)))
CONFIG = {"llm": {}}


class Parser:
    def __init__(self, req):
        self.req = req

    def parse_request(self, text, today, now, categories):
        return DayRequest(tasks=[self.req]) if isinstance(self.req, TaskRequest) else self.req


def run(monkeypatch, words, req=None):
    paths.ensure_private_dir()  # main() does this before any command
    calls = []
    monkeypatch.setattr(cli, "_in_bundle", lambda: False)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "_calendar_run", lambda argv, ask=True: calls.append(argv) or "planned")
    monkeypatch.setattr(cli, "make_backend", lambda cfg: Parser(req))
    cli.cmd_task(SimpleNamespace(words=words), RULES, CONFIG)
    return calls


def test_task_is_saved_and_its_days_replanned(monkeypatch):
    req = TaskRequest(title="report", category="Work", duration_minutes=120, due_day="tomorrow")
    calls = run(monkeypatch, ["report", "tomorrow", "2h"], req)
    tasks = Storage(paths.db_path()).open_tasks()
    assert [(t.id, t.title, t.duration_min) for t in tasks] == [("t1", "report", 120)]
    assert calls == [["plan", "--week", "2"]]


def test_task_without_deadline_plans_today_and_tomorrow(monkeypatch):
    calls = run(monkeypatch, ["read", "book"], TaskRequest(title="read", category="Learn", duration_minutes=60))
    assert calls == [["plan", "--week", "2"]]


def test_task_without_length_gets_an_hour_and_says_so(monkeypatch, capsys):
    calls = run(monkeypatch, ["report"], TaskRequest(title="report", category="Work"))
    assert [t.duration_min for t in Storage(paths.db_path()).open_tasks()] == [60]
    assert "assumed 60 min" in capsys.readouterr().out and calls


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


def test_done_replans_so_its_blocks_go(monkeypatch):
    run(monkeypatch, ["x"], TaskRequest(title="report", category="Work", duration_minutes=60, due_day="tomorrow"))
    assert run(monkeypatch, ["done", "t1"]) == [["plan", "--week", "2"]]


def test_several_tasks_are_saved_and_replanned_once(monkeypatch):
    parsed = DayRequest(tasks=[
        TaskRequest(title="laundry", category="Work", duration_minutes=120, due_day="tomorrow"),
        TaskRequest(title="exam prep", category="Learn", duration_minutes=120, due_day="day_after_tomorrow")])
    calls = run(monkeypatch, ["x"], parsed)
    tasks = Storage(paths.db_path()).open_tasks()
    assert sorted((t.id, t.title) for t in tasks) == [("t1", "laundry"), ("t2", "exam prep")]
    assert calls == [["plan", "--week", "3"]]


def test_a_bad_task_is_reported_and_the_rest_saved(monkeypatch, capsys):
    parsed = DayRequest(tasks=[TaskRequest(title="report", category="Gym"),
                               TaskRequest(title="read", category="Learn", duration_minutes=60)])
    run(monkeypatch, ["x"], parsed)
    assert [t.title for t in Storage(paths.db_path()).open_tasks()] == ["read"]
    assert "'Gym' is not one of your categories" in capsys.readouterr().out


def test_no_tasks_says_the_models_reply(monkeypatch, capsys):
    calls = run(monkeypatch, ["hi"], DayRequest(reply="That's not a task."))
    assert calls == [] and "That's not a task." in capsys.readouterr().out


def test_an_open_task_said_again_is_planned_again_not_doubled(monkeypatch, capsys):
    # its blocks were deleted from the calendar: saying it again must bring them back
    req = TaskRequest(title="Report ", category="Work", duration_minutes=60, due_day="tomorrow")
    run(monkeypatch, ["x"], req)
    calls = run(monkeypatch, ["x"], req.model_copy(update={"title": "report"}))
    assert calls == [["plan", "--week", "2"]] and [t.id for t in Storage(paths.db_path()).open_tasks()] == ["t1"]
    assert "your task t1, planned again" in " ".join(capsys.readouterr().out.split())


def test_time_of_day_words_count_only_when_said(monkeypatch):
    run(monkeypatch, ["zrób", "pranie"], TaskRequest(title="pranie", category="Work", when="rano"))
    run(monkeypatch, ["maile", "po", "południu"], TaskRequest(title="maile", category="Work"))
    invented, said = Storage(paths.db_path()).open_tasks()
    assert (invented.not_before, invented.due) == (None, None)
    assert said.due is not None and (said.due.hour, said.not_before.hour) == (18, 12)


def test_a_task_placed_whole_on_a_later_day_is_reported():
    from datetime import date, datetime
    from dayoptimizer.core.models import PlannedChange, Task

    def create(task_id, day, h):
        return PlannedChange(kind="create", category="Work", title="x", reason="r", task_id=task_id,
                             new_start=datetime(2030, 10, day, h).astimezone(),
                             new_end=datetime(2030, 10, day, h + 1).astimezone())
    tasks = [Task(id="t1", title="laundry", category="Work", duration_min=60),
             Task(id="t2", title="report", category="Work", duration_min=120),
             Task(id="t3", title="slides", category="Work", duration_min=60, due=datetime(2030, 10, 17, 12).astimezone())]
    lines = cli._moved([create("t1", 15, 9), create("t2", 15, 9), create("t3", 16, 9)], tasks, date(2030, 10, 14))
    assert lines == ["'laundry': no room today, placed on Tue 15.10 09:00"]


def test_mixed_message_adds_events_and_saves_tasks_in_one_run(monkeypatch):
    parsed = DayRequest(
        events=[NewEvent(title="meeting", category="Work", start_time="14:00"),
                NewEvent(title="read notes", category="Learn")],  # no clock time: a task
        tasks=[TaskRequest(title="laundry", category="Work", duration_minutes=30)])
    calls = run(monkeypatch, ["meeting at 14:00, laundry 30 min, read notes"], parsed)
    assert [t.title for t in Storage(paths.db_path()).open_tasks()] == ["laundry", "read notes"]
    (argv,) = calls
    assert argv[0] == "add" and argv[2:] == ["--week", "2"]
    assert [e["title"] for e in json.loads(argv[1])] == ["meeting"]


def test_chunks_only_when_the_message_asks_to_split(monkeypatch):
    req = TaskRequest(title="nauka", category="Learn", duration_minutes=120, min_chunk_minutes=60)  # the model's idea
    run(monkeypatch, ["jutro", "po", "południu", "nauka", "2h"], req)
    run(monkeypatch, ["nauka", "4h", "w", "kawałkach", "po", "godzinę"], req.model_copy(update={"title": "x", "duration_minutes": 240}))
    assert [t.min_chunk_min for t in Storage(paths.db_path()).open_tasks()] == [None, 60]


def _unfit(monkeypatch, tty, replies):
    from datetime import datetime, timedelta
    from dayoptimizer.core.models import Task
    paths.ensure_private_dir()
    storage = Storage(paths.db_path())
    storage.save_task(Task(id="t1", title="raport", category="Work", duration_min=180,
                           due=datetime.now().astimezone() + timedelta(hours=5)))
    replans, asked = [], []
    monkeypatch.setattr(cli, "_in_bundle", lambda: False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr(cli, "_load_config", lambda: (SimpleNamespace(categories={"Work": {}}, typical_week={}, awake=lambda d: (time(5), time(23, 59))), CONFIG))
    monkeypatch.setattr(cli.console, "input", lambda prompt, **kw: asked.append(prompt) or replies.pop(0))
    monkeypatch.setattr(cli, "_replan_for", lambda tasks, rules, config, ask=True: replans.append(([t.id for t in tasks], ask)))
    cli._note_unplaced(["t1: 'raport' doesn't fit before Thu 2030-10-17 23:59 - missing 180 min"])  # as the bundle does
    cli._decide_unplaced(cli._take_unplaced())
    return storage.get_task("t1"), asked, replans


def test_a_task_that_did_not_fit_is_asked_about_in_the_terminal_and_replanned_once(monkeypatch):
    task, asked, replans = _unfit(monkeypatch, True, ["make it 2h"])
    assert asked[0].startswith("'raport' doesn't fit before Thu 2030-10-17 23:59 - missing 180 min. What should I do?")
    assert task.duration_min == 120
    assert replans == [(["t1"], False)]  # the replan doesn't ask again
    assert not cli._unplaced_file().exists()


def test_no_terminal_no_question(monkeypatch):
    task, asked, replans = _unfit(monkeypatch, False, ["make it 2h"])
    assert (task.duration_min, asked, replans) == (180, [], [])


def test_task_line_says_the_length_fits_somewhere_in_the_window():
    from datetime import datetime
    from dayoptimizer.core.models import Task
    at = lambda d, h, m=0: datetime(2030, 10, d, h, m).astimezone()
    line = lambda **kw: cli._task_line(Task(id="t1", title="ml", category="Learn", duration_min=120, **kw))
    # 120 min some time in the day, not a block from 06:30 to 22:30
    assert line(not_before=at(19, 6, 30), due=at(19, 22, 30)) == \
        "[t1] ml (Learn) 120 min, some time Sat 19.10 06:30-22:30"
    assert line(not_before=at(19, 6, 30), due=at(21, 17)) == \
        "[t1] ml (Learn) 120 min, some time Sat 19.10 06:30 - Mon 21.10 17:00"
    assert line(due=at(21, 17)) == "[t1] ml (Learn) 120 min, by Mon 21.10 17:00"
    assert line(not_before=at(19, 18)) == "[t1] ml (Learn) 120 min, after Sat 19.10 18:00"


def test_no_length_said_and_a_routine_block_of_that_category_is_that_block(monkeypatch, capsys):
    from datetime import date, timedelta
    from dayoptimizer.core.rules import RoutineBlock
    tomorrow = date.today() + timedelta(days=1)
    rules = SimpleNamespace(categories={"Work": {}, "Learn": {}}, awake=RULES.awake,
                            typical_week={tomorrow.weekday(): [RoutineBlock(1110, 1185, "Learn", "Gym", protected=True),
                                                         RoutineBlock(600, 700, "Work", "Chores")]})
    monkeypatch.setattr(cli, "_in_bundle", lambda: False)
    monkeypatch.setattr(cli, "_calendar_run", lambda argv, ask=True: None)
    monkeypatch.setattr(cli, "make_backend", lambda cfg: Parser(TaskRequest(
        title="siłownia", category="Learn", due_day="tomorrow", not_before_day="tomorrow", when="wieczorem")))
    paths.ensure_private_dir()
    cli.cmd_task(SimpleNamespace(words=["jutro wieczorem siłownia"]), rules, CONFIG)
    # 'gym tonight' is the user's own 18:30-19:45 gym block, not one more hour of work next to it
    assert Storage(paths.db_path()).open_tasks() == []
    assert f"'siłownia' is already in your routine: Gym {tomorrow:%a %d.%m} 18:30-19:45" in capsys.readouterr().out


def test_a_plain_routine_block_still_takes_a_task_without_a_length():
    from datetime import datetime
    from dayoptimizer.core.models import Task
    from dayoptimizer.core.rules import RoutineBlock
    mon = datetime(2030, 10, 14, 6, 0).astimezone()
    rules = SimpleNamespace(categories={"Home": {}}, typical_week={0: [RoutineBlock(600, 700, "Home", "Chores")]})
    laundry = Task(id="t1", title="pranie", category="Home", duration_min=60, not_before=mon)
    assert cli._usual_block(rules, laundry) is None  # 'pranie' goes into the Chores time as a task
