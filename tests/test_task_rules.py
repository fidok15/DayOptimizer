from datetime import date, datetime, time, timedelta
from dayoptimizer.core.models import Event, Task
from dayoptimizer.llm.task_rules import (block_problem, overdue, remaining, task_lines, unplaced, window)

MON = date(2030, 10, 14)
NOW = datetime.combine(MON, time(10, 0)).astimezone()


def at(d, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m)).astimezone()


def task(**kw):
    base = dict(id="t1", title="Report", category="Work", duration_min=180, due=at(MON + timedelta(days=4), "17:00"))
    base.update(kw)
    return Task(**base)


def block(start, end, task_id="t1", d=MON):
    return Event(id=f"b{start}", calendar="Work", title="Report", start=at(d, start), end=at(d, end),
                 managed=True, task_id=task_id)


def test_remaining_subtracts_past_and_running_blocks():
    events = [block("07:00", "08:00"), block("09:30", "10:30"), block("12:00", "13:00"),
              block("07:00", "08:00", task_id="t9")]
    assert remaining([task()], events, NOW) == {"t1": 180 - 60 - 30}


def test_remaining_ignores_done_tasks_and_never_goes_negative():
    assert remaining([task(done=True)], [], NOW) == {}
    assert remaining([task(duration_min=30)], [block("07:00", "09:00")], NOW) == {"t1": 0}


def test_window_starts_at_not_before_or_now():
    assert window(task(), NOW) == (NOW, at(MON + timedelta(days=4), "17:00"))
    later = at(MON + timedelta(days=1), "00:00")
    assert window(task(not_before=later), NOW)[0] == later


def test_overdue_task_has_no_end():
    t = task(due=at(MON - timedelta(days=1), "20:00"))
    assert overdue(t, NOW) and window(t, NOW) == (NOW, None)


def test_task_lines_mark_overdue_and_chunks():
    lines = task_lines([task(min_chunk_min=60, priority="high"), task(id="t2", due=at(MON, "08:00"))],
                       {"t1": 120, "t2": 30}, NOW)
    assert lines[0] == "- [t1] Report (Work) 120 min left, due Fri 2030-10-18 17:00, chunks >= 60 min, priority high"
    assert "OVERDUE since Mon 2030-10-14 08:00" in lines[1] and "in one piece" in lines[1]


def test_task_lines_skip_finished():
    assert task_lines([task()], {"t1": 0}, NOW) == []


def test_block_problems():
    t = task(min_chunk_min=60, not_before=at(MON, "12:00"))
    ok = block_problem(t, "Work", at(MON, "13:00"), at(MON, "14:00"), 180, NOW)
    assert ok is None
    assert "not an open task" in block_problem(None, "Work", at(MON, "13:00"), at(MON, "14:00"), 180, NOW)
    assert "category 'Work'" in block_problem(t, "Learn", at(MON, "13:00"), at(MON, "14:00"), 180, NOW)
    assert "before the task may start" in block_problem(t, "Work", at(MON, "11:00"), at(MON, "12:00"), 180, NOW)
    late = at(MON + timedelta(days=4), "17:30")
    assert "deadline" in block_problem(t, "Work", late - timedelta(hours=1), late, 180, NOW)
    assert "only 30 min" in block_problem(t, "Work", at(MON, "13:00"), at(MON, "14:00"), 30, NOW)
    assert "minimum chunk of 60" in block_problem(t, "Work", at(MON, "13:00"), at(MON, "13:30"), 180, NOW)
    assert block_problem(t, "Work", at(MON, "13:00"), at(MON, "13:30"), 30, NOW) is None


def test_unsplittable_task_needs_one_block_for_all_left():
    t = task(duration_min=90)
    assert "minimum chunk of 90" in block_problem(t, "Work", at(MON, "13:00"), at(MON, "14:00"), 90, NOW)
    assert block_problem(t, "Work", at(MON, "13:00"), at(MON, "14:00"), 60, NOW) is None


def test_unplaced_only_for_tasks_due_within_the_plan():
    due_mon = task(due=at(MON, "22:00"))
    due_fri = task(id="t2")
    late = task(id="t3", due=at(MON - timedelta(days=1), "20:00"))
    out = unplaced([due_mon, due_fri, late], {"t1": 60, "t2": 60, "t3": 30}, set(), MON, NOW)
    assert len(out) == 2 and out[0].startswith("t1: 60 min") and "overdue" in out[1]
    assert unplaced([due_mon], {"t1": 60}, {"t1"}, MON, NOW) == []
    assert unplaced([due_mon], {"t1": 0}, set(), MON, NOW) == []
