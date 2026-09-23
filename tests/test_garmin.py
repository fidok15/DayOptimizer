import pytest
import stat
from unittest.mock import MagicMock, patch
from dayoptimizer.core import garmin as garmin_mod
from dayoptimizer.core.garmin import build_summary, summarize
from dayoptimizer.core.garmin import (GarminClient, GarminNotConfigured,
                                      garmin_configured)
from dayoptimizer.core.models import GarminSummary

SLEEP = {"dailySleepDTO": {"sleepTimeSeconds": 23400, "sleepScores": {"overall": {"value": 71}}}}
BATTERY = [{"charged": 62}]
STRESS = {"avgStressLevel": 31}
HRV = {"hrvSummary": {"status": "BALANCED"}}

def test_build_summary_parses_api_shapes():
    s = build_summary("2026-07-03", SLEEP, BATTERY, STRESS, HRV, rhr=52)
    assert s.sleep_seconds == 23400
    assert s.sleep_score == 71
    assert s.body_battery_start == 62
    assert s.stress_avg == 31
    assert s.hrv_status == "BALANCED"
    assert s.resting_hr == 52

def test_build_summary_tolerates_missing_data():
    s = build_summary("2026-07-03", None, None, None, None, rhr=None)
    assert s.sleep_seconds is None and s.sleep_score is None

def test_summarize_is_compact():
    s = GarminSummary(date="2026-07-03", sleep_seconds=23400, sleep_score=71,
                      body_battery_start=62, hrv_status="BALANCED", stress_avg=31, resting_hr=52)
    text = summarize(s)
    assert "sleep 6h30m" in text and "score 71" in text and "BB 62" in text
    assert "HRV BALANCED" in text and "stress 31" in text and "RHR 52" in text
    assert len(text) < 200

def test_summarize_no_data():
    s = GarminSummary(date="2026-07-03")
    assert summarize(s) == "[2026-07-03] no data"


def test_garmin_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    assert garmin_configured() is False
    (tmp_path / "garmin").mkdir(parents=True)
    assert garmin_configured() is False          # empty dir = not configured
    (tmp_path / "garmin" / "oauth1_token.json").write_text("{}")
    assert garmin_configured() is True


def test_client_raises_not_configured_without_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    try:
        GarminClient()
        assert False, "expected GarminNotConfigured"
    except GarminNotConfigured as exc:
        assert "dayoptimizer garmin login" in str(exc)


class _FakeClient:
    def dump(self, path):
        from pathlib import Path
        (Path(path) / "oauth.json").write_text("{}")


class _FakeGarmin:
    """Stands in for garminconnect.Garmin: MFA on demand, never touches the network."""
    mfa = False
    fail = None

    def __init__(self, email=None, password=None, return_on_mfa=False, **_):
        self.client = _FakeClient()

    def login(self, tokenstore=None):
        if _FakeGarmin.fail:
            raise _FakeGarmin.fail
        return ("needs_mfa", None) if _FakeGarmin.mfa else (None, None)

    def resume_login(self, state, code):
        if code != "123456":
            import garminconnect
            raise garminconnect.GarminConnectAuthenticationError("bad code")


@pytest.fixture
def fake_garmin(monkeypatch):
    import garminconnect
    monkeypatch.setattr(garminconnect, "Garmin", _FakeGarmin)
    _FakeGarmin.mfa, _FakeGarmin.fail = False, None
    return _FakeGarmin


def test_two_step_login_saves_only_private_tokens(fake_garmin):
    import stat
    from dayoptimizer.core.garmin import (garmin_configured, garmin_disconnect,
                                          garmin_finish_mfa, garmin_start_login)
    from dayoptimizer.paths import garmin_token_dir
    fake_garmin.mfa = True
    needs_mfa, api = garmin_start_login("a@b.c", "secret-pw")
    assert needs_mfa and not garmin_configured()
    garmin_finish_mfa(api, "123456")
    assert garmin_configured()
    token_dir = garmin_token_dir()
    assert stat.S_IMODE(token_dir.stat().st_mode) == 0o700
    for f in token_dir.iterdir():
        assert stat.S_IMODE(f.stat().st_mode) == 0o600 and "secret-pw" not in f.read_text()
    garmin_disconnect()
    assert not garmin_configured()


def test_login_errors_have_codes(fake_garmin):
    import garminconnect
    from dayoptimizer.core.garmin import GarminLoginError, garmin_finish_mfa, garmin_start_login
    fake_garmin.fail = garminconnect.GarminConnectAuthenticationError("401 for a@b.c")
    with pytest.raises(GarminLoginError) as e:
        garmin_start_login("a@b.c", "pw")
    assert e.value.code == "auth" and e.value.__cause__ is None
    fake_garmin.fail = garminconnect.GarminConnectTooManyRequestsError("429")
    with pytest.raises(GarminLoginError, match="limiting"):
        garmin_start_login("a@b.c", "pw")
    fake_garmin.fail, fake_garmin.mfa = None, True
    _, api = garmin_start_login("a@b.c", "pw")
    with pytest.raises(GarminLoginError) as e:
        garmin_finish_mfa(api, "000000")
    assert e.value.code == "mfa"
