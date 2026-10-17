import http.client
import json
import threading
import pytest
import yaml
from dayoptimizer import paths
from dayoptimizer.core.rules import load_rules
from dayoptimizer.onboarding import ConfigError
from datetime import date, datetime
from dayoptimizer.core.models import Event
from dayoptimizer.web import DEFAULT_CONFIG, events_to_week, make_server, read_state, write_state

BLOCK = {"start": "07:00", "end": "07:30", "category": "Food", "title": "Breakfast"}
FOOD = {"movable": True, "priority": 6, "color": "#e07b53"}


def _state_payload(**overrides):
    state = read_state()
    payload = {"categories": {"Food": FOOD, **state["categories"]}, "typical_week": state["typical_week"]}
    payload.update(overrides)
    return payload


def test_roundtrip_stores_only_delta_and_keeps_other_keys():
    paths.ensure_private_dir()
    paths.user_config_path().write_text("day_rules:\n  gym_per_week: 2\n")
    choir = {"movable": False, "priority": 7, "color": "#4f9d8a", "emoji": "🎵"}
    state = write_state(_state_payload(categories={"Food": FOOD, "Choir": choir},
                                       typical_week={"mon": [BLOCK], "tue": []}))

    local = yaml.safe_load(paths.user_config_path().read_text())
    assert local["day_rules"] == {"gym_per_week": 2}
    assert local["categories"] == {"Food": FOOD, "Choir": choir}
    assert local["typical_week"] == {"mon": [BLOCK]}
    assert set(state["categories"]) == {"Food", "Choir"}
    rules = load_rules(DEFAULT_CONFIG)
    assert set(rules.categories) == {"Food", "Choir"} and rules.is_movable("Choir") is False


@pytest.mark.parametrize("week", [
    {"mon": [{**BLOCK, "category": "Nope"}]},
    {"mon": [{**BLOCK, "end": "06:00"}]},
    {"funday": [BLOCK]},
    {"mon": [{**BLOCK, "start": "7am"}]},
])
def test_bad_week_rejected(week):
    with pytest.raises(ConfigError):
        write_state(_state_payload(typical_week=week))
    assert not paths.user_config_path().exists()


def test_end_of_day_block_allowed():
    write_state(_state_payload(typical_week={"sun": [{**BLOCK, "start": "23:00", "end": "24:00"}]}))
    assert read_state()["typical_week"]["sun"][0]["end"] == "24:00"


@pytest.fixture
def server():
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _request(port, method, body=None, headers=None, path="/api/state"):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    data = json.dumps(body).encode() if body is not None else None
    conn.request(method, path, body=data, headers=headers or {})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def test_http_get_and_put(server):
    status, state = _request(server, "GET")
    assert status == 200 and state["categories"] == {}
    payload = {"categories": {"Food": FOOD}, "typical_week": {"wed": [BLOCK]}}
    status, state = _request(server, "PUT", payload, {"Content-Type": "application/json",
                                                     "Origin": f"http://127.0.0.1:{server}"})
    assert status == 200 and state["typical_week"] == {"wed": [BLOCK]}


def test_http_rejects_cross_origin_and_foreign_host(server):
    payload = {"categories": {}, "typical_week": {}}
    json_hdr = {"Content-Type": "application/json"}
    assert _request(server, "PUT", payload, {**json_hdr, "Origin": "http://evil.example"})[0] == 403
    assert _request(server, "PUT", payload, {"Content-Type": "text/plain"})[0] == 403
    assert _request(server, "GET", headers={"Host": "evil.example"})[0] == 403
    assert _request(server, "PUT", {"categories": {}, "typical_week": {"mon": [BLOCK]}}, json_hdr)[0] == 422
    assert not paths.user_config_path().exists()


def _ev(start, end, cal="Work", title="x", all_day=False):
    at = lambda s: datetime.fromisoformat(s).astimezone()
    return Event(id=start, calendar=cal, title=title, start=at(start), end=at(end), all_day=all_day)


def test_events_to_week_splits_overnight_and_skips_all_day():
    week = events_to_week([
        _ev("2026-09-21T09:00", "2026-09-21T17:30", title="Office"),
        _ev("2026-09-22T23:00", "2026-09-23T07:00", cal="Sleep"),
        _ev("2026-09-24T00:00", "2026-09-25T00:00", cal="Holidays", all_day=True),
        _ev("2026-09-27T23:30", "2026-09-28T08:00", cal="Sleep"),
    ], date(2026, 9, 21))
    assert week["mon"] == [{"start": "09:00", "end": "17:30", "calendar": "Work", "title": "Office"}]
    assert [(b["start"], b["end"]) for b in week["tue"]] == [("23:00", "24:00")]
    assert [(b["start"], b["end"]) for b in week["wed"]] == [("00:00", "07:00")]
    assert week["thu"] == [] and [(b["start"], b["end"]) for b in week["sun"]] == [("23:30", "24:00")]


def test_http_import_rejects_bad_date(server):
    hdr = {"Content-Type": "application/json"}
    assert _request(server, "POST", {"week_start": "nope"}, hdr, "/api/import")[0] == 422
    assert _request(server, "POST", {"week_start": "2026-09-21"}, {"Content-Type": "text/plain"}, "/api/import")[0] == 403


def test_http_import_without_bundle_says_how_to_set_up(server):
    status, body = _request(server, "POST", {"week_start": "2026-09-21"},
                            {"Content-Type": "application/json"}, "/api/import")
    assert status == 502 and body["code"] == "setup" and "install.sh" in body["error"]


def test_http_garmin_mfa_flow(server, monkeypatch):
    import dayoptimizer.core.garmin as g
    calls = []
    monkeypatch.setattr(g, "garmin_start_login", lambda e, p: (True, "api"))
    monkeypatch.setattr(g, "garmin_finish_mfa", lambda api, code: calls.append((api, code)))
    hdr = {"Content-Type": "application/json"}
    post = lambda path, body: _request(server, "POST", body, hdr, path)
    assert post("/api/garmin/mfa", {"code": "123456"})[1]["code"] == "expired"
    assert post("/api/garmin/login", {"email": "nope", "password": "pw"})[0] == 422
    assert post("/api/garmin/login", {"email": "a@b.c", "password": "pw"}) == (200, {"status": "mfa"})
    assert post("/api/garmin/mfa", {"code": "12a"})[0] == 422
    assert post("/api/garmin/mfa", {"code": "123456"}) == (200, {"status": "connected"})
    assert calls == [("api", "123456")]
    assert _request(server, "GET", path="/api/garmin") == (200, {"connected": False})


def test_http_garmin_bad_password_never_echoed(server, monkeypatch):
    import dayoptimizer.core.garmin as g
    def fail(e, p):
        raise g.GarminLoginError("auth", "Garmin didn't accept that email and password.")
    monkeypatch.setattr(g, "garmin_start_login", fail)
    status, body = _request(server, "POST", {"email": "a@b.c", "password": "hunter2"},
                            {"Content-Type": "application/json"}, "/api/garmin/login")
    assert status == 502 and body["code"] == "auth" and "hunter2" not in json.dumps(body)
    assert _request(server, "POST", {"email": "a@b.c", "password": "x"},
                    {"Content-Type": "application/json", "Origin": "http://evil.example"},
                    "/api/garmin/login")[0] == 403


def test_serve_reuses_running_planner(server, monkeypatch, capsys):
    from dayoptimizer import web
    opened = []
    monkeypatch.setattr(web.webbrowser, "open", opened.append)
    web.serve(port=server)
    assert opened == [f"http://127.0.0.1:{server}/"] and "already running" in capsys.readouterr().out


def test_serve_refuses_foreign_port():
    import socket
    from dayoptimizer import web
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        with pytest.raises(SystemExit, match="another program"):
            web.serve(port=s.getsockname()[1], open_browser=False)


def test_http_save_routine_writes_state_and_brief(server):
    payload = {"categories": {"Food": FOOD}, "typical_week": {"mon": [BLOCK]}}
    status, body = _request(server, "POST", payload, {"Content-Type": "application/json"}, "/api/routine")
    assert status == 200 and body["path"].endswith("routine.md") and "## Mon" in body["text"]
    assert read_state()["typical_week"] == {"mon": [BLOCK]}


def test_category_calendars_report(monkeypatch):
    import os
    from dayoptimizer import mcp_server, web
    assert "install.sh" in web.create_category_calendars()["error"]
    exe = paths.ensure_private_dir() / "DayOptimizer.app" / "Contents" / "MacOS" / "dayopt"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    os.chmod(exe, 0o755)
    monkeypatch.setattr(mcp_server, "_bundle_run", lambda a: "FAILED Gym: nope\nCOLOR Choir\t#4f9d8a\n"
                        "COLOR Work\t#c2c2c2\nCREATED Choir\tRead\nRECOLORED Work\n")
    assert web.create_category_calendars() == {"created": ["Choir", "Read"], "recolored": ["Work"],
                                               "colors": {"Choir": "#4f9d8a", "Work": "#c2c2c2"},
                                               "all": [], "error": "Gym: nope"}
    assert web.calendar_colors() == {"colors": {"Choir": "#4f9d8a", "Work": "#c2c2c2"}, "calendars": {}}
    monkeypatch.setattr(mcp_server, "_bundle_run", lambda a: "COLOR Work\t#c2c2c2\nCAL Work\t#c2c2c2\tiCloud\n"
                        "CAL School\t#3fa7d6\tme@gmail.com\n")
    assert web.calendar_colors()["calendars"] == {"Work": "#c2c2c2", "School": "#3fa7d6"}
    monkeypatch.setattr(mcp_server, "_bundle_run", lambda a: "NO_ACCESS\n")
    assert "blocked" in web.create_category_calendars()["error"]


def test_notes_roundtrip_and_validation(server):
    hdr = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server}"}
    state = _request(server, "GET")[1]
    assert state["notes"] == ""
    payload = {"categories": state["categories"], "typical_week": {}, "notes": "  no food before 11  "}
    assert _request(server, "PUT", payload, hdr)[1]["notes"] == "no food before 11"
    assert yaml.safe_load(paths.user_config_path().read_text())["notes"] == "no food before 11"
    assert _request(server, "PUT", {**payload, "notes": "x" * 2001}, hdr)[0] == 422
    assert _request(server, "PUT", {**payload, "notes": 5}, hdr)[0] == 422
    assert _request(server, "PUT", {**payload, "notes": "   "}, hdr)[1]["notes"] == ""
    assert "notes" not in yaml.safe_load(paths.user_config_path().read_text())


def test_compile_notes_asks_per_sentence_and_stores_only_enforceable_rules(monkeypatch):
    from dayoptimizer.llm import backend as llm
    from dayoptimizer import web

    asked = []

    class FakeLLM:
        """Answers one sentence at a time, the way the compiler asks."""
        def compile_notes(self, sentence, categories):
            asked.append(sentence)
            if "lunch" in sentence:
                return llm.CompiledNotes(not_before=[llm.TimeRule(category="Food", time="14:00", source="echoed wrong")])
            if "gym" in sentence:
                return llm.CompiledNotes(max_per_week=[llm.WeekRule(category="Gym", count=3, source="x")])
            if "invented" in sentence:
                return llm.CompiledNotes(not_before=[llm.TimeRule(category="Nope", time="09:00", source="x")])
            if "broken" in sentence:
                return llm.CompiledNotes(not_after=[llm.TimeRule(time="oops", source="x")])
            if "family" in sentence:
                return llm.CompiledNotes(keep_free=[llm.FreeRule(start="12:00", end="18:00", weekday="sun", source="x")])
            return llm.CompiledNotes()

    monkeypatch.setattr(llm, "planning_backends", lambda cfg: [FakeLLM()])
    out = web.compile_notes("no lunch before 14. gym 3x a week\ninvented one; broken one. I want to feel less rushed. "
                            "Sunday 12:00-18:00 is family time, plan nothing", ["Food", "Gym"])
    assert asked == ["no lunch before 14", "gym 3x a week", "invented one", "broken one",
                     "I want to feel less rushed", "Sunday 12:00-18:00 is family time", "plan nothing",
                     "invented one. broken one", "broken one. I want to feel less rushed"]
    assert out["rules"] == ["Food: not before 14:00", "Gym: at most 3 time(s) a week",
                            "Sun 12:00-18:00: kept free"]
    assert out["not_compiled"] == ["invented one", "broken one", "I want to feel less rushed"]
    stored = yaml.safe_load(paths.user_config_path().read_text())["note_rules"]
    assert [(r["type"], r["source"]) for r in stored] == [("not_before", "no lunch before 14"),
                                                          ("max_per_week", "gym 3x a week"),
                                                          ("keep_free", "Sunday 12:00-18:00 is family time")]
    assert [r.type for r in load_rules(DEFAULT_CONFIG).note_rules] == ["not_before", "max_per_week", "keep_free"]
    assert web.compile_notes("", ["Food"]) == {"rules": [], "not_compiled": [], "error": None}
    assert "note_rules" not in yaml.safe_load(paths.user_config_path().read_text())


def test_compile_notes_without_llm_keeps_the_notes(monkeypatch):
    from dayoptimizer.llm import backend as llm
    from dayoptimizer import web
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dayoptimizer.llm.ollama_backend.ollama_running", lambda: False)
    monkeypatch.setattr("dayoptimizer.llm.ollama_backend.ollama_binary", lambda: None)
    out = web.compile_notes("no lunch before 14", ["Food"])
    assert out["rules"] == [] and "language model" in out["error"]


def test_time_rules_need_a_time_in_the_sentence():
    from dayoptimizer import web
    assert web._clean_rule({"type": "keep_free", "source": "it's family time",
                            "start": "00:00", "end": "23:59"}, []) is None
    assert web._clean_rule({"type": "keep_free", "source": "Sundays 18:00-22:00 are family time",
                            "start": "18:00", "end": "22:00"}, []) is not None
    assert web._clean_rule({"type": "min_gap_days", "source": "never two days in a row",
                            "category": "Gym", "days": 2}, ["Gym"]) is not None


def test_gap_rules_count_rest_days():
    from dayoptimizer import web
    from dayoptimizer.llm import backend as llm
    rows = llm.CompiledNotes(min_gap_days=[llm.GapRule(category="Gym", rest_days=1, source="x")]).rows()
    assert rows[0]["days"] == 2 and "rest_days" not in rows[0]
    assert web._clean_rule({"type": "min_gap_days", "source": "x", "category": "Gym", "days": 1}, ["Gym"]) is None


def test_import_lists_every_calendar_with_colour(monkeypatch):
    import os
    from dayoptimizer import mcp_server, web
    exe = paths.ensure_private_dir() / "DayOptimizer.app" / "Contents" / "MacOS" / "dayopt"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    os.chmod(exe, 0o755)
    monkeypatch.setattr(mcp_server, "_bundle_run",
                        lambda a: "SYNCED 0\nCAL Reminder\t#ff2968\tiCloud\nCAL Birthdays\t\t\n"
                                  "CAL Uni\t#4285f4\tjan@gmail.com\n")
    out = web.import_week({"week_start": "2026-09-21"})
    assert out["calendars"] == {"Reminder": "#ff2968", "Birthdays": "", "Uni": "#4285f4"}
    assert out["google"] == ["Uni"]
    assert out["typical_week"]["mon"] == []


ICS = """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:📚 Uni
X-APPLE-CALENDAR-COLOR:#1BADF8FF
BEGIN:VEVENT
UID:a
SUMMARY:Lecture
DTSTART:20260901T100000
DTEND:20260901T113000
RRULE:FREQ=WEEKLY
END:VEVENT
BEGIN:VEVENT
UID:c
SUMMARY:Called off
STATUS:CANCELLED
DTSTART:20260922T080000
DTEND:20260922T090000
END:VEVENT
BEGIN:VEVENT
UID:b
SUMMARY:Holiday
DTSTART;VALUE=DATE:20260924
DTEND;VALUE=DATE:20260925
END:VEVENT
END:VCALENDAR
"""


def test_import_file_expands_repeats_and_reads_calendar_name(server):
    from dayoptimizer import web
    out = web.import_file({"week_start": "2026-09-21", "files": [ICS]})
    assert out["calendars"] == {"Uni": "#1badf8"}
    assert out["span"] == ["2026-09-01", "2026-09-24"]
    assert out["typical_week"]["tue"] == [{"start": "10:00", "end": "11:30", "calendar": "Uni", "title": "Lecture"}]
    assert sum(map(len, out["typical_week"].values())) == 1
    assert out["all_day"] == [{"calendar": "Uni", "title": "Holiday", "days": ["thu"]}]
    hdr = {"Content-Type": "application/json"}
    assert _request(server, "POST", {"week_start": "2026-09-21", "files": ["nope"]}, hdr, "/api/import-file")[0] == 422
    assert _request(server, "POST", {"week_start": "2026-09-21", "files": []}, hdr, "/api/import-file")[0] == 422


def test_import_file_splits_by_event_categories():
    from dayoptimizer import web
    ics = ICS.replace("SUMMARY:Lecture", "SUMMARY:Lecture\nCATEGORIES:Study,Uni")
    out = web.import_file({"week_start": "2026-09-21", "files": [ics]})
    assert out["typical_week"]["tue"][0]["calendar"] == "Study"
    assert out["calendars"] == {"Study": ""}


def test_routine_mode_roundtrip_and_validation():
    assert read_state()["routine_mode"] is None
    assert write_state(_state_payload(routine_mode="day"))["routine_mode"] == "day"
    assert write_state(_state_payload())["routine_mode"] == "day"
    with pytest.raises(ConfigError):
        write_state(_state_payload(routine_mode="month"))


def test_free_time_settings_roundtrip_and_validation():
    assert (read_state()["min_free_minutes"], read_state()["variety"]) == (None, None)
    state = write_state(_state_payload(min_free_minutes=90, variety="low"))
    assert (state["min_free_minutes"], state["variety"]) == (90, "low")
    assert write_state(_state_payload())["variety"] == "low"  # not sent: kept
    with pytest.raises(ConfigError):
        write_state(_state_payload(variety="lots"))


def test_a_rule_told_over_two_sentences_compiles_from_both(monkeypatch):
    from dayoptimizer.llm import backend as llm
    from dayoptimizer import web

    class FakeLLM:
        def compile_notes(self, sentence, categories):
            if '"Lecture -"' in sentence and "skip" in sentence:
                return llm.CompiledNotes(skippable=[llm.SkipRule(category="Uni", prefix="Lecture -", source="x")])
            return llm.CompiledNotes()

    monkeypatch.setattr(llm, "planning_backends", lambda cfg: [FakeLLM()])
    out = web.compile_notes('Lectures are Uni events starting with "Lecture -". You may skip lectures.', ["Uni"])
    assert out["rules"] == ['Uni: events starting with "Lecture -" may be planned over']
    assert out["not_compiled"] == []


def test_notes_may_name_a_calendar_that_is_not_a_category(monkeypatch):
    from dayoptimizer import web
    seen = {}
    monkeypatch.setattr(web, "create_category_calendars", lambda: {"created": [], "all": ["School", "Work"]})
    monkeypatch.setattr(web, "compile_notes", lambda notes, cats: seen.setdefault("cats", cats) and {})
    monkeypatch.setattr("dayoptimizer.routine.save_routine", lambda text: "/tmp/x")
    out = web.save_routine_brief(_state_payload(notes='School "Lecture -" events can be skipped'))
    assert "School" in seen["cats"] and "all" not in out["calendars"]
