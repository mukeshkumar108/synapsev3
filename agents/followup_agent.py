from __future__ import annotations

import json
from typing import Any

from core.llm import LLMClient


FOLLOWUP_PROMPT = """You are Sophie’s proactive follow-up planner.

Your job is to decide whether Sophie should proactively check in right now.

You are not chatting with the user directly yet.
You are selecting the best follow-up move for this moment.

You will receive:
- candidate follow-up items that are already due and policy-approved
- current_datetime
- timezone
- recent_user_activity
- policy_context

Return a JSON object with exactly these keys:
- decision
- selected_thread_ids
- rationale
- message
- defer_hours
- bundle_strategy
- sensitivity

Allowed values:
- decision: send_now | defer | suppress
- bundle_strategy: single | bundle | rollover
- sensitivity: low | medium | high

Rules:
- Prefer one focused check-in unless bundling clearly helps the user.
- Do not select more than 2 thread ids.
- If the user was recently active or the timing feels intrusive, prefer defer or suppress.
- Health/symptom and care situations can justify send_now.
- Avoid sounding needy, clingy, or spammy.
- Do not invent facts.
- Return valid JSON only."""

EXPECTED_KEYS = {
    "decision",
    "selected_thread_ids",
    "rationale",
    "message",
    "defer_hours",
    "bundle_strategy",
    "sensitivity",
}
ALLOWED_DECISIONS = {"send_now", "defer", "suppress"}
ALLOWED_STRATEGIES = {"single", "bundle", "rollover"}
ALLOWED_SENSITIVITY = {"low", "medium", "high"}


def validate_output(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Follow-up response must be a JSON object.")
    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Follow-up response missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Follow-up response has unexpected keys: {sorted(extra)}")
    if payload["decision"] not in ALLOWED_DECISIONS:
        raise ValueError("Follow-up decision is invalid.")
    if payload["bundle_strategy"] not in ALLOWED_STRATEGIES:
        raise ValueError("Follow-up bundle_strategy is invalid.")
    if payload["sensitivity"] not in ALLOWED_SENSITIVITY:
        raise ValueError("Follow-up sensitivity is invalid.")
    if not isinstance(payload["selected_thread_ids"], list) or not all(isinstance(item, str) for item in payload["selected_thread_ids"]):
        raise ValueError("Follow-up selected_thread_ids must be an array of strings.")
    if len(payload["selected_thread_ids"]) > 2:
        raise ValueError("Follow-up may select at most 2 thread ids.")
    for key in ("rationale", "message"):
        if not isinstance(payload[key], str):
            raise ValueError(f"Follow-up field {key} must be a string.")
    if payload["decision"] == "send_now":
        if not payload["selected_thread_ids"]:
            raise ValueError("send_now requires at least one selected thread id.")
        if not payload["message"].strip():
            raise ValueError("send_now requires a non-empty message.")
    if payload["decision"] in {"defer", "suppress"} and payload["selected_thread_ids"] and payload["bundle_strategy"] == "single":
        pass
    defer_hours = payload["defer_hours"]
    if defer_hours is not None:
        if not isinstance(defer_hours, int) or defer_hours <= 0:
            raise ValueError("Follow-up defer_hours must be a positive integer or null.")
    return payload


def run(
    *,
    candidates: list[dict[str, Any]],
    current_datetime: str,
    timezone: str,
    recent_user_activity: str | None,
    policy_context: dict[str, Any] | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    client = llm_client or LLMClient()
    payload = client.generate_json(
        system_prompt=FOLLOWUP_PROMPT,
        user_prompt=json.dumps(
            {
                "candidates": candidates,
                "current_datetime": current_datetime,
                "timezone": timezone,
                "recent_user_activity": recent_user_activity,
                "policy_context": policy_context or {},
            },
            default=str,
        ),
        temperature=0.2,
    )
    return validate_output(payload)
