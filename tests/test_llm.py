from datetime import datetime
from unittest.mock import MagicMock
import anthropic
import httpx
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import DayRequest, NewEvent, format_changes
from dayoptimizer.llm.anthropic_backend import AnthropicBackend

def test_day_request_model_validates():
    r = DayRequest(events=[NewEvent(title="Standup", category="Work")])
    assert r.events[0].day == "today" and r.events[0].start_time is None and r.reply is None


def test_resolve_day_words():
    from datetime import date
    from dayoptimizer.llm.backend import resolve_day
    tue = date(2026, 9, 22)
    assert resolve_day("tomorrow", tue) == date(2026, 9, 23)
    assert resolve_day("thursday", tue) == date(2026, 9, 24)
    assert resolve_day("tuesday", tue) == tue and resolve_day("monday", tue) == date(2026, 9, 28)

def test_format_changes_readable():
    ch = PlannedChange(kind="move", category="Gym", title="Workout",
                       reason="low Body Battery",
                       new_start=datetime(2026, 7, 3, 17, 0), new_end=datetime(2026, 7, 3, 18, 0))
    text = format_changes([ch])
    assert "Gym" in text and "17:00" in text and "Body Battery" in text

def test_parse_request_sends_user_categories():
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.model = "claude-opus-4-8"
    backend.client = MagicMock()
    fake = MagicMock()
    fake.parsed_output = DayRequest()
    backend.client.messages.parse.return_value = fake
    req = backend.parse_request("plan my day", today="2026-07-03", now="09:00", categories=["Choir", "Work"])
    assert req.events == []
    kwargs = backend.client.messages.parse.call_args.kwargs
    assert kwargs["output_format"] is DayRequest
    assert "Choir, Work" in kwargs["messages"][0]["content"]
    assert "temperature" not in kwargs  # rejected on Opus 4.7+

def test_summarize_changes_uses_messages_create():
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.model = "claude-opus-4-8"
    backend.client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "summary"
    fake = MagicMock()
    fake.content = [block]
    backend.client.messages.create.return_value = fake

    ch = PlannedChange(kind="move", category="Gym", title="Workout", reason="low Body Battery")
    result = backend.summarize_changes([ch])

    assert result == "summary"
    kwargs = backend.client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 1000
    assert "temperature" not in kwargs

def test_summarize_changes_falls_back_on_api_error():
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.model = "claude-opus-4-8"
    backend.client = MagicMock()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    backend.client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    ch = PlannedChange(kind="move", category="Gym", title="Workout", reason="low Body Battery")
    result = backend.summarize_changes([ch])

    assert result == format_changes([ch])

def test_format_changes_create_kind():
    ch = PlannedChange(kind="create", category="Learn", title="Python course", reason="free time")
    text = format_changes([ch])
    assert "[create]" in text and "Learn" in text and "Python course" in text

def test_format_changes_note_kind():
    ch = PlannedChange(kind="note", category="Free time", title="Note", reason="no conflict")
    text = format_changes([ch])
    assert "[note]" in text and "Free time" in text

def test_format_changes_requires_approval_flag():
    ch = PlannedChange(kind="move", category="Work", title="Meeting", reason="conflict",
                        requires_approval=True)
    text = format_changes([ch])
    assert "[approval required]" in text

def test_format_changes_empty_list():
    assert format_changes([]) == "No changes — the plan is consistent."
