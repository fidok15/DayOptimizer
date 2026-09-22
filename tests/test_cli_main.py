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


def test_plain_words_are_understood_in_the_terminal(routed, monkeypatch):
    monkeypatch.setattr(cli, "cmd_ask", lambda args, *a: routed.append(("ask", args.text)))
    cli.main(["meeting", "at 14:00,", "then gym"])
    assert routed == [("ask", "meeting at 14:00, then gym")]


def test_setup_runs_in_terminal(routed):
    cli.main(["setup"])
    assert routed == [("setup",)]


def test_events_to_create_validates_llm_output():
    req = DayRequest(events=[
        NewEvent(title="Spotkanie", category="Meeting", start_time="14:00", duration_minutes=60),
        NewEvent(title="Siłownia", category="Gym", day="thursday", start_time="15:00"),
        NewEvent(title="Coś", category="Nope", start_time="16:00"),
        NewEvent(title="Kiedyś", category="Gym", date="2026-09-22"),
        NewEvent(title="Maraton", category="Gym", start_time="06:00", duration_minutes=10_000),
        NewEvent(title="Praca", category="Meeting", start_time="10:30", end_time="17:00", duration_minutes=300),
        NewEvent(title="Zero", category="Gym", start_time="18:00", duration_minutes=0, end_time="17:00"),
    ])
    ok, problems = cli.events_to_create(req, {"Meeting": None, "Gym": None}, date(2026, 9, 22))
    assert [(c, t, s.hour, (e - s).seconds // 60) for c, t, s, e in ok] == [
        ("Meeting", "Spotkanie", 14, 60), ("Gym", "Siłownia", 15, 60), ("Gym", "Maraton", 6, 720),
        ("Meeting", "Praca", 10, 390), ("Gym", "Zero", 18, 60)]
    assert ok[0][2].date() == date(2026, 9, 22) and ok[1][2].date() == date(2026, 9, 24)
    assert len(problems) == 2 and "Nope" in problems[0] and "no time" in problems[1]


class _LLM:
    def parse_request(self, text, today, now, categories):
        return DayRequest(events=[
            NewEvent(title="Spotkanie", category="Meeting", start_time="14:00", duration_minutes=60),
            NewEvent(title="Siłownia", category="Gym", start_time="15:00", duration_minutes=90)])

    def summarize_changes(self, changes):
        return "summary"


RULES = type("R", (), {"categories": {"Meeting": None, "Gym": None}})()


def test_ask_shows_events_then_hands_them_to_the_bundle(routed, monkeypatch, capsys):
    import json
    monkeypatch.setattr(cli, "make_backend", lambda cfg: _LLM())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)  # non-interactive: no prompt
    cli.cmd_ask(type("A", (), {"text": "spotkanie o 14, potem siłownia"})(), RULES, {"llm": {}})
    assert "I'll add:" in capsys.readouterr().out
    (kind, argv), = routed
    assert kind == "bundle" and argv[0] == "add"
    assert [(e["category"], e["title"]) for e in json.loads(argv[1])] == [("Meeting", "Spotkanie"), ("Gym", "Siłownia")]


def test_ask_cancel_changes_nothing(routed, monkeypatch):
    monkeypatch.setattr(cli, "make_backend", lambda cfg: _LLM())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.console, "input", lambda *a, **k: "n")
    cli.cmd_ask(type("A", (), {"text": "x"})(), RULES, {"llm": {}})
    assert routed == []


def test_add_creates_events_then_replans(monkeypatch, capsys):
    import json
    created, planned = [], []

    class Cal:
        def request_access(self):
            return True

        def create_event(self, category, title, start, end):
            if category == "Gym":
                raise KeyError(category)  # no Gym calendar in Apple Calendar
            created.append((category, title, f"{start:%H:%M}", f"{end:%H:%M}"))

    cli.paths.ensure_private_dir()
    monkeypatch.setattr(cli, "CalendarClient", Cal)
    monkeypatch.setattr(cli, "make_backend", lambda cfg: _LLM())
    monkeypatch.setattr(cli, "_run_plan", lambda day, *a: planned.append(day) or ([], [], []))
    events = json.dumps([
        {"category": "Meeting", "title": "Spotkanie", "start": "2026-09-22T14:00:00+02:00", "end": "2026-09-22T15:00:00+02:00"},
        {"category": "Gym", "title": "Siłownia", "start": "2026-09-22T15:00:00+02:00", "end": "2026-09-22T16:30:00+02:00"},
        {"category": "Nope", "title": "X", "start": "2026-09-22T17:00:00+02:00", "end": "2026-09-22T18:00:00+02:00"}])
    cli.cmd_add(type("A", (), {"events": events})(), RULES, {"llm": {}})
    out = capsys.readouterr().out
    assert created == [("Meeting", "Spotkanie", "14:00", "15:00")]
    assert planned == [date(2026, 9, 22)]
    assert "no 'Gym' calendar" in out and "summary" in out


def test_ask_without_any_llm_explains(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dayoptimizer.llm.ollama_backend.ollama_running", lambda: False)
    cli.cmd_ask(type("A", (), {"text": "x"})(), RULES, {"llm": {"backend": "auto"}})
    out = capsys.readouterr().out
    assert "ollama pull" in out and "ANTHROPIC_API_KEY" in out
