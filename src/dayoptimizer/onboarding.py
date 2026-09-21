"""Validated user-config writer. The Claude Code onboarding command builds a
YAML proposal in conversation; this module is the only path that persists it."""
from __future__ import annotations
import os
from typing import Annotated, Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_VALID_WORK_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ConfigError(ValueError):
    pass


class CategoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    movable: bool
    priority: int = Field(default=5, ge=0, le=10)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class TemplateBlock(BaseModel):
    """One block of the user's typical week (entered in the web planner)."""
    model_config = ConfigDict(extra="forbid")
    start: str = Field(pattern=_HHMM)
    end: str = Field(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")
    category: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=60)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value, info):
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError(f"end ({value}) must be after start ({start})")
        return value


class MealWindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    duration_minutes: int = Field(ge=5, le=240)


class DayRulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gym_per_week: int | None = Field(default=None, ge=0, le=14)
    gym_duration_minutes: int | None = Field(default=None, ge=10, le=300)
    min_free_minutes: int | None = Field(default=None, ge=0, le=720)
    deep_work_minutes: int | None = Field(default=None, ge=15, le=300)
    deep_work_blocks_per_day: int | None = Field(default=None, ge=0, le=8)
    buffer_minutes: int | None = Field(default=None, ge=0, le=120)
    wind_down_minutes: int | None = Field(default=None, ge=0, le=180)
    sleep_target_hours: float | None = Field(default=None, ge=4, le=12)
    morning_buffer_minutes: int | None = Field(default=None, ge=0, le=240)
    free_time_activity: str | None = Field(default=None, max_length=60)
    day_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    meal_windows: list[MealWindowConfig] | None = None
    work_days: list[str] | None = Field(default=None, max_length=7)

    @field_validator("work_days")
    @classmethod
    def _check_work_days(cls, value):
        if value is None:
            return value
        for name in value:
            if not isinstance(name, str) or name.lower() not in _VALID_WORK_DAYS:
                raise ValueError(
                    f"invalid work_days entry {name!r} — valid values are "
                    f"{', '.join(_VALID_WORK_DAYS)}")
        return value


class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # null removes a default category from the merged config
    categories: dict[str, CategoryConfig | None] = {}
    day_rules: DayRulesConfig = DayRulesConfig()
    transport_routes: dict[str, Annotated[int, Field(ge=0, le=600)]] = {}
    holiday_calendars: list[Annotated[str, Field(min_length=1, max_length=60)]] | None = Field(
        default=None, max_length=10)
    typical_week: dict[Weekday, Annotated[list[TemplateBlock], Field(max_length=48)]] | None = None

    @field_validator("holiday_calendars")
    @classmethod
    def _check_holiday_calendars(cls, value):
        if value is None:
            return value
        for name in value:
            if not name.isprintable():
                raise ValueError(
                    f"invalid holiday_calendars entry {name!r} (1-60 printable characters)")
        return value


def validate_config(yaml_text: str) -> UserConfig:
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Config must be a YAML mapping (top-level keys: "
                          "categories, day_rules, transport_routes, "
                          "holiday_calendars, typical_week).")
    problems: list[str] = []
    categories = data.get("categories")
    non_string_names: list[object] = []
    if isinstance(categories, dict):
        for name in categories:
            if not isinstance(name, str):
                problems.append(
                    f"Invalid category name: {name!r} (1-40 printable characters).")
                non_string_names.append(name)
            elif not (1 <= len(name) <= 40) or not name.isprintable():
                problems.append(
                    f"Invalid category name: {name!r} (1-40 printable characters).")
    if non_string_names:
        # Validate the rest on a copy; never mutate the caller's data.
        data = {**data, "categories": {
            k: v for k, v in categories.items() if k not in non_string_names}}
    result: UserConfig | None = None
    try:
        result = UserConfig.model_validate(data)
    except ValidationError as exc:
        problems.extend(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    if result is not None:
        day_start, day_end = result.day_rules.day_start, result.day_rules.day_end
        if day_start is not None and day_end is not None and day_start >= day_end:
            problems.append(
                f"day_rules: day_start ({day_start}) must be before day_end ({day_end}).")
    if problems:
        raise ConfigError("Invalid config: " + "; ".join(problems))
    assert result is not None
    return result


def save_user_config(yaml_text: str) -> str:
    """Validate and write the user's config.local.yaml (0600). Always writes
    to paths.user_config_path() — callers cannot redirect the write."""
    from dayoptimizer.paths import ensure_private_dir, user_config_path
    validate_config(yaml_text)
    ensure_private_dir()
    target = user_config_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(yaml_text)
    os.chmod(tmp, 0o600)
    tmp.replace(target)
    return f"Saved config to {target}. Background 'dayoptimizer check' runs pick it up automatically."
