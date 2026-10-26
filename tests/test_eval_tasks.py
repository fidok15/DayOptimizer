import importlib.util
from datetime import datetime
from pathlib import Path

from dayoptimizer.core.models import PlannedChange

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eval_tasks", ROOT / "scripts" / "eval_tasks.py")
eval_tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_tasks)


def test_every_scenario_loads():
    paths = sorted((ROOT / "evals" / "tasks").glob("*.yaml"))
    assert len(paths) == 13
    for p in paths:
        s = eval_tasks.load(p)
        assert s["tasks"] and s["days"] and s["routine"].startswith("# My typical week")
        assert set(s["expect"].get("placed", [])) <= {t.id for t in s["tasks"]}


def create(task_id, start, end):
    return PlannedChange(kind="create", category="Work", title="x", reason="r", task_id=task_id,
                         new_start=datetime(2030, 10, 14, *start).astimezone(),
                         new_end=datetime(2030, 10, 14, *end).astimezone())


def test_score_hard_and_soft():
    s = eval_tasks.load(ROOT / "evals" / "tasks" / "priority-order.yaml")
    ok = [create("t2", (9, 0), (10, 30)), create("t1", (10, 30), (12, 0))]
    assert eval_tasks.score(s, ok, [], []) == []
    swapped = [create("t1", (9, 0), (10, 30)), create("t2", (10, 30), (12, 0))]
    assert eval_tasks.score(s, swapped, [], []) == ["soft: t2 should start before t1"]
    short = [create("t2", (9, 0), (10, 30))]
    assert eval_tasks.score(s, short, ["x broke"], []) == ["rule: x broke", "t1: placed 0 of 90 min"]


def test_outcome_ignores_dropped_blocks_but_clean_does_not():
    s = eval_tasks.load(ROOT / "evals" / "tasks" / "priority-order.yaml")
    ok = [create("t2", (9, 0), (10, 30)), create("t1", (10, 30), (12, 0))]
    fails = eval_tasks.score(s, ok, ["2030-10-14 22:00-22:30 Home: Taxes: ends after the deadline"], [])
    assert eval_tasks.outcome_ok(fails) and not eval_tasks.clean(fails)
    assert not eval_tasks.outcome_ok(eval_tasks.score(s, ok[:1], [], []))
