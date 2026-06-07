from __future__ import annotations

from typing import Any

from agent_contract import AgentInput, AgentOutput
from core.llm import LLMClient


SESSION_SUMMARY_PROMPT = """You are reading a sealed chat transcript. Return a JSON object with exactly these keys:
summary: plain-English summary under 120 words
tags: array using only these tags: stress, planning, relationship, urgent, health, work, personal, celebration, conflict
open_items: array of unresolved items
key_decisions: array of decisions clearly made
emotional_tone: one of happy, stressed, neutral, anxious, energised

Rules:
- Use only the raw transcript provided.
- This is a compact searchable recap, not therapy, not literary writing, and not an extraction pass.
- Do not extract task candidates, event candidates, durable facts, or thread objects.
- Keep nuance, but stay concise and concrete.
- Do not speculate or over-interpret motives, personality, diagnoses, or subtext beyond what is clearly present.
- If there are no clear unresolved items, return an empty array.
- If there are no clear decisions, return an empty array.
- Prefer a few high-signal tags over many weak ones.
- The summary should say what happened, what mattered, and what remains unresolved if anything.
- Return only valid JSON with those exact keys."""

ALLOWED_TAGS = {
    "stress",
    "planning",
    "relationship",
    "urgent",
    "health",
    "work",
    "personal",
    "celebration",
    "conflict",
}
ALLOWED_TONES = {"happy", "stressed", "neutral", "anxious", "energised"}
EXPECTED_KEYS = {"summary", "tags", "open_items", "key_decisions", "emotional_tone"}


def _normalize_object_array(value: Any, field_name: str, string_key: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"Session summary field {field_name} must be an array.")

    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(item)
            continue
        if isinstance(item, str) and item.strip():
            normalized.append({string_key: item.strip()})
            continue
        raise ValueError(f"Session summary field {field_name} must be an array of objects.")
    return normalized


def _validate_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Session summary response must be a JSON object.")

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Session summary missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Session summary has unexpected keys: {sorted(extra)}")

    summary = payload["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Session summary field summary must be a non-empty string.")
    if len(summary.split()) >= 120:
        raise ValueError("Session summary must be under 120 words.")

    tags = payload["tags"]
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("Session summary tags must be an array of strings.")
    invalid_tags = [tag for tag in tags if tag not in ALLOWED_TAGS]
    if invalid_tags:
        raise ValueError(f"Session summary includes invalid tags: {invalid_tags}")

    payload["open_items"] = _normalize_object_array(payload["open_items"], "open_items", "item")
    payload["key_decisions"] = _normalize_object_array(
        payload["key_decisions"],
        "key_decisions",
        "decision",
    )

    if payload["emotional_tone"] not in ALLOWED_TONES:
        raise ValueError("Session summary emotional_tone is invalid.")

    return payload


def run(agent_input: AgentInput, llm_client: LLMClient | None = None) -> AgentOutput:
    client = llm_client or LLMClient()
    try:
        item = _validate_item(
            client.generate_json(
                system_prompt=SESSION_SUMMARY_PROMPT,
                user_prompt=agent_input.raw_content,
                temperature=0.2,
            )
        )
        return AgentOutput(
            agent="session_summary_agent",
            status="success",
            items=[item],
            errors=[],
            confidence_notes="Sealed chat transcript summarized into one searchable session item.",
        )
    except Exception as exc:
        return AgentOutput(
            agent="session_summary_agent",
            status="error",
            items=[],
            errors=[str(exc)],
            confidence_notes="Session summary generation failed.",
        )
