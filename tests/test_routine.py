import stat
from dayoptimizer import paths
from dayoptimizer.llm.backend import request_prompt
from dayoptimizer.routine import load_routine, render_routine, save_routine

WORK = [{"start": "09:00", "end": "17:00", "category": "Work", "title": ""},
        {"start": "18:00", "end": "19:30", "category": "Gym", "title": "Push day"}]
CATS = {"Work": {"movable": False, "priority": 9}, "Gym": {"movable": True, "priority": 5}}


def test_render_merges_identical_days():
    week = {d: WORK for d in ("mon", "tue", "wed", "thu", "fri")} | {"sat": [WORK[1]]}
    text = render_routine(CATS, week)
    assert "## Mon-Fri\n09:00-17:00 Work\n18:00-19:30 Gym: Push day" in text
    assert "## Sat\n18:00-19:30 Gym: Push day" in text and "## Sun\n(nothing drawn)" in text
    assert text.index("- Work: fixed, priority 9") < text.index("- Gym: flexible, priority 5")


def test_render_non_consecutive_days():
    assert "## Mon, Wed\n" in render_routine(CATS, {"mon": WORK, "wed": WORK})


def test_saved_routine_is_private_and_reaches_the_llm_prompt():
    save_routine(render_routine(CATS, {"mon": WORK}))
    assert stat.S_IMODE(paths.routine_path().stat().st_mode) == 0o600
    assert "Push day" in load_routine()
    assert "Push day" in request_prompt("gym tomorrow", "2026-09-22", "Tuesday 09:00", ["Gym"])


def test_prompt_without_routine():
    assert "routine" not in request_prompt("x", "2026-09-22", "Tuesday 09:00", ["Gym"])
