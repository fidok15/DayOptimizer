from __future__ import annotations
import os
from pathlib import Path
from dayoptimizer.core.models import GarminSummary

def build_summary(date, sleep_data, battery_data, stress_data, hrv_data, rhr) -> GarminSummary:
    sleep_seconds = sleep_score = battery = stress = hrv_status = None
    if sleep_data:
        dto = sleep_data.get("dailySleepDTO") or {}
        sleep_seconds = dto.get("sleepTimeSeconds")
        sleep_score = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
    if battery_data:
        battery = battery_data[0].get("charged")
    if stress_data:
        stress = stress_data.get("avgStressLevel")
    if hrv_data:
        hrv_status = (hrv_data.get("hrvSummary") or {}).get("status")
    return GarminSummary(date=date, sleep_seconds=sleep_seconds, sleep_score=sleep_score,
                         body_battery_start=battery, hrv_status=hrv_status,
                         stress_avg=stress, resting_hr=rhr)

def summarize(s: GarminSummary) -> str:
    parts = []
    if s.sleep_seconds is not None:
        h, m = divmod(s.sleep_seconds // 60, 60)
        parts.append(f"sleep {h}h{m:02d}m")
    if s.sleep_score is not None:
        parts.append(f"score {s.sleep_score}")
    if s.body_battery_start is not None:
        parts.append(f"BB {s.body_battery_start}")
    if s.hrv_status:
        parts.append(f"HRV {s.hrv_status}")
    if s.stress_avg is not None:
        parts.append(f"stress {s.stress_avg}")
    if s.resting_hr is not None:
        parts.append(f"RHR {s.resting_hr}")
    return f"[{s.date}] " + ", ".join(parts) if parts else f"[{s.date}] no data"

class GarminNotConfigured(RuntimeError):
    pass


def _chmod_tokens(token_dir: Path) -> None:
    os.chmod(token_dir, 0o700)
    for f in token_dir.iterdir():
        if f.is_file():
            os.chmod(f, 0o600)


def garmin_login(email: str, password: str, token_dir: str | Path | None = None) -> str:
    """First-time login: authenticate with Garmin and persist ONLY the OAuth
    tokens. The password is used for this call and never stored."""
    from garminconnect import Garmin
    from dayoptimizer.paths import ensure_private_dir, garmin_token_dir
    token_dir = Path(token_dir) if token_dir else garmin_token_dir()
    ensure_private_dir()
    api = Garmin(email=email, password=password)
    api.login(str(token_dir))
    _chmod_tokens(token_dir)
    return f"Logged in to Garmin Connect. Tokens saved to {token_dir} (password not stored)."


def garmin_configured(token_dir: str | Path | None = None) -> bool:
    from dayoptimizer.paths import garmin_token_dir
    token_dir = Path(token_dir) if token_dir else garmin_token_dir()
    return token_dir.is_dir() and any(token_dir.iterdir())


class GarminClient:
    """Token-only wrapper over garminconnect: resumes a session persisted by
    `garmin_login`. Never sees the password."""

    def __init__(self, token_dir: str | Path | None = None):
        from garminconnect import Garmin
        from dayoptimizer.paths import garmin_token_dir
        token_dir = Path(token_dir) if token_dir else garmin_token_dir()
        if not garmin_configured(token_dir):
            raise GarminNotConfigured(
                "Garmin is not configured — run 'dayoptimizer garmin login'")
        self._api = Garmin()
        try:
            self._api.login(str(token_dir))
        except Exception as exc:
            raise GarminNotConfigured(
                "Garmin session expired — run 'dayoptimizer garmin login'") from exc

    def fetch_summary(self, date: str) -> GarminSummary:
        def _try(fn, *args):
            try:
                return fn(*args)
            except Exception:
                return None
        sleep = _try(self._api.get_sleep_data, date)
        battery = _try(self._api.get_body_battery, date)
        stress = _try(self._api.get_stress_data, date)
        hrv = _try(self._api.get_hrv_data, date)
        rhr_data = _try(self._api.get_rhr_day, date)
        rhr = None
        if rhr_data:
            try:
                metrics = rhr_data["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
                rhr = metrics[0]["value"]
            except (KeyError, IndexError, TypeError):
                rhr = None
        return build_summary(date, sleep, battery, stress, hrv, rhr)
