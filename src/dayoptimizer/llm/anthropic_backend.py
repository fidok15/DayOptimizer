from __future__ import annotations
import anthropic
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import Intent, format_changes

_INTENT_SYSTEM = (
    "You are the intent parser for the DayOptimizer calendar assistant. "
    "Turn the user's message into an intent. Calendar categories: Important, Meeting, "
    "Work, Sleep, Gym, Food, Learn, Transport, Free time. "
    "Return dates as ISO (YYYY-MM-DD) relative to the given 'today'."
)

_SUMMARY_SYSTEM = (
    "You summarize the changes to the user's day plan for them. In English, "
    "concise, bulleted, what and why. Do not invent changes outside the list."
)

class AnthropicBackend:
    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

    def parse_intent(self, text: str, today: str) -> Intent:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=1024,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": f"today: {today}\nmessage: {text}"}],
            output_format=Intent,
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
