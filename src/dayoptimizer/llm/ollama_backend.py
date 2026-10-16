"""Local LLM through Ollama's HTTP API (stdlib only). Calendar text never leaves the Mac."""
from __future__ import annotations
import atexit
import json
import os
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from dayoptimizer import paths
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import (_FIX_SYSTEM, _NOTES_SYSTEM, _REQUEST_SYSTEM, _SUMMARY_SYSTEM, CompiledNotes,
                                      DayRequest, LLMTimeout, LLMUnavailable, TaskFix, compile_prompt, fix_prompt,
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


def ollama_binary() -> str | None:
    """The installed `ollama` command. The app bundle's PATH lacks Homebrew's
    folders, so look there too."""
    return shutil.which("ollama") or next(
        (p for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama") if os.access(p, os.X_OK)), None)


def ollama_available() -> bool:
    return ollama_running() or ollama_binary() is not None


_server: subprocess.Popen | None = None


def _stop_server() -> None:
    global _server
    if _server is not None and _server.poll() is None:
        _server.terminate()
        try:
            _server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server.kill()
    _server = None


def ensure_running(wait: float = 30.0) -> None:
    """Start Ollama for this run when it isn't up, and stop it again when the
    process ends: the model takes gigabytes of memory, so it only lives while
    DayOptimizer has work for it. A server someone else started is left alone."""
    global _server
    if ollama_running():
        return
    binary = ollama_binary()
    if binary is None:
        raise LLMUnavailable("Ollama isn't installed. Install it with:  brew install ollama")
    with open(paths.ensure_private_dir() / "ollama.log", "a") as log:  # the child keeps its own handle
        _server = subprocess.Popen([binary, "serve"], stdout=log, stderr=log)
    atexit.register(_stop_server)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if ollama_running():
            return
        time.sleep(0.3)
    _stop_server()
    raise LLMUnavailable("Ollama didn't start. Try it by hand:  ollama serve")


class OllamaBackend:
    one_day_at_a_time = True

    def __init__(self, model: str = "qwen3:8b", mode: str = "slots"):
        self.model = model
        # slots: code finds the legal times and the model only picks among them (week_plan.slot_items)
        self.slots = mode == "slots"

    def _chat(self, system: str, user: str, schema: dict | None = None, timeout: int = 180,
              num_predict: int | None = None) -> str:
        ensure_running()
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": False,
            # ponytail: fixed 8192 fits the week prompt (~2.7k) plus a capped 2000-token answer; size it from the prompt if plans grow
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        if num_predict:
            body["options"]["num_predict"] = num_predict
        if schema:
            body["format"] = schema
        req = Request(f"{_host()}/api/chat", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            self.prompt_tokens = data.get("prompt_eval_count")  # read by scripts/eval_tasks.py: is num_ctx enough?
            return data["message"]["content"]
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            if exc.code == 404 and "not found" in detail:
                raise LLMUnavailable(f"The local model isn't downloaded yet. Run:  ollama pull {self.model}") from None
            raise LLMUnavailable(f"Ollama error {exc.code}: {detail[:200]}") from None
        except TimeoutError:
            raise LLMTimeout("The local model took too long to answer. Try again, or a shorter message.") from None
        except (URLError, OSError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise LLMTimeout("The local model took too long to answer. Try again, or a shorter message.") from None
            raise LLMUnavailable("Ollama isn't running. Start it with:  brew services start ollama") from None

    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest:
        schema = DayRequest.model_json_schema()
        schema["$defs"]["NewEvent"]["properties"]["category"]["enum"] = list(categories)
        schema["$defs"]["TaskRequest"]["properties"]["category"]["enum"] = list(categories)
        raw = self._chat(_REQUEST_SYSTEM, request_prompt(text, today, now, categories), schema)
        return DayRequest.model_validate_json(raw)

    def plan_week(self, system: str, prompt: str, schema: dict | None = None):
        """`schema` is the answer schema with the allowed values filled in
        (week_plan.plan_schema). The answer is capped so a model that starts
        repeating itself stops instead of running for many minutes."""
        from dayoptimizer.llm.week_plan import WeekPlan
        raw = self._chat(system, prompt, schema or WeekPlan.model_json_schema(), timeout=300, num_predict=2000)
        return WeekPlan.model_validate_json(raw)

    def choose(self, system: str, prompt: str, schema: dict) -> dict:
        return json.loads(self._chat(system, prompt, schema, timeout=300, num_predict=1000))

    def task_fix(self, reply: str, task_line: str, blocks: list[str]) -> TaskFix:
        schema = TaskFix.model_json_schema()
        if blocks:
            schema["properties"]["blocks"]["items"]["enum"] = list(blocks)
        return TaskFix.model_validate_json(self._chat(_FIX_SYSTEM, fix_prompt(reply, task_line, blocks), schema))

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
            return rendered
