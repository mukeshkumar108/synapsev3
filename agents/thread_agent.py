from __future__ import annotations

from typing import Any

from agent_contract import AgentInput, AgentOutput
from core.llm import LLMClient


THREAD_PROMPT = """You are identifying unresolved ongoing situations from raw source material.

Return a JSON object with one key:
- items: array of thread objects

Each thread object must include:
- title: short thread name
- summary: concise description of the unresolved situation
- companion_category: struggle|hope|fear|worry|ask_about_later|celebration_moment|relationship_context|null
- involves: array of people or things involved
- last_status: what the state of the situation is at the end of the transcript
- follow_up_question: a natural follow-up Sophie could ask later
- follow_up_after_hours: integer hours before follow-up makes sense
- needs_confirmation: boolean
- salience: high|medium|low
- priority: high|medium|low
- sensitivity: low|medium|high
- stale_after_hours: integer
- related_people: array of names
- related_projects: array of projects/topics
- raw_evidence: exact quote from the source
- confidence: number from 0.0 to 1.0

Rules:
- Extract only genuinely unresolved situations worth following up.
- Do not create threads for resolved items, trivial chatter, routine scheduling, or isolated moods.
- Do not turn tasks or events into threads unless the unresolved situation itself is the point.
- Do not create threads for simple tasks, reminders, or one-off to-dos.
- A thread requires real unresolvedness, waiting-on, blocked-by, relationship tension, dependency on another person/entity, or follow-up value beyond simply doing the task.
- Do not create a thread merely because something has a future date.
- Good thread examples:
  - "Things with Nina still feel unresolved after our argument."
  - "Vendor negotiation is stuck because legal has not responded."
  - "Venue for the offsite is still TBD."
  - "Waiting on Jordan to send the contract."
- Bad thread examples:
  - "Remind me to send Leo the draft on Monday."
  - "I need to send the proposal tomorrow."
  - "I have a product review Thursday at 3pm."
  - "Dentist appointment Friday."
- Do not create a thread for every tentative social plan.
- A tentative social plan only qualifies if there is real unresolved follow-up value; if so keep salience moderate or lower and set needs_confirmation=true.
- Companion follow-up threads are in scope when there is meaningful follow-up value: something to ask about later, an unresolved emotional open loop, an upcoming meaningful moment, a celebration worth checking back on, a relationship situation, or a worry that deserves gentle follow-up.
- Do not create dependency-oriented, possessive, or manipulative follow-up framing.
- Use companion_category only when it adds clear semantic value. Otherwise return null.
- Keep language concrete and non-psychologizing.
- Return an empty array if there are no real thread candidates.
- Return valid JSON only."""

ALLOWED_LEVELS = {"high", "medium", "low"}
ALLOWED_COMPANION_CATEGORIES = {
    "struggle",
    "hope",
    "fear",
    "worry",
    "ask_about_later",
    "celebration_moment",
    "relationship_context",
    None,
}
EXPECTED_KEYS = {
    "title",
    "summary",
    "companion_category",
    "involves",
    "last_status",
    "follow_up_question",
    "follow_up_after_hours",
    "needs_confirmation",
    "salience",
    "priority",
    "sensitivity",
    "stale_after_hours",
    "related_people",
    "related_projects",
    "raw_evidence",
    "confidence",
}


def _validate_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Thread candidate must be a JSON object.")

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Thread candidate missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Thread candidate has unexpected keys: {sorted(extra)}")

    for key in ("title", "summary", "last_status", "follow_up_question", "raw_evidence"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValueError(f"Thread field {key} must be a non-empty string.")
    if payload["companion_category"] not in ALLOWED_COMPANION_CATEGORIES:
        raise ValueError("Thread companion_category is invalid.")

    for key in ("involves", "related_people", "related_projects"):
        value = payload[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Thread field {key} must be an array of strings.")

    for key in ("follow_up_after_hours", "stale_after_hours"):
        if not isinstance(payload[key], int) or payload[key] <= 0:
            raise ValueError(f"Thread field {key} must be a positive integer.")
    if not isinstance(payload["needs_confirmation"], bool):
        raise ValueError("Thread needs_confirmation must be a boolean.")

    for key in ("salience", "priority", "sensitivity"):
        if payload[key] not in ALLOWED_LEVELS:
            raise ValueError(f"Thread field {key} must be one of high, medium, low.")

    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("Thread confidence must be a number between 0 and 1.")
    payload["confidence"] = float(confidence)

    return payload


def run(agent_input: AgentInput, llm_client: LLMClient | None = None) -> AgentOutput:
    client = llm_client or LLMClient()
    try:
        payload = client.generate_json(
            system_prompt=THREAD_PROMPT,
            user_prompt=agent_input.raw_content,
            temperature=0.2,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("Thread agent response must include an items array.")
        return AgentOutput(
            agent="thread_agent",
            status="success",
            items=[_validate_item(item) for item in items],
            errors=[],
            confidence_notes="Thread extraction completed from raw content with unresolved-situation discipline.",
        )
    except Exception as exc:
        return AgentOutput(
            agent="thread_agent",
            status="error",
            items=[],
            errors=[str(exc)],
            confidence_notes="Thread extraction failed.",
        )
