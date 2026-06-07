from __future__ import annotations

from typing import Any

from agent_contract import AgentInput, AgentOutput
from core.llm import LLMClient


EVENT_PROMPT = """You are extracting calendar events, invitations, appointments, deadlines, and time-anchored plans.

Return a JSON object with one key:
- items: array of event objects

Each event object must include:
- title: short event title
- date: ISO date if determinable, otherwise null
- time: ISO time or datetime if explicitly mentioned, otherwise null
- duration: string or null
- location: string or null
- attendees: array of names
- is_invitation: boolean
- needs_confirmation: boolean
- is_past: boolean
- urgency: high|medium|low
- salience: high|medium|low
- sensitivity: low|medium|high
- related_people: array of names
- related_projects: array of projects/topics
- raw_evidence: exact quote from the source
- confidence: number from 0.0 to 1.0

Rules:
- Resolve relative dates using the current_date context when it is provided.
- Never guess a date or time that is not stated or clearly determinable.
- If the event is tentative, incomplete, or ambiguous, set needs_confirmation=true.
- Deadlines and dated plans belong here.
- Reminders and send/call/do tasks are not events just because they mention a date.
- Good event examples:
  - "I have a product review with Sam on Thursday at 3pm."
  - "Alex invited me to dinner next Tuesday at 7pm."
  - "The design deadline is Friday."
- Bad event examples:
  - "Remind me to send Leo the draft on Monday."
  - "I need to prepare for the product review."
- Do not extract tasks, habits, moods, or unresolved threads.
- Return an empty array if there are no event candidates.
- Return valid JSON only."""

ALLOWED_LEVELS = {"high", "medium", "low"}
EXPECTED_KEYS = {
    "title",
    "date",
    "time",
    "duration",
    "location",
    "attendees",
    "is_invitation",
    "needs_confirmation",
    "is_past",
    "urgency",
    "salience",
    "sensitivity",
    "related_people",
    "related_projects",
    "raw_evidence",
    "confidence",
}


def _validate_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Event candidate must be a JSON object.")

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Event candidate missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Event candidate has unexpected keys: {sorted(extra)}")

    if not isinstance(payload["title"], str) or not payload["title"].strip():
        raise ValueError("Event title must be a non-empty string.")

    for key in ("date", "time", "duration", "location"):
        value = payload[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Event field {key} must be a string or null.")

    for key in ("attendees", "related_people", "related_projects"):
        value = payload[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Event field {key} must be an array of strings.")

    for key in ("is_invitation", "needs_confirmation", "is_past"):
        if not isinstance(payload[key], bool):
            raise ValueError(f"Event field {key} must be a boolean.")

    for key in ("urgency", "salience", "sensitivity"):
        if payload[key] not in ALLOWED_LEVELS:
            raise ValueError(f"Event field {key} must be one of high, medium, low.")

    if not isinstance(payload["raw_evidence"], str) or not payload["raw_evidence"].strip():
        raise ValueError("Event raw_evidence must be a non-empty string.")

    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("Event confidence must be a number between 0 and 1.")
    payload["confidence"] = float(confidence)

    return payload


def run(agent_input: AgentInput, llm_client: LLMClient | None = None) -> AgentOutput:
    client = llm_client or LLMClient()
    current_date = agent_input.context.get("current_date")
    user_prompt = agent_input.raw_content
    if current_date:
        user_prompt = f"current_date: {current_date}\n\nTranscript:\n{agent_input.raw_content}"

    try:
        payload = client.generate_json(
            system_prompt=EVENT_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("Event agent response must include an items array.")
        return AgentOutput(
            agent="event_agent",
            status="success",
            items=[_validate_item(item) for item in items],
            errors=[],
            confidence_notes="Event extraction completed from raw content with strict temporal grounding.",
        )
    except Exception as exc:
        return AgentOutput(
            agent="event_agent",
            status="error",
            items=[],
            errors=[str(exc)],
            confidence_notes="Event extraction failed.",
        )
