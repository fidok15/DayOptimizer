from __future__ import annotations
import anthropic
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import (_NOTES_SYSTEM, _REQUEST_SYSTEM, _SUMMARY_SYSTEM, CompiledNotes,
                                      DayRequest, compile_prompt, format_changes, request_prompt)

class AnthropicBackend:
    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=2048,
            system=_REQUEST_SYSTEM,
            messages=[{"role": "user", "content": request_prompt(text, today, now, categories)}],
            output_format=DayRequest,
        )
        return response.parsed_output

    def compile_notes(self, notes: str, categories: list[str]) -> CompiledNotes:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=2048,
            system=_NOTES_SYSTEM,
            messages=[{"role": "user", "content": compile_prompt(notes, categories)}],
            output_format=CompiledNotes,
        )
        return response.parsed_output

    def summarize_changes(self, changes: list[PlannedChange]) -> str:
        rendered = format_changes(changes)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=_SUMMARY_SYSTEM,
                messages=[{"role": "user", "content": rendered}],
            )
            return next((b.text for b in response.content if b.type == "text"), rendered)
        except anthropic.APIError:
            return rendered  # LLM down → deterministic fallback (hybrid guarantee)
