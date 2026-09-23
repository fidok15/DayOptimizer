import io
import json
from urllib.error import HTTPError
import pytest
from dayoptimizer.llm import ollama_backend as ob
from dayoptimizer.llm.backend import LLMUnavailable, make_backend, request_prompt


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_parse_request_uses_schema_and_no_thinking(monkeypatch):
    sent = {}

    def fake_urlopen(req, timeout):
        sent.update(json.loads(req.data))
        answer = {"events": [
            {"title": "Spotkanie", "category": "Meeting", "day": "today", "start_time": "14:00", "duration_minutes": 60}]}
        return _Resp(json.dumps({"message": {"content": json.dumps(answer)}}).encode())

    monkeypatch.setattr(ob, "urlopen", fake_urlopen)
    req = ob.OllamaBackend("qwen3:8b").parse_request("spotkanie o 14", "2026-09-22", "Tuesday 09:00", ["Meeting"])
    assert req.events[0].start_time == "14:00"
    assert sent["think"] is False and sent["format"]["title"] == "DayRequest" and sent["model"] == "qwen3:8b"


def test_missing_model_says_how_to_pull(monkeypatch):
    def fake_urlopen(req, timeout):
        raise HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"error":"model \'qwen3:8b\' not found"}'))

    monkeypatch.setattr(ob, "urlopen", fake_urlopen)
    with pytest.raises(LLMUnavailable, match="ollama pull qwen3:8b"):
        ob.OllamaBackend("qwen3:8b").parse_request("x", "2026-09-22", "09:00", ["Work"])


def test_summary_falls_back_when_ollama_down(monkeypatch):
    from dayoptimizer.core.models import PlannedChange
    monkeypatch.setattr(ob, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    ch = PlannedChange(kind="move", category="Gym", title="Workout", reason="tired")
    assert "Workout" in ob.OllamaBackend().summarize_changes([ch])


def test_make_backend_prefers_local_then_api(monkeypatch):
    monkeypatch.setattr(ob, "ollama_running", lambda: True)
    assert isinstance(make_backend({"backend": "auto"}), ob.OllamaBackend)
    monkeypatch.setattr(ob, "ollama_running", lambda: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert type(make_backend({"backend": "auto"})).__name__ == "AnthropicBackend"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(LLMUnavailable):
        make_backend({"backend": "auto"})


def test_request_prompt_has_now_and_categories():
    p = request_prompt("x", "2026-09-22", "Tuesday 09:00", ["Work"])
    assert "now: Tuesday 09:00" in p and "categories: Work" in p
