import http.client
import json
import threading
import pytest
import yaml
from dayoptimizer import paths
from dayoptimizer.core.rules import load_rules
from dayoptimizer.onboarding import ConfigError
from dayoptimizer.web import DEFAULT_CONFIG, make_server, read_state, write_state

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


def _request(port, method, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    data = json.dumps(body).encode() if body is not None else None
    conn.request(method, "/api/state", body=data, headers=headers or {})
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
