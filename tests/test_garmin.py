import stat
from unittest.mock import MagicMock, patch
from dayoptimizer.core import garmin as garmin_mod
from dayoptimizer.core.garmin import build_summary, summarize
from dayoptimizer.core.garmin import (GarminClient, GarminNotConfigured,
                                      garmin_configured, garmin_login)
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


def test_garmin_login_persists_tokens_only_with_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYOPTIMIZER_HOME", str(tmp_path))
    fake_api = MagicMock()

    def fake_login(token_dir):
        (tmp_path / "garmin").mkdir(parents=True, exist_ok=True)
        (tmp_path / "garmin" / "oauth1_token.json").write_text("{}")

    fake_api.login.side_effect = fake_login
    with patch("garminconnect.Garmin", return_value=fake_api) as ctor:
        msg = garmin_login("user@example.com", "secret")
    ctor.assert_called_once_with(email="user@example.com", password="secret")
    token_file = tmp_path / "garmin" / "oauth1_token.json"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "garmin").stat().st_mode) == 0o700
    assert "secret" not in msg


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
