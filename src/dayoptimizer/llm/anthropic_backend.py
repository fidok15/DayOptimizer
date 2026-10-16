from __future__ import annotations
import anthropic
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import (_FIX_SYSTEM, _NOTES_SYSTEM, _REQUEST_SYSTEM, _SUMMARY_SYSTEM, CompiledNotes,
                                      DayRequest, TaskFix, compile_prompt, fix_prompt, format_changes, request_prompt)

class AnthropicBackend:
    def __init__(self, model: str = "claude-sonnet-5-5"):
        self.model = model
        self.client = anthropic.Anthropic()

    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=2048,
            system=_REQUEST_SYSTEM,
            messages=[{"role": "user", "content": request_prompt(text, today, now, categories)}],
            output_format=DayRequest,
        )
        return response.parsed_output

    def plan_week(self, system: str, prompt: str, schema: dict | None = None):
        # `schema` (the closed choices) is for small local models; the
        # validator catches what Claude gets wrong, which is rare.
        from dayoptimizer.llm.week_plan import WeekPlan
        with self.client.messages.stream(
            model=self.model,
            max_tokens=32000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=[{"role": "user", "content": prompt}],
            output_format=WeekPlan,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"the model stopped early ({response.stop_reason})")
        return response.parsed_output

    def task_fix(self, reply: str, task_line: str, blocks: list[str]) -> TaskFix:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=1024,
            system=_FIX_SYSTEM,
            messages=[{"role": "user", "content": fix_prompt(reply, task_line, blocks)}],
            output_format=TaskFix,
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
            return rendered
