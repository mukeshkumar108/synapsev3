from __future__ import annotations

from typing import Any

from agent_contract import AgentInput, AgentOutput
from core.llm import LLMClient


STATE_PROMPT = """You are reading raw source material to understand the user's current temporary state.

Return a JSON object with one key:
- items: array containing zero or one state object

If present, the state object must include:
- emotional_state: happy|stressed|anxious|excited|flat|neutral|frustrated
- current_focus: string
- companion_category: win|low|struggle|fear|worry|celebration_moment|null
- energy_level: high|medium|low
- stress_level: high|medium|low
- notable_tension: string or null
- sensitivity: low|medium|high
- stale_after_hours: integer
- raw_evidence: exact quote from the source
- confidence: number from 0.0 to 1.0
- provisional: true

Rules:
- State is temporary and must never be framed as durable.
- Use companion_category for temporary companion-relevant states such as a current win, low, struggle, worry, fear, or celebration moment.
- If the user describes a present-moment low, worry, fear, vulnerability, pride, or emotional pressure, that belongs here.
- If the statement is a durable aspiration, preference, value, or boundary, leave it for the fact agent instead.
- Do not diagnose or use clinical language.
- If the transcript does not contain a meaningful current state worth storing, return an empty array.
- Return valid JSON only."""

ALLOWED_EMOTIONS = {"happy", "stressed", "anxious", "excited", "flat", "neutral", "frustrated"}
ALLOWED_LEVELS = {"high", "medium", "low"}
ALLOWED_COMPANION_CATEGORIES = {
    "win",
    "low",
    "struggle",
    "fear",
    "worry",
    "celebration_moment",
    None,
}
EXPECTED_KEYS = {
    "emotional_state",
    "current_focus",
    "companion_category",
    "energy_level",
    "stress_level",
    "notable_tension",
    "sensitivity",
    "stale_after_hours",
    "raw_evidence",
    "confidence",
    "provisional",
}


def _validate_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("State candidate must be a JSON object.")

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"State candidate missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"State candidate has unexpected keys: {sorted(extra)}")

    if payload["emotional_state"] not in ALLOWED_EMOTIONS:
        raise ValueError("State emotional_state is invalid.")
    if not isinstance(payload["current_focus"], str) or not payload["current_focus"].strip():
        raise ValueError("State current_focus must be a non-empty string.")
    if payload["companion_category"] not in ALLOWED_COMPANION_CATEGORIES:
        raise ValueError("State companion_category is invalid.")
    for key in ("energy_level", "stress_level", "sensitivity"):
        if payload[key] not in ALLOWED_LEVELS:
            raise ValueError(f"State field {key} must be one of high, medium, low.")
    if payload["notable_tension"] is not None and not isinstance(payload["notable_tension"], str):
        raise ValueError("State notable_tension must be a string or null.")
    if not isinstance(payload["stale_after_hours"], int) or payload["stale_after_hours"] <= 0:
        raise ValueError("State stale_after_hours must be a positive integer.")
    if payload["provisional"] is not True:
        raise ValueError("State provisional must be true.")
    if not isinstance(payload["raw_evidence"], str) or not payload["raw_evidence"].strip():
        raise ValueError("State raw_evidence must be a non-empty string.")

    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("State confidence must be a number between 0 and 1.")
    payload["confidence"] = float(confidence)

    return payload


def run(agent_input: AgentInput, llm_client: LLMClient | None = None) -> AgentOutput:
    client = llm_client or LLMClient()
    try:
        payload = client.generate_json(
            system_prompt=STATE_PROMPT,
            user_prompt=agent_input.raw_content,
            temperature=0.2,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("State agent response must include an items array.")
        if len(items) > 1:
            raise ValueError("State agent must return at most one state item.")
        return AgentOutput(
            agent="state_agent",
            status="success",
            items=[_validate_item(item) for item in items],
            errors=[],
            confidence_notes="Temporary state extraction completed from raw content with provisional semantics.",
        )
    except Exception as exc:
        return AgentOutput(
            agent="state_agent",
            status="error",
            items=[],
            errors=[str(exc)],
            confidence_notes="State extraction failed.",
        )
