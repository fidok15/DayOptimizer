from datetime import date
import pytest
from dayoptimizer import cli
from dayoptimizer.llm.backend import DayRequest, NewEvent


@pytest.fixture
def routed(monkeypatch):
    """Record where main() sends a command instead of running it."""
    calls = []
    monkeypatch.setattr(cli, "_in_bundle", lambda: False)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "_calendar_run", lambda argv: calls.append(("bundle", argv)) or "")
    monkeypatch.setattr(cli, "cmd_web", lambda *a: calls.append(("setup",)))
    return calls


def test_bare_command_optimizes_today_via_bundle(routed, monkeypatch):
    monkeypatch.setattr(cli, "_first_run", lambda: False)
    cli.main([])
    assert routed == [("bundle", ["plan"])]


def test_first_run_opens_setup(routed, monkeypatch):
    monkeypatch.setattr(cli, "_first_run", lambda: True)
    cli.main([])
    assert routed == [("setup",)]


def test_plain_words_become_a_request(routed):
    cli.main(["meeting", "at 14:00,", "then gym"])
    assert routed == [("bundle", ["ask", "meeting at 14:00, then gym"])]


def test_setup_runs_in_terminal(routed):
    cli.main(["setup"])
    assert routed == [("setup",)]


def test_events_to_create_validates_llm_output():
    req = DayRequest(date="2026-09-22", events=[
        NewEvent(title="Spotkanie", category="Meeting", date="2026-09-22", start_time="14:00", duration_minutes=60),
        NewEvent(title="Siłownia", category="Gym", date="2026-09-22", start_time="15:00"),
        NewEvent(title="Coś", category="Nope", date="2026-09-22", start_time="16:00"),
        NewEvent(title="Kiedyś", category="Gym", date="2026-09-22"),
        NewEvent(title="Maraton", category="Gym", date="2026-09-22", start_time="06:00", duration_minutes=10_000),
    ])
    ok, problems = cli.events_to_create(req, {"Meeting": None, "Gym": None})
    assert [(c, t, s.hour, (e - s).seconds // 60) for c, t, s, e in ok] == [
        ("Meeting", "Spotkanie", 14, 60), ("Gym", "Siłownia", 15, 60), ("Gym", "Maraton", 6, 720)]
    assert ok[0][2].date() == date(2026, 9, 22)
    assert len(problems) == 2 and "Nope" in problems[0] and "no time" in problems[1]


def test_ask_adds_events_then_replans(monkeypatch, capsys):
    created, planned = [], []

    class Cal:
        def request_access(self):
            return True

        def create_event(self, category, title, start, end):
            if category == "Gym":
                raise KeyError(category)  # no Gym calendar in Apple Calendar
            created.append((category, title, f"{start:%H:%M}", f"{end:%H:%M}"))

    class LLM:
        def __init__(self, model):
            pass

        def parse_request(self, text, today, now, categories):
            assert set(categories) == {"Meeting", "Gym"}
            return DayRequest(date="2026-09-22", events=[
                NewEvent(title="Spotkanie", category="Meeting", date="2026-09-22", start_time="14:00", duration_minutes=60),
                NewEvent(title="Siłownia", category="Gym", date="2026-09-22", start_time="15:00", duration_minutes=90)])

        def summarize_changes(self, changes):
            return "summary"

    cli.paths.ensure_private_dir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(cli, "CalendarClient", Cal)
    monkeypatch.setattr(cli, "AnthropicBackend", LLM)
    monkeypatch.setattr(cli, "_run_plan", lambda day, *a: planned.append(day) or ([], [], []))
    rules = type("R", (), {"categories": {"Meeting": None, "Gym": None}})()
    cli.cmd_ask(type("A", (), {"text": "spotkanie o 14, potem siłownia"})(), rules, {"llm": {"model": "m"}})
    out = capsys.readouterr().out
    assert created == [("Meeting", "Spotkanie", "14:00", "15:00")]
    assert planned == [date(2026, 9, 22)]
    assert "no 'Gym' calendar" in out and "summary" in out


def test_ask_without_api_key_explains(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cli.cmd_ask(type("A", (), {"text": "x"})(), None, None)
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out
