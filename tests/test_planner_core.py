from datetime import datetime, date, timedelta
from dayoptimizer.core.models import Event, GarminSummary
from dayoptimizer.core.planner import free_slots, suggest_sleep, resolve_conflicts
from dayoptimizer.core.rules import load_rules
from pathlib import Path

RULES = load_rules(Path(__file__).parent / "fixtures" / "config.yaml")
D = datetime(2026, 7, 3, 0, 0).astimezone()

def _ev(eid, cal, h1, h2, title="x"):
    return Event(id=eid, calendar=cal, title=title,
                 start=D.replace(hour=h1), end=D.replace(hour=h2))

def test_free_slots_between_events():
    events = [_ev("a", "Work", 9, 12), _ev("b", "Meeting", 14, 15)]
    slots = free_slots(events, D.replace(hour=7), D.replace(hour=22))
    assert (D.replace(hour=12), D.replace(hour=14)) in slots
    assert slots[0][0] == D.replace(hour=7)
    assert slots[-1][1] == D.replace(hour=22)

def test_suggest_sleep_adds_debt_after_bad_night():
    bad = GarminSummary(date="2026-07-03", sleep_seconds=5 * 3600, sleep_score=48)
    good = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    first_fixed = D.replace(hour=8) + timedelta(days=1)
    c_bad = suggest_sleep(bad, RULES, first_fixed, date(2026, 7, 3))
    c_good = suggest_sleep(good, RULES, first_fixed, date(2026, 7, 3))
    assert c_bad.new_start < c_good.new_start  # earlier bedtime after bad night
    assert c_bad.category == "Sleep" and not c_bad.requires_approval

def test_suggest_sleep_late_fixed_event_does_not_delay_wake():
    good = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    late_fixed = D.replace(hour=11, minute=30) + timedelta(days=1)
    c = suggest_sleep(good, RULES, late_fixed, date(2026, 7, 3))
    assert c.new_end == (D.replace(hour=8) + timedelta(days=1))  # wake capped at 08:00

def test_suggest_sleep_floors_wake_when_anchor_is_an_all_day_marker():
    # regression: an all-day event (e.g. a multi-week vacation marker) has
    # start=00:00/00:30 — treating it as tomorrow_first_fixed must not pull
    # wake into the previous evening. Floor: never earlier than 05:00 next day.
    good = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    marker_start = D.replace(hour=0, minute=30) + timedelta(days=1)  # 2026-07-04 00:30
    c = suggest_sleep(good, RULES, marker_start, date(2026, 7, 3))
    assert c.new_end == D.replace(hour=5) + timedelta(days=1)  # floored to 05:00
    assert c.new_start == D.replace(hour=21)  # bedtime = floor wake - 8h

def test_suggest_sleep_early_legit_event_wakes_exactly_at_floor():
    good = GarminSummary(date="2026-07-03", sleep_seconds=8 * 3600, sleep_score=85)
    early_fixed = D.replace(hour=6, minute=30) + timedelta(days=1)  # 06:30 next day
    c = suggest_sleep(good, RULES, early_fixed, date(2026, 7, 3))
    assert c.new_end == D.replace(hour=5) + timedelta(days=1)  # 90-min buffer lands on the floor

def test_movable_conflicting_with_fixed_gets_moved():
    events = [_ev("w", "Work", 9, 12), _ev("g", "Gym", 11, 12)]  # gym overlaps work
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1
    ch = changes[0]
    assert ch.kind == "move" and ch.event_id == "g"
    assert ch.new_start >= D.replace(hour=12)  # after the fixed block
    assert not ch.requires_approval

def test_fixed_vs_fixed_conflict_proposes_approval_gated_move():
    events = [_ev("w", "Work", 9, 12, title="Deep review"), _ev("m", "Meeting", 11, 12, title="Standup")]
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1
    ch = changes[0]
    assert ch.kind == "move" and ch.requires_approval
    assert ch.event_id == "m"  # equal priority — the later-starting event is proposed to move
    assert ch.new_start >= D.replace(hour=12)  # into a genuinely free slot
    assert "approval required" in ch.reason
    assert "Deep review" in ch.reason and "Standup" in ch.reason

def test_fixed_vs_fixed_conflict_without_free_slot_keeps_note():
    events = [_ev("w", "Work", 7, 22), _ev("m", "Meeting", 11, 12)]
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1
    assert changes[0].kind == "note" and changes[0].requires_approval
    assert "user decision required" in changes[0].reason

def test_planner_managed_title_in_fixed_category_is_effectively_movable():
    # regression: fill_day creates "Own work" in the fixed Work category; on
    # replan it must be the planner's to move, not a fixed-vs-fixed standoff
    events = [_ev("w", "Work", 9, 12, title="Sprint"), _ev("o", "Work", 11, 13, title="Own work")]
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1
    ch = changes[0]
    assert ch.kind == "move" and ch.event_id == "o"
    assert not ch.requires_approval

def test_sleep_vs_sleep_overlap_is_not_a_conflict():
    # regression: two representations of the same night (one crossing midnight,
    # one created at 00:00 by an earlier replan) are duplicates, not competing
    # blocks — neither may be relocated into the day.
    s1 = Event(id="s1", calendar="Sleep", title="Sleep",
               start=D.replace(hour=23, minute=30), end=D.replace(hour=8) + timedelta(days=1))
    s2 = Event(id="s2", calendar="Sleep", title="Sleep",
               start=D + timedelta(days=1), end=D.replace(hour=8) + timedelta(days=1))
    changes = resolve_conflicts([s1, s2], RULES, D.replace(hour=7), D.replace(hour=23))
    assert not any(c.kind == "move" for c in changes)

def test_sleep_overlapping_fixed_event_notes_instead_of_moving():
    # regression: Sleep is nocturnal — it must never be picked as the mover.
    # Against a fixed event the planner flags the overlap and leaves both.
    meeting = _ev("m", "Meeting", 22, 23, title="Late call")
    sleep = Event(id="s", calendar="Sleep", title="Sleep",
                  start=D.replace(hour=22, minute=30), end=D.replace(hour=8) + timedelta(days=1))
    changes = resolve_conflicts([meeting, sleep], RULES, D.replace(hour=7), D.replace(hour=23))
    assert not any(c.kind == "move" for c in changes)
    note = next(c for c in changes if c.kind == "note")
    assert note.category == "Sleep" and note.event_id == "s"
    assert "Late call" in note.reason

def test_sleep_overlapping_movable_event_moves_the_other():
    # the movable side yields to sleep, never the other way around
    gym = _ev("g", "Gym", 22, 23, title="Workout")
    sleep = Event(id="s", calendar="Sleep", title="Sleep",
                  start=D.replace(hour=22, minute=30), end=D.replace(hour=8) + timedelta(days=1))
    changes = resolve_conflicts([gym, sleep], RULES, D.replace(hour=7), D.replace(hour=23))
    assert len(changes) == 1
    ch = changes[0]
    assert ch.kind == "move" and ch.event_id == "g"

def test_sleep_pairing_note_does_not_drop_remaining_conflicts():
    # regression: the sleep-vs-fixed note used to abort resolution of the
    # current event entirely — an event overlapping BOTH the sleep window and
    # another event had its second conflict silently dropped (no move, no note)
    sleep = Event(id="s", calendar="Sleep", title="Sleep",
                  start=D.replace(hour=21), end=D.replace(hour=8) + timedelta(days=1))
    m1 = Event(id="m1", calendar="Meeting", title="Sync",
               start=D.replace(hour=22), end=D.replace(hour=23))
    m2 = Event(id="m2", calendar="Meeting", title="Retro",
               start=D.replace(hour=22, minute=30), end=D.replace(hour=23, minute=30))
    changes = resolve_conflicts([sleep, m1, m2], RULES, D.replace(hour=7), D.replace(hour=23))
    assert not any(c.kind == "move" and c.category == "Sleep" for c in changes)
    assert any(c.kind == "note" and c.event_id == "s" for c in changes)  # sleep pairing flagged
    # the m2-vs-m1 fixed conflict must still be resolved (approval-gated move)
    m2_move = next(c for c in changes if c.kind == "move" and c.event_id == "m2")
    assert m2_move.requires_approval

def test_movable_overlapping_sleep_and_fixed_still_moves():
    # guard: a movable event touching both the sleep window and a fixed event
    # yields once, into a slot clear of both; sleep itself never moves
    sleep = Event(id="s", calendar="Sleep", title="Sleep",
                  start=D.replace(hour=21), end=D.replace(hour=8) + timedelta(days=1))
    m = Event(id="m", calendar="Meeting", title="Sync",
              start=D.replace(hour=21, minute=30), end=D.replace(hour=22, minute=30))
    gym = Event(id="g", calendar="Gym", title="Workout",
                start=D.replace(hour=22), end=D.replace(hour=23))
    changes = resolve_conflicts([sleep, m, gym], RULES, D.replace(hour=7), D.replace(hour=23))
    g_move = next(c for c in changes if c.kind == "move" and c.event_id == "g")
    assert g_move.new_end <= D.replace(hour=21)  # clear of sleep and the meeting
    assert not any(c.kind == "move" and c.category == "Sleep" for c in changes)

def test_no_conflicts_no_changes():
    events = [_ev("w", "Work", 9, 12), _ev("g", "Gym", 17, 18)]
    assert resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22)) == []

def test_movable_vs_movable_priority_tiebreak_moves_lower_priority():
    # "Free time" (priority 2) vs "Food" (priority 6) — lower priority number moves.
    events = [_ev("f", "Free time", 9, 11), _ev("d", "Food", 10, 11)]
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1
    ch = changes[0]
    assert ch.kind == "move" and ch.event_id == "f"
    assert not ch.requires_approval

def test_movable_overlapping_two_fixed_events_gets_fully_resolved():
    events = [_ev("w", "Work", 9, 11), _ev("m", "Meeting", 11, 12), _ev("g", "Gym", 10, 13)]
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1  # only one final change for "g", not one per bump
    ch = changes[0]
    assert ch.kind == "move" and ch.event_id == "g"
    work_start, work_end = D.replace(hour=9), D.replace(hour=11)
    meeting_start, meeting_end = D.replace(hour=11), D.replace(hour=12)
    assert not (ch.new_start < work_end and work_start < ch.new_end)
    assert not (ch.new_start < meeting_end and meeting_start < ch.new_end)

def test_fallback_slot_before_original_start_notes_it_in_reason():
    events = [_ev("w", "Work", 12, 22), _ev("g", "Gym", 13, 14)]
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1
    ch = changes[0]
    assert ch.kind == "move" and ch.event_id == "g"
    assert ch.new_start < D.replace(hour=13)  # moved earlier than its original start
    assert "earlier" in ch.reason

def test_no_free_slot_anywhere_records_note():
    events = [_ev("w", "Work", 7, 22), _ev("g", "Gym", 10, 11)]
    changes = resolve_conflicts(events, RULES, D.replace(hour=7), D.replace(hour=22))
    assert len(changes) == 1
    assert changes[0].kind == "note" and changes[0].event_id == "g"
