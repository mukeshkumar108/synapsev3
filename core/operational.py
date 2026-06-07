from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def derive_kind(*, item_type: str | None, content: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    data = metadata or content.get("metadata") or {}
    agent_item = data.get("agent_item") or {}
    if agent_item.get("is_habit"):
        return "habit"
    time_payload = content.get("time") or {}
    if item_type == "task" and time_payload.get("reminder_at") and not time_payload.get("due_date"):
        return "reminder"
    return item_type or "fact"


def normalize_provenance(
    *,
    source_id: Any,
    source_type: str | None,
    original_text: str | None,
    who_said_it: str | None = None,
    channel: str | None = None,
    conversation_id: str | None = None,
    created_from: dict[str, Any] | None = None,
    source_ids: list[Any] | None = None,
) -> dict[str, Any]:
    cleaned_source_ids = [str(value) for value in (source_ids or []) if value]
    primary_source_id = str(source_id) if source_id is not None else (cleaned_source_ids[0] if cleaned_source_ids else None)
    return {
        "source_id": primary_source_id,
        "source_ids": cleaned_source_ids or ([primary_source_id] if primary_source_id else []),
        "source_type": source_type or "chat",
        "who_said_it": who_said_it or "user",
        "original_text": _clean_text(original_text),
        "channel": channel or source_type or "chat",
        "conversation_id": conversation_id,
        "created_from": deepcopy(created_from) if isinstance(created_from, dict) else {},
    }


def build_structured_content(
    *,
    item_type: str | None,
    content: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(content)
    metadata = payload.get("metadata") or {}
    time_payload = payload.get("time") or {}
    links = payload.get("links") or {}
    kind = derive_kind(item_type=item_type, content=payload, metadata=metadata)
    agent_item = metadata.get("agent_item") or {}
    title = payload.get("title")
    summary = payload.get("summary")
    recurrence_rule = agent_item.get("recurrence") or time_payload.get("recurrence_rule")
    cadence = agent_item.get("recurrence") or agent_item.get("cadence")
    follow_up_needed = bool(
        kind == "thread"
        or metadata.get("follow_up_needed")
        or metadata.get("open_loop_status") in {"active", "unresolved", "open"}
    )
    return {
        "kind": kind,
        "title": title,
        "summary": summary,
        "status": metadata.get("item_status"),
        "priority": payload.get("priority") or payload.get("importance") or payload.get("salience"),
        "temporal": {
            "starts_at": time_payload.get("starts_at") or time_payload.get("date"),
            "ends_at": time_payload.get("ends_at"),
            "due_at": time_payload.get("due_date"),
            "remind_at": time_payload.get("reminder_at"),
            "timezone": time_payload.get("timezone") or agent_item.get("timezone"),
            "recurrence_rule": recurrence_rule,
        },
        "habit": {
            "cadence": cadence,
            "target_value": agent_item.get("target_value"),
            "target_unit": agent_item.get("target_unit"),
        }
        if kind == "habit"
        else None,
        "thread": {
            "follow_up_needed": follow_up_needed,
            "thread_type": metadata.get("thread_type") or agent_item.get("thread_type"),
            "actionability": metadata.get("actionability") or agent_item.get("actionability"),
            "next_move": metadata.get("next_move") or agent_item.get("next_move"),
            "waiting_on": metadata.get("waiting_on") or agent_item.get("waiting_on"),
            "open_loop_status": metadata.get("open_loop_status") or agent_item.get("open_loop_status") or "active",
            "suggested_actions": metadata.get("suggested_actions") or agent_item.get("suggested_actions") or [],
            "blocked_by": metadata.get("blocked_by") or agent_item.get("blocked_by"),
            "resolution_condition": metadata.get("resolution_condition") or agent_item.get("resolution_condition"),
            "resolution_summary": metadata.get("resolution_summary") or agent_item.get("resolution_summary"),
            "surface_reason": metadata.get("surface_reason") or agent_item.get("surface_reason"),
            "evidence": metadata.get("thread_evidence") or agent_item.get("thread_evidence") or {},
            "capability_assessment": metadata.get("capability_assessment") or agent_item.get("capability_assessment"),
            "last_progressed_at": metadata.get("last_progressed_at") or agent_item.get("last_progressed_at"),
            "last_resurfaced_at": metadata.get("last_resurfaced_at") or metadata.get("last_surfaced_at") or agent_item.get("last_resurfaced_at"),
            "snoozed_until": metadata.get("snoozed_until") or agent_item.get("snoozed_until"),
        }
        if kind == "thread"
        else None,
        "links": deepcopy(links),
        "provenance": deepcopy(provenance),
    }


def extract_operational_fields(
    *,
    item_type: str | None,
    content: dict[str, Any],
    provenance: dict[str, Any],
    record_status: str | None,
) -> dict[str, Any]:
    structured_content = build_structured_content(item_type=item_type, content=content, provenance=provenance)
    temporal = structured_content["temporal"]
    metadata = content.get("metadata") or {}
    return {
        "fact_type": item_type,
        "status": record_status,
        "starts_at": temporal.get("starts_at"),
        "ends_at": temporal.get("ends_at"),
        "due_at": temporal.get("due_at"),
        "remind_at": temporal.get("remind_at"),
        "timezone": temporal.get("timezone"),
        "recurrence_rule": temporal.get("recurrence_rule"),
        "completed_at": metadata.get("completed_at"),
        "cancelled_at": metadata.get("cancelled_at"),
        "priority": structured_content.get("priority"),
        "structured_content": structured_content,
        "provenance": deepcopy(provenance),
        "source_type": provenance.get("source_type"),
        "source_id": provenance.get("source_id"),
        "source_ids": provenance.get("source_ids") or [],
        "who_said_it": provenance.get("who_said_it"),
        "original_text": provenance.get("original_text"),
        "channel": provenance.get("channel"),
        "conversation_id": provenance.get("conversation_id"),
        "created_from": deepcopy(provenance.get("created_from") or {}),
        "follow_up_needed": bool((structured_content.get("thread") or {}).get("follow_up_needed")),
        "thread_type": (structured_content.get("thread") or {}).get("thread_type"),
        "actionability": (structured_content.get("thread") or {}).get("actionability"),
        "next_move": (structured_content.get("thread") or {}).get("next_move"),
        "last_progressed_at": (structured_content.get("thread") or {}).get("last_progressed_at"),
        "last_resurfaced_at": (structured_content.get("thread") or {}).get("last_resurfaced_at"),
        "snoozed_until": (structured_content.get("thread") or {}).get("snoozed_until"),
        "kind": structured_content.get("kind"),
    }


def apply_lifecycle_timestamp(content: dict[str, Any], *, completed_at: str | None = None, cancelled_at: str | None = None) -> dict[str, Any]:
    updated = deepcopy(content)
    metadata = updated.setdefault("metadata", {})
    if completed_at is not None:
        metadata["completed_at"] = completed_at
    if cancelled_at is not None:
        metadata["cancelled_at"] = cancelled_at
    return updated
