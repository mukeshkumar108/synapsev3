from __future__ import annotations

from typing import Any

from agent_contract import AgentInput, AgentOutput
from core.llm import LLMClient


FACT_PROMPT = """You are a Provenance-Aware Extraction Agent extracting durable facts, preferences, and identities.

Input Metadata:
{{PARTICIPANTS}}
Interaction Mode: {{MODE}}

Return a JSON object with one key:
- items: array of fact objects

Each fact object must include:
- subject: user or named person/entity
- fact_type: preference|trait|relationship|background|constraint
- content: plain-English fact statement
- companion_category: win|accomplishment|hope|aspiration|fear|inside_joke|comfort_preference|communication_preference|tone_preference|encouragement_style|personal_value|sensitivity_boundary|avoid_topic|meaningful_routine|important_person|relationship_context|null
- about_user: boolean
- person_name: name if about someone else, otherwise null
- related_people: array of names
- related_projects: array of projects/topics
- salience: high|medium|low
- sensitivity: low|medium|high
- needs_confirmation: boolean
- claimed_by_entity_id: ID of the participant who made the claim
- subject_entity_id: ID of the participant the fact is about (if applicable, otherwise 'world' or 'user')
- claim_type: direct|reported|inferred|interpretation
- evidence_turn_index: integer index of the [Turn X] where this was said
- raw_evidence: exact quote from the source
- confidence: number from 0.0 to 1.0

Rules:
- claimed_by_entity_id: The ID of the participant speaking in the [Turn X].
- subject_entity_id: The ID of the participant the fact is about. Default to 'user' if it's a general user fact.
- claim_type:
  - 'direct': Speaker asserts something about themselves or the world.
  - 'reported': Speaker reports what someone else said ("Ashley told me she's tired").
  - 'interpretation': Assistant proposes a meaning ("You seem stressed").
- MODE RULES:
  - real_life mode: Treat Sophie's claims as 'interpretation'. Do NOT store as truth unless the User confirms it in a later turn.
  - fictional_rp mode: Treat Sophie's claims as 'direct' (Canon). They are world-state truth.
- Extract only durable facts, preferences, identity details, and relationships.
- Do not extract temporary mood or short-lived context.
- Good fact examples:
  - [Turn 2] User: "I am vegetarian." -> claimed_by: user, subject_entity_id: user, claim_type: direct
  - [Turn 5] User: "Nina said she's moving." -> claimed_by: user, subject_entity_id: nina, claim_type: reported
- Prefer clear evidence over inference.
- Return an empty array if there are no durable fact candidates.
- Return valid JSON only."""

ALLOWED_FACT_TYPES = {"preference", "trait", "relationship", "background", "constraint"}
ALLOWED_CLAIM_TYPES = {"direct", "reported", "inferred", "interpretation"}
ALLOWED_LEVELS = {"high", "medium", "low"}
ALLOWED_COMPANION_CATEGORIES = {
    "win",
    "accomplishment",
    "hope",
    "aspiration",
    "fear",
    "inside_joke",
    "comfort_preference",
    "communication_preference",
    "tone_preference",
    "encouragement_style",
    "personal_value",
    "sensitivity_boundary",
    "avoid_topic",
    "meaningful_routine",
    "important_person",
    "relationship_context",
    None,
}
COMPANION_FACT_TYPE_NORMALIZATION = {
    "communication_preference": "preference",
    "tone_preference": "preference",
    "comfort_preference": "preference",
    "encouragement_style": "preference",
    "inside_joke": "preference",
    "meaningful_routine": "preference",
    "personal_value": "trait",
    "aspiration": "background",
    "hope": "background",
    "fear": "background",
    "avoid_topic": "constraint",
    "sensitivity_boundary": "constraint",
    "important_person": "relationship",
    "relationship_context": "relationship",
    "win": "background",
    "accomplishment": "background",
}
EXPECTED_KEYS = {
    "subject",
    "fact_type",
    "content",
    "companion_category",
    "about_user",
    "person_name",
    "related_people",
    "related_projects",
    "salience",
    "sensitivity",
    "needs_confirmation",
    "claimed_by_entity_id",
    "subject_entity_id",
    "claim_type",
    "evidence_turn_index",
    "raw_evidence",
    "confidence",
}


def _normalize_fact_type(payload: dict[str, Any]) -> dict[str, Any]:
    fact_type = payload.get("fact_type")
    companion_category = payload.get("companion_category")

    if (
        companion_category in COMPANION_FACT_TYPE_NORMALIZATION
        and fact_type not in ALLOWED_FACT_TYPES
    ):
        payload["fact_type"] = COMPANION_FACT_TYPE_NORMALIZATION[companion_category]
        return payload

    if fact_type in COMPANION_FACT_TYPE_NORMALIZATION:
        if companion_category is None:
            payload["companion_category"] = fact_type
        payload["fact_type"] = COMPANION_FACT_TYPE_NORMALIZATION[fact_type]
        return payload

    return payload


def _validate_item(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Fact candidate must be a JSON object.")

    payload = _normalize_fact_type(payload)

    missing = EXPECTED_KEYS - set(payload)
    extra = set(payload) - EXPECTED_KEYS
    if missing:
        raise ValueError(f"Fact candidate missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"Fact candidate has unexpected keys: {sorted(extra)}")

    for key in (
        "subject",
        "content",
        "raw_evidence",
        "claimed_by_entity_id",
        "subject_entity_id",
    ):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValueError(f"Fact field {key} must be a non-empty string.")

    if payload["fact_type"] not in ALLOWED_FACT_TYPES:
        raise ValueError(f"Fact fact_type is invalid: {payload['fact_type']}")
    if payload["claim_type"] not in ALLOWED_CLAIM_TYPES:
        raise ValueError(f"Fact claim_type is invalid: {payload['claim_type']}")
    if payload["companion_category"] not in ALLOWED_COMPANION_CATEGORIES:
        raise ValueError("Fact companion_category is invalid.")
    if not isinstance(payload["about_user"], bool):
        raise ValueError("Fact about_user must be a boolean.")
    if not isinstance(payload["needs_confirmation"], bool):
        raise ValueError("Fact needs_confirmation must be a boolean.")
    if not isinstance(payload["evidence_turn_index"], int):
        raise ValueError("Fact evidence_turn_index must be an integer.")

    if payload["person_name"] is not None and not isinstance(payload["person_name"], str):
        raise ValueError("Fact person_name must be a string or null.")

    for key in ("related_people", "related_projects"):
        value = payload[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Fact field {key} must be an array of strings.")

    for key in ("salience", "sensitivity"):
        if payload[key] not in ALLOWED_LEVELS:
            raise ValueError(f"Fact field {key} must be one of high, medium, low.")

    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("Fact confidence must be a number between 0 and 1.")
    payload["confidence"] = float(confidence)

    return payload


def run(agent_input: AgentInput, llm_client: LLMClient | None = None) -> AgentOutput:
    client = llm_client or LLMClient()

    participants_text = "Participants:\n" + "\n".join(
        [f"- {p.id}: {p.name} ({p.role})" for p in agent_input.participants]
    )
    system_prompt = FACT_PROMPT.replace("{{PARTICIPANTS}}", participants_text).replace(
        "{{MODE}}", agent_input.interaction_mode
    )

    try:
        payload = client.generate_json(
            system_prompt=system_prompt,
            user_prompt=agent_input.raw_content,
            temperature=0.1,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("Fact agent response must include an items array.")
        return AgentOutput(
            agent="fact_agent",
            status="success",
            items=[_validate_item(item) for item in items],
            errors=[],
            confidence_notes="Durable fact extraction completed with provenance-aware judgment.",
        )
    except Exception as exc:
        return AgentOutput(
            agent="fact_agent",
            status="error",
            items=[],
            errors=[str(exc)],
            confidence_notes="Fact extraction failed.",
        )
