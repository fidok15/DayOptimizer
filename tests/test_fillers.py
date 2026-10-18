from dataclasses import replace
from datetime import date, datetime, time, timedelta
from dayoptimizer.core.constraints import parse_rules
from dayoptimizer.core.models import Event
from dayoptimizer.core.rules import CategoryRule, RoutineBlock, Rules
from dayoptimizer.core.storage import Storage
from dayoptimizer.llm.fillers import Filler, Fillers, bare, check, day_gaps, suggest, record, suffix

SAT = date(2026, 10, 17)
SUN = SAT + timedelta(days=1)
MON = SAT + timedelta(days=2)
NOW = datetime(2026, 10, 17, 12, 7).astimezone()
CATS = ["Sleep", "Food", "Gym", "Free"]
GYM_2 = parse_rules([{"type": "max_per_week", "category": "Gym", "count": 2, "source": "Gym at most 2 times a week."},
                     {"type": "not_after", "category": "Free", "time": "22:00", "source": "Nothing after 22."}])


def at(d, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m)).astimezone()


def rules(**kw):
    week = {d: [RoutineBlock(0, 420, "Sleep", "Sen"), RoutineBlock(780, 840, "Food", "Obiad"),
                RoutineBlock(1380, 1440, "Sleep", "Sen")] for d in range(7)}
    base = dict(categories={c: CategoryRule(movable=True) for c in CATS}, gym_per_week=0, meal_windows=[],
                min_free_minutes=60, deep_work_minutes=60, sleep_target_hours=8, morning_buffer_minutes=0,
                note_rules=GYM_2, typical_week=week, day_start=time(6), day_end=time(23))
    base.update(kw)
    return Rules(**base)


def ev(id, cal, title, d, s, e, **kw):
    return Event(id=id, calendar=cal, title=title, start=at(d, s), end=at(d, e), **kw)


def plan(d):  # the planner's blocks of a day: sleep, lunch, sleep
    return [ev(f"s{d.day}", "Sleep", "Sen", d, "00:00", "07:00", managed=True),
            ev(f"o{d.day}", "Food", "Obiad", d, "13:00", "14:00", managed=True),
            ev(f"n{d.day}", "Sleep", "Sen", d, "23:00", "23:59", managed=True)]


class Model:
    """Proposes what it is given, and counts the calls."""
    def __init__(self, *fillers):
        self.fillers, self.calls, self.prompts = list(fillers), 0, []

    def structured(self, system, prompt, model, schema=None):
        self.calls += 1
        self.prompts.append(prompt)
        return Fillers(fillers=self.fillers)


class Cal:
    def __init__(self, events):
        self.events = list(events)

    def apply(self, changes):
        gone = {c.event_id for c in changes if c.kind == "delete"}
        self.events = [e for e in self.events if e.id not in gone]
        for i, c in enumerate(c for c in changes if c.kind == "create"):
            c.event_id = f"f{len(self.events)}-{i}"
            self.events.append(Event(id=c.event_id, calendar=c.category, title=c.title, start=c.new_start,
                                     end=c.new_end, managed=True, suggested=c.suggested))


def f(start, end, title="Czytanie", cat="Free", day=SAT):
    return Filler(day=day.isoformat(), start=start, end=end, category=cat, title=title)


def run(model, cal, storage, r=None, days=(SAT, SUN), now=NOW):
    changes, refused = suggest(model, list(days), cal.events, storage, r or rules(), "Lubię czytać.", CATS, now)
    cal.apply(changes)
    record([c for c in changes if c.kind == "create"], storage)
    return changes, refused


def test_gaps_start_now_on_the_quarter_and_stay_in_waking_hours():
    gaps = day_gaps(SAT, plan(SAT), NOW, (time(6), time(23)))
    assert gaps == [(at(SAT, "12:15"), at(SAT, "13:00")), (at(SAT, "14:00"), at(SAT, "23:00"))]


def test_only_today_and_tomorrow_get_suggestions_and_the_minimum_free_time_stays():
    model = Model(f("14:00", "15:30"), f("16:00", "17:30", "Spacer"), f("09:00", "10:00", "Kino", day=MON))
    cal = Cal(plan(SAT) + plan(SUN) + plan(MON))
    changes, refused = run(model, cal, Storage(":memory:"), rules(min_free_minutes=480), days=(SAT, SUN, MON))
    # Saturday has 45 + 540 min free from now: 105 may be filled, so the second suggestion must go
    assert [(c.title, c.new_start) for c in changes] == [("Czytanie (sugestia)", at(SAT, "14:00"))]
    assert any("minimum free time" in r for r in refused) and any("not a day to fill" in r for r in refused)
    assert "2026-10-19" not in model.prompts[0]


def test_code_refuses_what_breaks_a_rule():
    asks = {SAT: [(at(SAT, "14:00"), at(SAT, "23:00"))]}
    history = {"Gym": [SAT - timedelta(days=4), SAT - timedelta(days=2)]}
    kept, refused = check(
        [f("14:00", "14:20"), f("19:00", "21:00", "Joga"), f("14:00", "15:00", cat="Nope"), f("14:00", "15:00", "Siłka", "Gym"),
         f("21:30", "22:30"), f("12:00", "13:00"), f("15:00", "16:00", "Kino"), f("16:00", "17:00", "Spacer (sugestia)"),
         f("17:00", "18:00", "Czytanie"), f("18:00", "19:00", "czytanie")],
        asks, CATS, rules(), history, recent=[(SAT - timedelta(days=1), "spacer")], unwanted={"kino"},
        budget={SAT: 600})
    # too long is cut to 90 min (a small model takes the whole gap), too short goes
    assert [(x[2].title, x[2].end) for x in kept] == [("Joga", "20:30"), ("Czytanie", "18:00")]
    why = [r.rsplit(": ", 1)[1] for r in refused]
    assert why == ["not 30-90 min", "not one of the categories",
                   'breaks the note "Gym at most 2 times a week."', 'breaks the note "Nothing after 22."',
                   "not inside a free gap", "you removed it lately", "suggested lately (variety)",
                   "suggested lately (variety)"]


def test_a_whole_gap_taken_is_cut_to_what_the_day_may_fill():
    kept, _ = check([f("18:15", "20:00")], {SAT: [(at(SAT, "18:15"), at(SAT, "20:00"))]}, CATS, rules(), {}, [],
                    set(), {SAT: 60})
    assert [(s, e) for s, e, _ in kept] == [(at(SAT, "18:15"), at(SAT, "19:15"))]


def test_a_title_is_one_short_line_and_an_empty_one_is_refused():
    long = f("14:00", "15:00", "Read\n  a  book" + "x" * 100)
    long.why = "calm\nevening " * 20
    kept, refused = check([long, f("16:00", "17:00", " \n (sugestia)")], {SAT: [(at(SAT, "14:00"), at(SAT, "23:00"))]},
                          CATS, rules(), {}, [], set(), {SAT: 600})
    [(_, _, x)] = kept
    assert x.title == ("Read a book" + "x" * 100)[:40] and "\n" not in x.why and len(x.why) == 120
    assert refused[0].endswith("no title")


def test_a_copy_of_the_users_own_event_is_refused():
    cal = Cal(plan(SAT) + [ev("u1", "Food", "Kawa z Olą", SAT - timedelta(days=2), "10:00", "11:00")])
    changes, refused = run(Model(f("14:00", "15:00", "kawa z olą (sugestia)")), cal, Storage(":memory:"), days=(SAT,))
    assert changes == [] and refused[0].endswith("a copy of one of your own events")


def test_variety_low_lets_a_title_come_back_the_next_day():
    asks = {SUN: [(at(SUN, "14:00"), at(SUN, "23:00"))]}
    args = (asks, CATS)
    kw = dict(history={}, recent=[(SAT, "czytanie")], unwanted=set(), budget={SUN: 600})
    assert check([f("14:00", "15:00", day=SUN)], *args, rules(variety="low"), **kw)[0]
    assert not check([f("14:00", "15:00", day=SUN)], *args, rules(variety="medium"), **kw)[0]


def test_a_second_run_changes_nothing_and_asks_no_model():
    storage, cal = Storage(":memory:"), Cal(plan(SAT) + plan(SUN))
    first = Model(f("14:00", "15:00"), f("18:00", "19:00", "Spacer", day=SUN))
    changes, _ = run(first, cal, storage)
    assert len(changes) == 2 and all(c.suggested for c in changes)
    again = Model(f("16:00", "17:00", "Kino"))
    assert run(again, cal, storage, now=NOW + timedelta(minutes=15))[0] == [] and again.calls == 0


def test_a_suggestion_something_took_goes_and_its_time_is_offered_again():
    storage, cal = Storage(":memory:"), Cal(plan(SAT))
    run(Model(f("14:00", "15:30")), cal, storage, days=(SAT,))
    cal.events.append(ev("u1", "Gym", "Trening", SAT, "14:00", "14:30"))  # the user's new event
    model = Model(f("14:30", "15:30", "Spacer"))
    changes, _ = run(model, cal, storage, days=(SAT,))
    assert [(c.kind, c.title) for c in changes] == [("delete", "Czytanie (sugestia)"), ("create", "Spacer (sugestia)")]
    assert "Gaps to fill: 14:30-15:30;" in model.prompts[0]


def test_a_suggestion_the_planner_hid_and_then_covered_goes_even_if_it_started_meanwhile():
    # the plan started at 12:55 (the suggestion was still ahead, so hidden from it) and took 8 minutes
    cal = Cal([ev("x1", "Free", "Spacer (sugestia)", SAT, "13:00", "14:00", managed=True, suggested=True),
               ev("t1", "Free", "Essay", SAT, "13:00", "14:00", managed=True)])
    changes, _ = suggest(Model(), [SAT], cal.events, Storage(":memory:"), rules(typical_week={}), "", CATS,
                         at(SAT, "13:03"), hidden_since=at(SAT, "12:55"))
    assert [(c.kind, c.event_id) for c in changes] == [("delete", "x1")]


def test_a_day_left_short_of_its_minimum_free_time_loses_its_newest_suggestions():
    storage, cal = Storage(":memory:"), Cal(plan(SAT))
    run(Model(f("14:00", "15:00"), f("16:00", "17:00", "Spacer")), cal, storage, days=(SAT,))
    cal.events.append(ev("u1", "Gym", "Trening", SAT, "17:00", "22:15"))  # 465 min left free
    changes, _ = run(Model(), cal, storage, days=(SAT,), r=rules(min_free_minutes=480))
    assert [(c.kind, c.title) for c in changes] == [("delete", "Spacer (sugestia)")]
    assert [r["status"] for r in storage.fillers_since("2026-10-01")] == ["placed", "removed"]


def test_a_suggestion_the_user_deleted_leaves_its_time_free_and_is_not_wanted():
    storage, cal = Storage(":memory:"), Cal(plan(SAT))
    run(Model(f("14:00", "15:30")), cal, storage, days=(SAT,))
    cal.events = [e for e in cal.events if not e.suggested]
    model = Model(f("14:00", "15:00", "Czytanie"))
    assert run(model, cal, storage, days=(SAT,))[0] == [] and model.calls == 0
    assert [r["status"] for r in storage.fillers_since("2026-10-01")] == ["deleted"]
    # the next day it is on the avoid list
    cal = Cal(plan(SUN))
    model = Model(f("14:00", "15:00", "Czytanie", day=SUN))
    changes, refused = run(model, cal, storage, days=(SUN,), now=NOW + timedelta(days=1))
    assert changes == [] and "never suggest them: Czytanie" in model.prompts[0]


def test_a_suggestion_whose_id_a_resync_changed_is_not_taken_for_deleted():
    storage, cal = Storage(":memory:"), Cal(plan(SAT))
    run(Model(f("14:00", "15:00")), cal, storage, days=(SAT,))
    cal.events = [replace(e, id="new-" + e.id) if e.suggested else e for e in cal.events]
    run(Model(), cal, storage, days=(SAT,), now=NOW + timedelta(minutes=15))
    [row] = storage.fillers_since("2026-10-01")
    assert row["status"] == "placed" and row["event_id"].startswith("new-")


def test_a_suggestion_the_user_moved_stays_where_they_put_it():
    storage, cal = Storage(":memory:"), Cal(plan(SAT) + [ev("u1", "Gym", "Trening", SAT, "18:00", "19:00")])
    run(Model(f("14:00", "15:00")), cal, storage, days=(SAT,))
    cal.events = [replace(e, start=at(SAT, "18:00"), end=at(SAT, "19:00")) if e.suggested else e for e in cal.events]
    for minutes_later in (5, 20):  # and the next run too
        changes, _ = run(Model(), cal, storage, days=(SAT,), now=NOW + timedelta(minutes=minutes_later))
        assert changes == []
    [row] = storage.fillers_since("2026-10-01")
    assert (row["status"], row["start"]) == ("moved", at(SAT, "18:00").isoformat())


def test_a_replan_neither_sees_nor_removes_suggestions_and_a_second_one_changes_nothing(monkeypatch):
    from dayoptimizer import cli
    from dayoptimizer.llm.week_plan import WeekPlan
    tomorrow = date.today() + timedelta(days=1)

    class Backend(Model):
        plan_prompts: list = []

        def plan_week(self, system, prompt, schema=None):
            self.plan_prompts.append(prompt)
            return WeekPlan()

    class Calendar(Cal):
        def list_events(self, start, end):
            return [e for e in self.events if start <= e.start < end]

        def create_event(self, category, title, start, end, task_id=None, suggested=False):
            self.events.append(Event(id=f"c{len(self.events)}", calendar=category, title=title, start=start, end=end,
                                     managed=True, suggested=suggested))
            return self.events[-1].id

        def delete_event(self, event_id):
            self.events = [e for e in self.events if e.id != event_id]

    cal = Calendar([ev("u1", "Food", "Lunch with Ann", tomorrow, "13:00", "14:00")])
    monkeypatch.setattr(cli, "_load_config", lambda: (None, {"categories": {c: {} for c in CATS}, "llm": {},
                                                             "notes": "I like books."}))
    storage = Storage(":memory:")
    for run_no in range(2):
        backend = Backend(f("10:00", "11:00", "Reading", day=tomorrow))
        backend.plan_prompts = []
        monkeypatch.setattr("dayoptimizer.llm.backend.planning_backends", lambda cfg: [backend])
        changes, applied, *_ = cli._llm_plan([tomorrow], cal, storage, rules(note_rules=[]), confirm=lambda c: True)
        if run_no == 0:
            assert [(c.title, c.new_start) for c in applied] == [("Reading (suggestion)", at(tomorrow, "10:00"))]
        else:  # the planner didn't see it (so its plan didn't drop it), and the model wasn't asked again
            assert changes == [] and backend.calls == 0 and "Reading" not in backend.plan_prompts[0]
    assert [r["title"] for r in storage.fillers_since(date.today().isoformat())] == ["Reading (suggestion)"]


def test_free_time_replies_are_read_without_a_model():
    from dayoptimizer.cli import understand_free_time as minutes_of, understand_variety as variety_of
    assert [minutes_of(x) for x in ("godzinkę", "1h", "90 min", "1,5h", "pół godziny", "dwie godziny", "45", "2",
                                    "półtorej godziny", "an hour", "nic", "hmm", "1h 30min", "1 godz. 30 min",
                                    "1h30")] == [
        60, 60, 90, 90, 30, 120, 45, 120, 90, 60, 0, None, 90, 90, 90]
    assert [variety_of(x) for x in ("dużo", "średnio", "mało", "high", "whatever", "not much", "nie za dużo",
                                    "niewiele", "nie wiem")] == [
        "high", "medium", "low", "high", None, "low", "low", "low", None]


def test_the_free_time_question_is_asked_once_in_a_terminal_and_saved(monkeypatch):
    import yaml
    from dayoptimizer import cli, paths
    from dayoptimizer.onboarding import save_user_config
    save_user_config(yaml.safe_dump({"typical_week": {"mon": [{"start": "09:00", "end": "10:00", "category": "Gym"}]},
                                     "categories": {"Gym": {"movable": True}}}))
    monkeypatch.setattr(cli, "_in_bundle", lambda: False)
    replies = iter(["godzinkę", "dużo"])
    monkeypatch.setattr(cli.console, "input", lambda *a, **k: next(replies))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    cli._ask_free_time({"llm": {}})  # no terminal: nothing asked, nothing saved
    assert "day_rules" not in yaml.safe_load(paths.user_config_path().read_text())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    cli._ask_free_time({"llm": {}})
    cli._ask_free_time({"llm": {}})  # asked once: a second call would run out of replies
    assert yaml.safe_load(paths.user_config_path().read_text())["day_rules"] == {"min_free_minutes": 60,
                                                                                "variety": "high"}


def test_ctrl_c_at_the_free_time_question_stops_and_a_config_that_wont_save_doesnt(monkeypatch):
    import yaml
    from dayoptimizer import cli, onboarding, paths
    onboarding.save_user_config(yaml.safe_dump({"typical_week": {"mon": [{"start": "09:00", "end": "10:00",
                                                                           "category": "Gym"}]},
                                                "categories": {"Gym": {"movable": True}}}))
    monkeypatch.setattr(cli, "_in_bundle", lambda: False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)

    def replies(*answers):
        it = iter(answers)

        def ask(*a, **k):
            x = next(it)
            if isinstance(x, BaseException):
                raise x
            return x
        monkeypatch.setattr(cli.console, "input", ask)
    replies("1h", KeyboardInterrupt())
    assert cli._ask_free_time({"llm": {}}) is False  # the command stops, the first answer isn't kept
    assert "day_rules" not in yaml.safe_load(paths.user_config_path().read_text())

    def broken(text):
        raise onboarding.ConfigError("Invalid config: notes too long")
    monkeypatch.setattr(onboarding, "save_user_config", broken)
    replies("1h", "dużo")
    assert cli._ask_free_time({"llm": {}}) is True  # a note, and the plan goes on


def test_no_model_now_means_no_suggestions_and_the_gaps_are_offered_next_time():
    class Down(Model):
        def structured(self, *a, **k):
            raise RuntimeError("Ollama isn't running")
    storage, cal = Storage(":memory:"), Cal(plan(SAT))
    assert run(Down(), cal, storage, days=(SAT,)) == ([], ["no suggestions: Ollama isn't running"])
    model = Model(f("14:00", "15:00"))
    assert len(run(model, cal, storage, days=(SAT,))[0]) == 1 and model.calls == 1


def test_the_suggestion_mark_follows_the_notes_language():
    assert suffix("Siłownia 2 razy w tygodniu") == "(sugestia)" and suffix("Gym twice a week") == "(suggestion)"
    assert suffix("") == "(suggestion)" and bare(" Czytanie  (sugestia)") == "czytanie"


def test_suggestions_keep_out_of_routine_time_unless_the_block_moved_or_the_notes_skip_it():
    # live: a replan lost part of Study and Deep work, and suggestions filled their usual time
    week = {d: rules().typical_week[d] + [RoutineBlock(900, 1080, "Free", "Nauka"), RoutineBlock(1110, 1185, "Gym", "Gym")]
            for d in range(7)}
    gyms = [ev(f"g{i}", "Gym", "Gym", SAT - timedelta(days=i), "18:30", "19:45", managed=True) for i in (3, 5)]
    moved = [e if e.title != "Obiad" else replace(e, start=at(SAT, "14:00"), end=at(SAT, "15:00")) for e in plan(SAT)]
    model = Model()
    run(model, Cal(moved + gyms), Storage(":memory:"), rules(typical_week=week), days=(SAT,))
    # lunch moved (its hour is free), Nauka is missing but its time is not free, the notes skip the gym
    assert "Gaps to fill: 12:15-14:00, 18:00-23:00;" in model.prompts[0]


def test_the_model_is_told_outright_to_write_titles_in_the_notes_language():
    class Spy(Model):
        def structured(self, system, prompt, model, schema=None):
            self.system = system
            return super().structured(system, prompt, model, schema)
    model = Spy()
    run(model, Cal(plan(SAT)), Storage(":memory:"), days=(SAT,))  # notes: "Lubię czytać."
    assert "in Polish" in model.system and "Spacer" in model.system
    changes, _ = suggest(model, [SAT], plan(SAT), Storage(":memory:"), rules(), "I like reading.", CATS, NOW)
    assert "in English" in model.system and "in Polish" not in model.system


def test_an_open_blocks_usual_time_is_never_free_for_suggestions():
    # its pieces may be anywhere in it (or a task took one): the time stays the open block's
    from dayoptimizer.llm.fillers import routine_time
    open_ = [RoutineBlock(600, 720, "Free", "coś produktywnego", intent="coś produktywnego"),
             RoutineBlock(900, 1020, "Free", "coś produktywnego", intent="coś produktywnego")]
    piece = [ev("p", "Free", "coś produktywnego", SAT, "16:00", "17:00", managed=True)]
    assert routine_time(SAT, rules(typical_week={d: open_ for d in range(7)}), piece) == [
        (at(SAT, "10:00"), at(SAT, "12:00")), (at(SAT, "15:00"), at(SAT, "17:00"))]


def open_rules(intent="coś relaksującego", cat="Free", **kw):
    week = {d: rules().typical_week[d] + [RoutineBlock(1080, 1260, cat, intent, intent=intent)] for d in range(7)}
    return rules(typical_week=week, **kw)


def holder(d=SAT, s="18:00", e="21:00", title="coś relaksującego", cat="Free"):
    return ev(f"ph{s}", cat, title, d, s, e, managed=True)


def test_an_open_block_gets_activities_of_their_own_length_and_keeps_only_a_leftover_of_30_min():
    storage, cal = Storage(":memory:"), Cal(plan(SAT) + [holder()])
    model = Model(f("18:00", "19:00"), f("19:15", "20:15", "Spacer", cat="Nope"), f("20:30", "21:30", "Kino"),
                  f("20:15", "20:30", "Joga"))
    # no free time to spare in gaps: an open block is filled anyway
    changes, refused = run(model, cal, storage, open_rules(min_free_minutes=1000), days=(SAT,))
    assert "Open block to fill: 18:00-21:00 Free, meant for: coś relaksującego" in model.prompts[0]
    assert "Gaps to fill" not in model.prompts[0]
    # a break of 15 min stays empty, 45 min left at the end keep the placeholder; an unknown category is the block's
    assert [(c.kind, c.title, c.category, c.new_start) for c in changes] == [
        ("create", "Czytanie (sugestia)", "Free", at(SAT, "18:00")), ("create", "Spacer (sugestia)", "Free", at(SAT, "19:15")),
        ("delete", "coś relaksującego", "Free", None), ("create", "coś relaksującego", "Free", at(SAT, "20:15"))]
    assert [r.rsplit(": ", 1)[1] for r in refused] == ["not inside a free gap", "under 30 min"]
    again = Model(f("20:15", "21:00", "Kino"))
    assert run(again, cal, storage, open_rules(min_free_minutes=1000), days=(SAT,), now=NOW + timedelta(minutes=15))[0] == []
    assert again.calls == 0


def test_a_productive_block_may_take_a_course_as_its_topic_but_never_copies_a_meeting():
    mine = [ev("u1", "Uni", "Systemy operacyjne", MON, "10:00", "12:00"),
            ev("u2", "Free", "Spotkanie z Anią", SAT - timedelta(days=1), "18:00", "19:00")]
    model = Model(f("18:00", "19:30", "Powtórka: Systemy operacyjne"), f("19:45", "21:00", "Spotkanie z Anią"))
    changes, refused = run(model, Cal(plan(SAT) + mine + [holder(title="coś produktywnego")]), Storage(":memory:"),
                           open_rules("coś produktywnego"), days=(SAT,))
    assert "study topics): Systemy operacyjne" in model.prompts[0]
    assert [c.title for c in changes if c.suggested] == ["Powtórka: Systemy operacyjne (sugestia)"]
    assert refused[0].endswith("a copy of one of your own events")


def test_no_model_keeps_the_whole_placeholder_and_a_deleted_activity_leaves_it_a_placeholder_that_day():
    class Down(Model):
        def structured(self, *a, **k):
            raise RuntimeError("Ollama isn't running")
    storage, cal = Storage(":memory:"), Cal(plan(SAT) + [holder()])
    assert run(Down(), cal, storage, open_rules(), days=(SAT,))[0] == []
    run(Model(f("18:00", "19:00")), cal, storage, open_rules(), days=(SAT,))
    assert sorted(e.title for e in cal.events if e.start >= at(SAT, "18:00") and e.end <= at(SAT, "21:00")) == [
        "Czytanie (sugestia)", "coś relaksującego"]
    # the user deletes the activity; the planner puts the placeholder back over its time
    cal.events = [e for e in cal.events if not at(SAT, "18:00") <= e.start < at(SAT, "21:00")] + [holder()]
    model = Model(f("18:00", "19:00", "Kino"))
    assert run(model, cal, storage, open_rules(), days=(SAT,), now=NOW + timedelta(minutes=15))[0] == []
    assert model.calls == 0


def test_a_replan_puts_an_open_block_back_only_around_its_activities_and_an_event_over_one_shrinks_it(monkeypatch):
    from dayoptimizer import cli
    from dayoptimizer.llm.week_plan import WeekPlan
    tomorrow = date.today() + timedelta(days=1)

    class Backend(Model):
        def plan_week(self, system, prompt, schema=None):
            return WeekPlan()

    class Calendar(Cal):
        def list_events(self, start, end):
            return [e for e in self.events if start <= e.start < end]

        def create_event(self, category, title, start, end, task_id=None, suggested=False):
            self.events.append(Event(id=f"c{start:%H%M}{title}", calendar=category, title=title, start=start, end=end,
                                     managed=True, suggested=suggested))
            return self.events[-1].id

        def delete_event(self, event_id):
            self.events = [e for e in self.events if e.id != event_id]

    cal = Calendar([])
    monkeypatch.setattr(cli, "_load_config", lambda: (None, {"categories": {c: {} for c in CATS}, "llm": {},
                                                             "notes": "Lubię czytać."}))
    storage, r = Storage(":memory:"), open_rules(note_rules=[], min_free_minutes=1000)

    def replan():
        backend = Backend(f("18:00", "19:00", day=tomorrow), f("19:15", "20:15", "Spacer", day=tomorrow))
        monkeypatch.setattr("dayoptimizer.llm.backend.planning_backends", lambda cfg: [backend])
        changes, *_ = cli._llm_plan([tomorrow], cal, storage, r, confirm=lambda c: True)
        return [(c.kind, c.title, c.new_start and f"{c.new_start:%H:%M}") for c in changes
                if c.kind == "delete" or c.new_start.hour >= 18], backend.calls

    assert replan()[0][-4:] == [("create", "Czytanie (sugestia)", "18:00"), ("create", "Spacer (sugestia)", "19:15"),
                                ("delete", "coś relaksującego", None), ("create", "coś relaksującego", "20:15")]
    assert replan() == ([], 0)  # nothing changed: nothing changes, no model asked
    cal.events.append(ev("u1", "Food", "Kolacja", tomorrow, "19:45", "20:30"))
    assert sorted(replan()[0]) == [("create", "coś relaksującego", "20:30"), ("delete", "Spacer (sugestia)", None),
                                   ("delete", "coś relaksującego", None)]
