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


def _state_payload(**overrides):
    state = read_state()
    payload = {"categories": state["categories"], "typical_week": state["typical_week"]}
    payload.update(overrides)
    return payload


def test_roundtrip_stores_only_delta_and_keeps_other_keys():
    paths.ensure_private_dir()
    paths.user_config_path().write_text("day_rules:\n  gym_per_week: 2\n")
    cats = read_state()["categories"]
    cats["Choir"] = {"movable": False, "priority": 7, "color": "#4f9d8a", "emoji": "🎵"}
    del cats["Gym"]
    state = write_state(_state_payload(categories=cats, typical_week={"mon": [BLOCK], "tue": []}))

    local = yaml.safe_load(paths.user_config_path().read_text())
    assert local["day_rules"] == {"gym_per_week": 2}
    assert local["categories"] == {"Gym": None, "Choir": {"movable": False, "priority": 7, "color": "#4f9d8a", "emoji": "🎵"}}
    assert local["typical_week"] == {"mon": [BLOCK]}
    assert "Gym" not in state["categories"] and "Choir" in state["categories"]
    rules = load_rules(DEFAULT_CONFIG)
    assert "Gym" not in rules.categories and rules.is_movable("Choir") is False


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
    assert status == 200 and "Food" in state["categories"]
    payload = {"categories": state["categories"], "typical_week": {"wed": [BLOCK]}}
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
        _ev("2026-09-27T23:30", "2026-09-28T08:00", cal="Sleep"),  # tail is next week
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
    assert status == 502 and body["code"] == "setup" and "setup-bundle.sh" in body["error"]


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
    web.serve(port=server)  # port already taken by our own planner
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
    status, state = _request(server, "GET")
    payload = {"categories": state["categories"], "typical_week": {"mon": [BLOCK]}}
    status, body = _request(server, "POST", payload, {"Content-Type": "application/json"}, "/api/routine")
    assert status == 200 and body["path"].endswith("routine.md") and "## Mon" in body["text"]
    assert read_state()["typical_week"] == {"mon": [BLOCK]}


def test_category_calendars_report(monkeypatch):
    import os
    from dayoptimizer import mcp_server, web
    assert "install.sh" in web.create_category_calendars()["error"]  # no bundle yet
    exe = paths.ensure_private_dir() / "DayOptimizer.app" / "Contents" / "MacOS" / "dayopt"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    os.chmod(exe, 0o755)
    monkeypatch.setattr(mcp_server, "_bundle_run", lambda a: "FAILED Gym: nope\nCREATED Choir\tRead\n")
    assert web.create_category_calendars() == {"created": ["Choir", "Read"], "error": "Gym: nope"}
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
    # clearing the notes drops the key instead of storing an empty string
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
            if "invented" in sentence:  # a category the user doesn't have
                return llm.CompiledNotes(not_before=[llm.TimeRule(category="Nope", time="09:00", source="x")])
            if "broken" in sentence:    # unparseable time
                return llm.CompiledNotes(not_after=[llm.TimeRule(time="oops", source="x")])
            return llm.CompiledNotes()  # a mood: no rule

    monkeypatch.setattr(llm, "make_backend", lambda cfg: FakeLLM())
    out = web.compile_notes("no lunch before 14. gym 3x a week\ninvented one; broken one. I want to feel less rushed",
                            ["Food", "Gym"])
    assert asked == ["no lunch before 14", "gym 3x a week", "invented one", "broken one",
                     "I want to feel less rushed"]
    assert out["rules"] == ["Food: not before 14:00", "Gym: at most 3 time(s) a week"]
    assert out["not_compiled"] == ["invented one", "broken one", "I want to feel less rushed"]
    stored = yaml.safe_load(paths.user_config_path().read_text())["note_rules"]
    # the source is the user's own sentence, not whatever the model echoed
    assert [(r["type"], r["source"]) for r in stored] == [("not_before", "no lunch before 14"),
                                                          ("max_per_week", "gym 3x a week")]
    # the rules reach the planner through the normal config path
    assert [r.type for r in load_rules(DEFAULT_CONFIG).note_rules] == ["not_before", "max_per_week"]
    # clearing the notes clears the rules
    assert web.compile_notes("", ["Food"]) == {"rules": [], "not_compiled": [], "error": None}
    assert "note_rules" not in yaml.safe_load(paths.user_config_path().read_text())


def test_compile_notes_without_llm_keeps_the_notes(monkeypatch):
    from dayoptimizer.llm import backend as llm
    from dayoptimizer import web
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dayoptimizer.llm.ollama_backend.ollama_running", lambda: False)
    out = web.compile_notes("no lunch before 14", ["Food"])
    assert out["rules"] == [] and "language model" in out["error"]


def test_time_rules_need_a_time_in_the_sentence():
    from dayoptimizer import web
    # a model turning "it's family time" into a whole free Sunday is invention
    assert web._clean_rule({"type": "keep_free", "source": "it's family time",
                            "start": "00:00", "end": "23:59"}, []) is None
    assert web._clean_rule({"type": "keep_free", "source": "Sundays 18:00-22:00 are family time",
                            "start": "18:00", "end": "22:00"}, []) is not None
    # counts may be spelled out ("two days in a row"), so they aren't checked for digits
    assert web._clean_rule({"type": "min_gap_days", "source": "never two days in a row",
                            "category": "Gym", "days": 2}, ["Gym"]) is not None
