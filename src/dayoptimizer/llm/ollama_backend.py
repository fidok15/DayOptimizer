"""Local LLM through Ollama's HTTP API (stdlib only). Calendar text never leaves the Mac."""
from __future__ import annotations
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import (_REQUEST_SYSTEM, _SUMMARY_SYSTEM, DayRequest, LLMUnavailable,
                                      format_changes, request_prompt)


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
            "think": False,  # reasoning models (qwen3) answer much faster without it
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
        except (URLError, OSError):
            raise LLMUnavailable("Ollama isn't running. Start it with:  brew services start ollama") from None

    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest:
        raw = self._chat(_REQUEST_SYSTEM, request_prompt(text, today, now, categories),
                         DayRequest.model_json_schema())
        return DayRequest.model_validate_json(raw)

    def summarize_changes(self, changes: list[PlannedChange]) -> str:
        rendered = format_changes(changes)
        if not changes:
            return rendered
        try:
            return self._chat(_SUMMARY_SYSTEM, rendered).strip() or rendered
        except LLMUnavailable:
            return rendered  # LLM down: deterministic fallback, same as Anthropic
