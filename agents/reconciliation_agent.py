from __future__ import annotations

import json
from typing import Any

from core.llm import LLMClient


RECONCILIATION_PROMPT = """You are Sophie’s memory editor for Cortex.

Cortex is a trusted memory system for a life-aware AI companion. Your job is to keep memory clean, useful, non-duplicative, and safe.

You will receive:
- new_candidates: pending candidate memories extracted from raw source material
- existing_facts: up to 10 relevant confirmed facts already stored for the same user

For each candidate, decide what should happen:

CREATE:
Use when the candidate is genuinely new, useful, sufficiently evidenced, and safe to store.
- Use CREATE even if an existing fact exists IF the new candidate is a CONTESTED claim (e.g., Speaker B disagrees with Speaker A about the same subject). Do not flatten disagreements into a single "truth" yet.

MERGE:
Use when the candidate is the same underlying memory as an existing fact and should reinforce it.
- Only MERGE if claimed_by_entity_id and subject_entity_id are identical or compatible (e.g., reinforcing the same speaker's previous claim).
- Do not merge merely because the same person, project, or topic is mentioned.

UPDATE:
Use when the candidate changes, corrects, or meaningfully refines an existing fact.
- Use when the same speaker corrects their OWN previous claim (superseding).
- Use when the User confirms an Assistant 'interpretation' candidate (this upgrades the assistant's interpretation to a confirmed direct claim).

DISMISS:
Use when the candidate is duplicate noise, operational clutter, invalid, too weak, unsafe, stale, or not worth storing.

Rules:
- Do not access any database.
- Do not invent candidate_ids or target_ids.
- Only use candidate_ids provided in new_candidates.
- Only use target_ids provided in existing_facts.
- Preserve evidence and companion_category meaning when relevant.
- Do not flatten sensitive boundaries, avoid topics, or communication preferences into generic memories.
- Sensitive inferred memories require stronger evidence.
- Explicit user-stated preferences and boundaries are higher authority than inference.
- Explicit user-stated boundaries should not be casually dismissed.
- State candidates are provisional and should not be merged aggressively.
- Return valid JSON only.

Return a JSON object with one key:
{
  "items": [
    {
      "candidate_id": "UUID from new_candidates",
      "instruction": "CREATE|MERGE|UPDATE|DISMISS",
      "target_id": "UUID from existing_facts if MERGE or UPDATE, otherwise null",
      "confidence_delta": number between -1.0 and 1.0,
      "reason": "one concise sentence"
    }
  ]
}"""

ALLOWED_INSTRUCTIONS = {"CREATE", "MERGE", "UPDATE", "DISMISS"}
EXPECTED_KEYS = {"candidate_id", "instruction", "target_id", "confidence_delta", "reason"}


def _validate_instruction(
    payload: Any,
    *,
    allowed_candidate_ids: set[str],
    allowed_target_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Reconciliation instruction must be a JSON object.")

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Reconciliation instruction missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Reconciliation instruction has unexpected keys: {sorted(extra)}")

    candidate_id = payload["candidate_id"]
    if not isinstance(candidate_id, str) or candidate_id not in allowed_candidate_ids:
        raise ValueError("Reconciliation candidate_id is invalid or unknown.")

    instruction = payload["instruction"]
    if instruction not in ALLOWED_INSTRUCTIONS:
        raise ValueError("Reconciliation instruction is invalid.")

    target_id = payload["target_id"]
    if instruction in {"MERGE", "UPDATE"}:
        if not isinstance(target_id, str) or target_id not in allowed_target_ids:
            raise ValueError("Reconciliation target_id is invalid or unknown.")
    elif target_id is not None:
        raise ValueError("Reconciliation target_id must be null for CREATE or DISMISS.")

    reason = payload["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Reconciliation reason must be a non-empty string.")

    confidence_delta = payload["confidence_delta"]
    if not isinstance(confidence_delta, (int, float)) or not -1 <= float(confidence_delta) <= 1:
        raise ValueError("Reconciliation confidence_delta must be between -1 and 1.")

    payload["confidence_delta"] = float(confidence_delta)
    return payload


def validate_instructions(
    items: Any,
    *,
    candidate_ids: list[str],
    target_ids: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError("Reconciliation agent response must include an items array.")

    allowed_candidate_ids = set(candidate_ids)
    allowed_target_ids = set(target_ids)
    instructions = [
        _validate_instruction(
            item,
            allowed_candidate_ids=allowed_candidate_ids,
            allowed_target_ids=allowed_target_ids,
        )
        for item in items
    ]

    seen_ids = {item["candidate_id"] for item in instructions}
    missing_ids = allowed_candidate_ids - seen_ids
    if missing_ids:
        raise ValueError(f"Missing reconciliation instructions for candidates: {sorted(missing_ids)}")
    return instructions


def run(
    *,
    new_candidates: list[dict[str, Any]],
    existing_facts: list[dict[str, Any]],
    llm_client: LLMClient | None = None,
) -> list[dict[str, Any]]:
    client = llm_client or LLMClient()
    candidate_ids = [str(candidate["id"]) for candidate in new_candidates]
    target_ids = [str(fact["id"]) for fact in existing_facts]
    payload = client.generate_json(
        system_prompt=RECONCILIATION_PROMPT,
        user_prompt=json.dumps(
            {"new_candidates": new_candidates, "existing_facts": existing_facts},
            default=str,
        ),
        temperature=0.1,
    )
    return validate_instructions(
        payload.get("items"),
        candidate_ids=candidate_ids,
        target_ids=target_ids,
    )
