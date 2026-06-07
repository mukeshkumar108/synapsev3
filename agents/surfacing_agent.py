from __future__ import annotations

import json
from typing import Any

from core.llm import LLMClient


SURFACING_PROMPT = """You are Sophie’s chief of staff.

Your job is to decide what Sophie should be aware of right now before talking to the user.

You are not writing Sophie’s response.
You are preparing a briefing and calibration packet for Sophie runtime.

You will receive:
- confirmed_facts: relevant active facts
- tasks: open obligations
- events: upcoming events
- state: current state facts
- threads: active open loops
- recent_timeline: recent timeline events
- time_of_day
- current_datetime
- timezone

Return a JSON object with exactly these keys:
- session_instructions
- relevant_topics
- worth_attention
- suggested_focus
- tone_note
- avoid
- stale_warnings

worth_attention must be an array of at most 3 objects.
Each worth_attention object must include:
- title
- why_it_matters
- suggested_way_to_raise
- sensitivity: low|medium|high
- source_fact_ids: array of confirmed_facts UUID strings

Rules:
- Give Sophie only the most relevant 2-3 things.
- Do not overwhelm the brief.
- Do not include dismissed, corrected, expired, or stale memories as current.
- Do not surface avoid_topic items as topics to raise. Put them in avoid.
- High-sensitivity memories require restraint.
- Communication preferences should calibrate tone_note and session_instructions, not become topics to raise.
- Inside jokes should only surface if low sensitivity and clearly relevant; otherwise keep them as background.
- Distinguish practical support from emotional support.
- Preserve companion_category meaning when relevant.
- Do not invent facts.
- Return valid JSON only."""

ALLOWED_LEVELS = {"high", "medium", "low"}
EXPECTED_KEYS = {
    "session_instructions",
    "relevant_topics",
    "worth_attention",
    "suggested_focus",
    "tone_note",
    "avoid",
    "stale_warnings",
}
WORTH_ATTENTION_KEYS = {
    "title",
    "why_it_matters",
    "suggested_way_to_raise",
    "sensitivity",
    "source_fact_ids",
}


def _validate_worth_attention_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("worth_attention item must be a JSON object.")
    missing = WORTH_ATTENTION_KEYS - set(payload)
    extra = set(payload) - WORTH_ATTENTION_KEYS
    if missing:
        raise ValueError(f"worth_attention item missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"worth_attention item has unexpected keys: {sorted(extra)}")

    for key in ("title", "why_it_matters", "suggested_way_to_raise"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValueError(f"worth_attention field {key} must be a non-empty string.")
    if payload["sensitivity"] not in ALLOWED_LEVELS:
        raise ValueError("worth_attention sensitivity is invalid.")
    if not isinstance(payload["source_fact_ids"], list) or not all(
        isinstance(item, str) for item in payload["source_fact_ids"]
    ):
        raise ValueError("worth_attention source_fact_ids must be an array of strings.")
    return payload


def validate_output(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Surfacing response must be a JSON object.")
    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Surfacing response missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Surfacing response has unexpected keys: {sorted(extra)}")

    for key in ("session_instructions", "suggested_focus", "tone_note"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValueError(f"Surfacing field {key} must be a non-empty string.")

    for key in ("relevant_topics", "avoid", "stale_warnings"):
        value = payload[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Surfacing field {key} must be an array of strings.")

    worth_attention = payload["worth_attention"]
    if not isinstance(worth_attention, list):
        raise ValueError("Surfacing worth_attention must be an array.")
    if len(worth_attention) > 3:
        raise ValueError("Surfacing worth_attention must contain at most 3 items.")
    payload["worth_attention"] = [_validate_worth_attention_item(item) for item in worth_attention]
    return payload


def run(
    *,
    confirmed_facts: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    state: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    recent_timeline: list[dict[str, Any]],
    time_of_day: str,
    current_datetime: str,
    timezone: str,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    client = llm_client or LLMClient()
    payload = client.generate_json(
        system_prompt=SURFACING_PROMPT,
        user_prompt=json.dumps(
            {
                "confirmed_facts": confirmed_facts,
                "tasks": tasks,
                "events": events,
                "state": state,
                "threads": threads,
                "recent_timeline": recent_timeline,
                "time_of_day": time_of_day,
                "current_datetime": current_datetime,
                "timezone": timezone,
            },
            default=str,
        ),
        temperature=0.2,
    )
    return validate_output(payload)
