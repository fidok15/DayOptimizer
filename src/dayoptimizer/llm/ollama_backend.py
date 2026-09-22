"""Local LLM through Ollama's HTTP API (stdlib only). Calendar text never leaves the Mac."""
from __future__ import annotations
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import (_NOTES_SYSTEM, _REQUEST_SYSTEM, _SUMMARY_SYSTEM, CompiledNotes,
                                      DayRequest, LLMUnavailable, compile_prompt, format_changes,
                                      request_prompt)


def _host() -> str:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    return host if host.startswith("http") else f"http://{host}"


def ollama_running() -> bool:
    try:
        with urlopen(f"{_host()}/api/version", timeout=1):
            return True
    except (URLError, OSError):
        return False


class OllamaBackend:
    def __init__(self, model: str = "qwen3:8b"):
        self.model = model

    def _chat(self, system: str, user: str, schema: dict | None = None) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": False,  # qwen3 answers in ~6 s without it, ~40 s with
            "options": {"temperature": 0},
        }
        if schema:
            body["format"] = schema  # Ollama constrains the output to this JSON schema
        req = Request(f"{_host()}/api/chat", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())["message"]["content"]
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            if exc.code == 404 and "not found" in detail:
                raise LLMUnavailable(f"The local model isn't downloaded yet. Run:  ollama pull {self.model}") from None
            raise LLMUnavailable(f"Ollama error {exc.code}: {detail[:200]}") from None
        except TimeoutError:
            raise LLMUnavailable("The local model took too long to answer. Try again, or a shorter message.") from None
        except (URLError, OSError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise LLMUnavailable("The local model took too long to answer. Try again, or a shorter message.") from None
            raise LLMUnavailable("Ollama isn't running. Start it with:  brew services start ollama") from None

    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest:
        schema = DayRequest.model_json_schema()
        # the grammar then can't produce a category the user doesn't have
        schema["$defs"]["NewEvent"]["properties"]["category"]["enum"] = list(categories)
        raw = self._chat(_REQUEST_SYSTEM, request_prompt(text, today, now, categories), schema)
        return DayRequest.model_validate_json(raw)

    def compile_notes(self, notes: str, categories: list[str]) -> CompiledNotes:
        raw = self._chat(_NOTES_SYSTEM, compile_prompt(notes, categories), CompiledNotes.model_json_schema())
        return CompiledNotes.model_validate_json(raw)

    def summarize_changes(self, changes: list[PlannedChange]) -> str:
        rendered = format_changes(changes)
        if not changes:
            return rendered
        try:
            return self._chat(_SUMMARY_SYSTEM, rendered).strip() or rendered
        except LLMUnavailable:
            return rendered  # LLM down: deterministic fallback, same as Anthropic
