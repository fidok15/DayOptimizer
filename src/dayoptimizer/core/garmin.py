from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime, timedelta
from dayoptimizer.core.models import Activity, GarminSummary

def build_summary(date, sleep_data, battery_data, stress_data, hrv_data, rhr,
                  readiness=None) -> GarminSummary:
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
    if isinstance(readiness, list):
        readiness = readiness[0] if readiness else None
    readiness = readiness or {}
    return GarminSummary(date=date, sleep_seconds=sleep_seconds, sleep_score=sleep_score,
                         body_battery_start=battery, hrv_status=hrv_status,
                         stress_avg=stress, resting_hr=rhr,
                         recovery_minutes=readiness.get("recoveryTime"),
                         recovery_measured_at=readiness.get("timestampLocal"),
                         readiness_score=readiness.get("score"),
                         readiness_level=readiness.get("level"))

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


class GarminLoginError(RuntimeError):
    """Login failure with a stable reason code: auth, mfa, rate, offline, failed."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _login_error(exc: Exception, during_mfa: bool = False) -> GarminLoginError:
    import garminconnect as gc
    if isinstance(exc, gc.GarminConnectTooManyRequestsError):
        return GarminLoginError("rate", "Garmin is limiting sign-in attempts. Wait a few minutes and try again.")
    if isinstance(exc, gc.GarminConnectAuthenticationError):
        if during_mfa:
            return GarminLoginError("mfa", "That code didn't work. Check the newest code and try again.")
        return GarminLoginError("auth", "Garmin didn't accept that email and password.")
    if isinstance(exc, (gc.GarminConnectConnectionError, OSError)):
        return GarminLoginError("offline", "Couldn't reach Garmin. Check your internet connection and try again.")
    return GarminLoginError("failed", "Garmin sign-in failed. Try again in a moment.")


def _save_tokens(api, token_dir: Path) -> None:
    token_dir.mkdir(parents=True, exist_ok=True)
    api.client.dump(str(token_dir))
    _chmod_tokens(token_dir)


def garmin_start_login(email: str, password: str, token_dir: str | Path | None = None):
    """Two-step login for UIs. Returns (needs_mfa, api). Without MFA the tokens
    are saved right away; with MFA pass `api` to `garmin_finish_mfa`. The
    password lives only for this call."""
    from garminconnect import Garmin
    from dayoptimizer.paths import ensure_private_dir, garmin_token_dir
    ensure_private_dir()
    api = Garmin(email=email, password=password, return_on_mfa=True)
    try:
        status, _ = api.login()
    except Exception as exc:
        raise _login_error(exc) from None  # from None: keep credentials out of chained tracebacks
    if status == "needs_mfa":
        return True, api
    _save_tokens(api, Path(token_dir) if token_dir else garmin_token_dir())
    return False, api


def garmin_finish_mfa(api, code: str, token_dir: str | Path | None = None) -> None:
    from dayoptimizer.paths import garmin_token_dir
    try:
        api.resume_login(None, code)
    except Exception as exc:
        raise _login_error(exc, during_mfa=True) from None
    _save_tokens(api, Path(token_dir) if token_dir else garmin_token_dir())


def garmin_disconnect(token_dir: str | Path | None = None) -> None:
    """Forget the Garmin session: delete the stored tokens."""
    import shutil
    from dayoptimizer.paths import garmin_token_dir
    shutil.rmtree(Path(token_dir) if token_dir else garmin_token_dir(), ignore_errors=True)


def garmin_configured(token_dir: str | Path | None = None) -> bool:
    from dayoptimizer.paths import garmin_token_dir
    token_dir = Path(token_dir) if token_dir else garmin_token_dir()
    return token_dir.is_dir() and any(token_dir.iterdir())


class GarminClient:
    """Token-only wrapper over garminconnect: resumes a session persisted by
    `garmin_start_login`. Never sees the password."""

    def __init__(self, token_dir: str | Path | None = None):
        from garminconnect import Garmin
        from dayoptimizer.paths import garmin_token_dir
        token_dir = Path(token_dir) if token_dir else garmin_token_dir()
        if not garmin_configured(token_dir):
            raise GarminNotConfigured(
                "Garmin is not connected — connect it in the web planner (dayoptimizer web) or run 'dayoptimizer garmin login'")
        self._api = Garmin()
        try:
            self._api.login(str(token_dir))
        except Exception as exc:
            raise GarminNotConfigured(
                "Garmin session expired — reconnect in the web planner or run 'dayoptimizer garmin login'") from exc

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
        readiness = _try(self._api.get_training_readiness, date)
        rhr_data = _try(self._api.get_rhr_day, date)
        rhr = None
        if rhr_data:
            try:
                metrics = rhr_data["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
                rhr = metrics[0]["value"]
            except (KeyError, IndexError, TypeError):
                rhr = None
        return build_summary(date, sleep, battery, stress, hrv, rhr, readiness)

    def activities(self, start: str, end: str) -> list[Activity]:
        """Recorded workouts between two ISO dates (inclusive)."""
        out = []
        for a in self._api.get_activities_by_date(start, end) or []:
            try:
                begin = datetime.fromisoformat(a["startTimeLocal"]).astimezone()
                seconds = float(a.get("duration") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            out.append(Activity(
                id=str(a.get("activityId")),
                type_key=str((a.get("activityType") or {}).get("typeKey") or "other"),
                name=str(a.get("activityName") or ""),
                start=begin, end=begin + timedelta(seconds=seconds),
                aerobic_te=float(a.get("aerobicTrainingEffect") or 0),
                anaerobic_te=float(a.get("anaerobicTrainingEffect") or 0)))
        return sorted(out, key=lambda x: x.start)
