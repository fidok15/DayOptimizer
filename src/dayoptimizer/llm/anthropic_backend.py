from __future__ import annotations
import anthropic
from dayoptimizer.core.models import PlannedChange
from dayoptimizer.llm.backend import DayRequest, format_changes

_REQUEST_SYSTEM = (
    "You turn a user's message about their day into calendar events for the DayOptimizer "
    "planner. The message may be in any language; keep event titles in that language.\n"
    "- One event per thing the user says they will do at a known time. Never invent events.\n"
    "- category must be exactly one of the listed categories: pick the closest fit.\n"
    "- Dates are ISO (YYYY-MM-DD), resolved against 'today' ('tomorrow', weekday names...).\n"
    "- start_time is HH:MM, 24h. 'then'/'after that' starts when the previous event ends. "
    "If the time can't be worked out, leave start_time empty.\n"
    "- duration_minutes from the message ('about an hour' = 60); empty if not said.\n"
    "- date is the day the message is about (today if unclear).\n"
    "- If the message isn't about the schedule, return no events and a short reply."
)

_SUMMARY_SYSTEM = (
    "You summarize the changes to the user's day plan for them. In English, "
    "concise, bulleted, what and why. Do not invent changes outside the list."
)

class AnthropicBackend:
    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

    def parse_request(self, text: str, today: str, now: str, categories: list[str]) -> DayRequest:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=2048,
            system=_REQUEST_SYSTEM,
            messages=[{"role": "user", "content": (
                f"today: {today} ({now})\ncategories: {', '.join(categories)}\nmessage: {text}")}],
            output_format=DayRequest,
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
