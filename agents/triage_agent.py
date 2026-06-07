from __future__ import annotations

from typing import Any

from agent_contract import AgentInput, AgentOutput
from core.llm import LLMClient


TRIAGE_PROMPT = """You are a classifier. Read the raw content and return a JSON object with exactly these keys:
has_tasks: boolean
has_events: boolean
has_facts: boolean
has_state_change: boolean
has_threads: boolean
has_invitations: boolean
session_kind: one of technical, personal, mixed, transient
emotional_weight: one of low, medium, high
emotional_note: one short sentence if there is meaningful emotional weight, otherwise null
tension_signal: one sentence about an unspoken or unresolved tension in USER turns only, otherwise null
ignore_reasons: array of short reasons for content that should not be routed or stored
memory_worthy: boolean

Rules:
- This is routing only. Do not extract tasks, events, facts, threads, quotes, or summaries.
- Later agents will reread the raw transcript. Do not do their job here.
- Be conservative. Casual mentions of coffee, a walk, a video, needing a break, or a light reset are not events, not durable facts, and not state changes unless the user clearly frames them as important or changing.
- Mark memory_worthy true only if the transcript contains at least one of: a real follow-up action, a meaningful event or invitation, a durable fact or preference, an unresolved thread, or a meaningful current-state change worth storing or routing.
- If the conversation is casual, fleeting, and has no future relevance, set memory_worthy false and include ignore_reasons explaining why.
- has_facts is only for durable facts or preferences about the user or other people, not one-off plans.
- Set has_facts=true for explicit durable companion-calibration signals, including communication preferences, tone preferences, comfort preferences, encouragement style, reminder style, challenge style, language preferences, humour or directness preferences, explicit "speak to me like this" or "don't speak to me like this" instructions, explicit avoid topics, and explicit sensitivity boundaries.
- Explicit instructions about how Sophie should communicate are memory-worthy and should route to the fact agent.
- Explicit "do not bring this up" or topic-boundary instructions are memory-worthy and should route to the fact agent.
- Do not set has_facts=true for vague emotional states alone, casual reset chat, or one-off operational status.
- has_state_change is only true when the user clearly expresses a meaningful current emotional or situational state worth storing or routing, not just a passing reset.
- has_threads is only true for genuine unresolved ongoing situations with follow-up value beyond simply doing a task or attending an event.
- Do not set has_threads true for a simple reminder, one-off to-do, ordinary appointment, or scheduled event.
- Do not set has_threads true for a tentative plan unless there is real unresolved dependency, tension, blocked progress, waiting-on, or relationship/project follow-up value.
- Good has_threads=true examples:
  - "Things with Nina still feel unresolved after our argument."
  - "Vendor negotiation is stuck because legal has not responded."
  - "Venue for the offsite is still TBD."
  - "I am still waiting on Jordan to send the contract."
- Bad has_threads=true examples:
  - "Remind me to send Leo the draft on Monday."
  - "I need to send the proposal tomorrow."
  - "I have a product review Thursday at 3pm."
  - "Dentist appointment Friday."
- tension_signal should only use evidence from USER turns and should stay null unless something genuinely feels unresolved, avoided, or underneath the surface.
- Base the answer only on the raw content provided.
- Return only valid JSON with those exact keys."""

ALLOWED_WEIGHTS = {"low", "medium", "high"}
ALLOWED_SESSION_KINDS = {"technical", "personal", "mixed", "transient"}
EXPECTED_KEYS = {
    "has_tasks",
    "has_events",
    "has_facts",
    "has_state_change",
    "has_threads",
    "has_invitations",
    "session_kind",
    "emotional_weight",
    "emotional_note",
    "tension_signal",
    "ignore_reasons",
    "memory_worthy",
}


def _validate_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Triage response must be a JSON object.")

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Triage response missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Triage response has unexpected keys: {sorted(extra)}")

    for key in {
        "has_tasks",
        "has_events",
        "has_facts",
        "has_state_change",
        "has_threads",
        "has_invitations",
        "memory_worthy",
    }:
        if not isinstance(payload[key], bool):
            raise ValueError(f"Triage field {key} must be a boolean.")

    if payload["session_kind"] not in ALLOWED_SESSION_KINDS:
        raise ValueError(
            "Triage session_kind must be one of technical, personal, mixed, transient."
        )

    if payload["emotional_weight"] not in ALLOWED_WEIGHTS:
        raise ValueError("Triage emotional_weight must be one of low, medium, high.")

    for key in ("emotional_note", "tension_signal"):
        value = payload[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Triage field {key} must be a string or null.")

    ignore_reasons = payload["ignore_reasons"]
    if not isinstance(ignore_reasons, list) or not all(
        isinstance(reason, str) for reason in ignore_reasons
    ):
        raise ValueError("Triage ignore_reasons must be an array of strings.")

    return payload


def run(agent_input: AgentInput, llm_client: LLMClient | None = None) -> AgentOutput:
    client = llm_client or LLMClient()
    try:
        item = _validate_item(
            client.generate_json(
                system_prompt=TRIAGE_PROMPT,
                user_prompt=agent_input.raw_content,
                temperature=0,
            )
        )
        return AgentOutput(
            agent="triage_agent",
            status="success",
            items=[item],
            errors=[],
            confidence_notes="Routing classification completed from raw content with lightweight triage metadata.",
        )
    except Exception as exc:
        return AgentOutput(
            agent="triage_agent",
            status="error",
            items=[],
            errors=[str(exc)],
            confidence_notes="Triage classification failed.",
        )
