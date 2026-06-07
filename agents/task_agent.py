from __future__ import annotations

from typing import Any

from agent_contract import AgentInput, AgentOutput
from core.llm import LLMClient


TASK_PROMPT = """You are extracting tasks and commitments from raw source material for a personal AI assistant.

Return a JSON object with one key:
- items: array of task objects

Each task object must include:
- title: short actionable title
- description: optional context string or null
- due_date: ISO date/time string if explicitly grounded, otherwise null
- reminder_at: ISO date/time string if explicitly grounded, otherwise null
- priority: high|medium|low
- urgency: high|medium|low
- is_habit: boolean
- recurrence: daily|weekly|monthly|null
- waiting_on: string or null
- needs_confirmation: boolean
- salience: high|medium|low
- raw_evidence: exact quote from the source
- confidence: number from 0.0 to 1.0
- related_people: array of names
- related_projects: array of projects/topics

Rules:
- Extract only clearly actionable tasks, reminders, commitments, follow-ups, habits, or waiting-on states.
- Do not extract calendar events as tasks.
- Do not create tasks like "attend dinner", "attend meeting", or "attend product review" from simple scheduled events.
- If the transcript only says an event exists, leave it for the event agent.
- Extract a task only when there is an explicit action, commitment, reminder, follow-up, waiting-on state, or recurring habit.
- Do not turn companion-memory follow-up requests into tasks when the point is relational continuity rather than an operational to-do.
- If the user says something like "Ask me how it went" about a conversation, interview, relationship moment, or meaningful event, prefer leaving that for the thread agent unless there is also a separate real-world action to perform.
- Good task examples:
  - "Remind me to send Leo the draft on Monday."
  - "I need to prepare for the product review."
  - "I am still waiting on Jordan to send the contract."
- Bad task examples:
  - "I have a product review with Sam on Thursday at 3pm."
  - "Alex invited me to dinner next Tuesday."
- Do not invent dates or reminders that were not stated.
- Use null for missing optional fields.
- Return an empty array if there are no real task candidates.
- Return valid JSON only."""

ALLOWED_LEVELS = {"high", "medium", "low"}
ALLOWED_RECURRENCE = {"daily", "weekly", "monthly", None}
EXPECTED_KEYS = {
    "title",
    "description",
    "due_date",
    "reminder_at",
    "priority",
    "urgency",
    "is_habit",
    "recurrence",
    "waiting_on",
    "needs_confirmation",
    "salience",
    "raw_evidence",
    "confidence",
    "related_people",
    "related_projects",
}


def _validate_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Task candidate must be a JSON object.")

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Task candidate missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Task candidate has unexpected keys: {sorted(extra)}")

    if not isinstance(payload["title"], str) or not payload["title"].strip():
        raise ValueError("Task title must be a non-empty string.")

    for key in ("description", "due_date", "reminder_at", "waiting_on"):
        value = payload[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Task field {key} must be a string or null.")

    for key in ("priority", "urgency", "salience"):
        if payload[key] not in ALLOWED_LEVELS:
            raise ValueError(f"Task field {key} must be one of high, medium, low.")

    if not isinstance(payload["is_habit"], bool):
        raise ValueError("Task is_habit must be a boolean.")
    if not isinstance(payload["needs_confirmation"], bool):
        raise ValueError("Task needs_confirmation must be a boolean.")
    if payload["recurrence"] not in ALLOWED_RECURRENCE:
        raise ValueError("Task recurrence must be daily, weekly, monthly, or null.")

    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("Task confidence must be a number between 0 and 1.")
    payload["confidence"] = float(confidence)

    if not isinstance(payload["raw_evidence"], str) or not payload["raw_evidence"].strip():
        raise ValueError("Task raw_evidence must be a non-empty string.")

    for key in ("related_people", "related_projects"):
        value = payload[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Task field {key} must be an array of strings.")

    return payload


def run(agent_input: AgentInput, llm_client: LLMClient | None = None) -> AgentOutput:
    client = llm_client or LLMClient()
    try:
        payload = client.generate_json(
            system_prompt=TASK_PROMPT,
            user_prompt=agent_input.raw_content,
            temperature=0.1,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("Task agent response must include an items array.")
        return AgentOutput(
            agent="task_agent",
            status="success",
            items=[_validate_item(item) for item in items],
            errors=[],
            confidence_notes="Task extraction completed from raw content without persistence side effects.",
        )
    except Exception as exc:
        return AgentOutput(
            agent="task_agent",
            status="error",
            items=[],
            errors=[str(exc)],
            confidence_notes="Task extraction failed.",
        )
