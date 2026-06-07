from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.item_utils import _to_iso
from core.operational import parse_datetime


def _thread_metadata(content: dict[str, Any]) -> dict[str, Any]:
    return content.setdefault("metadata", {})


def _set_thread_field(content: dict[str, Any], key: str, value: Any) -> None:
    metadata = _thread_metadata(content)
    if value is None:
        metadata.pop(key, None)
        return
    metadata[key] = value


def _thread_structured(row: dict[str, Any]) -> dict[str, Any]:
    return ((row.get("structured_content") or {}).get("thread") or {})


def _thread_snoozed(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    anchor = row.get("snoozed_until") or _thread_structured(row).get("snoozed_until")
    if not anchor:
        return False
    dt = parse_datetime(anchor) if isinstance(anchor, str) else (anchor.replace(tzinfo=timezone.utc) if isinstance(anchor, datetime) and anchor.tzinfo is None else anchor)
    if not dt:
        return False
    current = now or datetime.now(timezone.utc)
    return dt > current


def _normalize_links(links: dict[str, Any] | None) -> dict[str, list[str]]:
    payload = links or {}
    normalized: dict[str, list[str]] = {}
    for key in ("people", "projects", "topics", "related_facts", "related_threads"):
        values = payload.get(key, [])
        if not isinstance(values, list):
            values = []
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = str(value or "").strip()
            if not cleaned:
                continue
            token = cleaned.lower()
            if token in seen:
                continue
            seen.add(token)
            deduped.append(cleaned)
        normalized[key] = deduped
    return normalized


def _build_content(
    *,
    item_type: str,
    title: str,
    summary: str | None,
    due_at: str | None = None,
    priority: str | None = None,
    links: dict[str, Any] | None = None,
    source: str,
    requires_confirmation: bool,
    not_synced_external: bool = False,
    companion_category: str | None = None,
    open_loop_status: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    normalized_links = _normalize_links(links)
    summary_value = summary or title
    evidence = note or summary_value
    return {
        "schema_version": "v1",
        "item_type": item_type,
        "title": title,
        "summary": summary_value,
        "salience": priority,
        "priority": priority,
        "urgency": priority,
        "importance": priority,
        "sensitivity": "low",
        "time": {
            "due_date": due_at if item_type == "task" else None,
            "reminder_at": None,
            "date": due_at if item_type == "event" else None,
            "time": None,
            "duration": None,
            "follow_up_after_hours": 24 if item_type == "thread" else None,
            "stale_after_hours": None,
            "expires_at": None,
        },
        "links": normalized_links,
        "lifecycle": {
            "follow_up_after_hours": 24 if item_type == "thread" else None,
            "stale_after_hours": None,
            "expires_at": None,
        },
        "evidence": {
            "raw_evidence": evidence,
            "source_turn_refs": [],
        },
        "metadata": {
            "companion_category": companion_category,
            "internal_source": source,
            "requires_confirmation": requires_confirmation,
            "not_synced_external": not_synced_external,
            "item_status": "pending" if requires_confirmation else "active",
            "open_loop_status": open_loop_status,
            "agent_item": {
                "title": title,
                "summary": summary_value,
                "raw_evidence": evidence,
                "related_people": normalized_links["people"],
                "related_projects": normalized_links["projects"],
                "related_topics": normalized_links["topics"],
                "source": source,
                "requires_confirmation": requires_confirmation,
                "not_synced_external": not_synced_external,
            },
        },
    }


def _kind_for_row(row: dict[str, Any]) -> str:
    structured = row.get("structured_content") or {}
    kind = structured.get("kind")
    if kind:
        return str(kind)
    fact_type = row.get("fact_type") or row.get("candidate_type")
    content = row.get("content") or {}
    metadata = content.get("metadata") or {}
    agent_item = metadata.get("agent_item") or {}
    if agent_item.get("is_habit"):
        return "habit"
    if fact_type == "task" and (content.get("time") or {}).get("reminder_at") and not (content.get("time") or {}).get("due_date"):
        return "reminder"
    return str(fact_type or content.get("item_type") or "fact")


def _fact_item_status(fact: dict[str, Any]) -> str:
    if fact.get("status") == "dismissed":
        return "dismissed"
    if fact.get("status") == "stale":
        return "stale"
    if fact.get("status") == "historical":
        return "completed"
    return str((fact.get("content") or {}).get("metadata", {}).get("item_status") or "active")


def _candidate_item_status(candidate: dict[str, Any]) -> str:
    status = candidate.get("status")
    if status == "dismissed":
        return "dismissed"
    if status == "expired":
        return "stale"
    return "active"


def _canonical_item(
    *,
    source_kind: str,
    row: dict[str, Any],
    item_class: str,
) -> dict[str, Any]:
    content = row.get("content") or {}
    metadata = content.get("metadata") or {}
    structured = row.get("structured_content") or {}
    links = _normalize_links(content.get("links") or {})
    time_payload = content.get("time") or {}
    status = _fact_item_status(row) if source_kind == "confirmed_fact" else _candidate_item_status(row)
    kind = _kind_for_row(row)
    return {
        "id": str(row["id"]),
        "user_id": row["user_id"],
        "item_class": item_class,
        "item_kind": kind,
        "record_kind": source_kind,
        "status": status,
        "title": content.get("title"),
        "summary": content.get("summary"),
        "starts_at": row.get("starts_at") or time_payload.get("starts_at") or time_payload.get("date"),
        "ends_at": row.get("ends_at") or time_payload.get("ends_at"),
        "due_at": row.get("due_at") or time_payload.get("due_date") or time_payload.get("date"),
        "remind_at": row.get("remind_at") or time_payload.get("reminder_at"),
        "priority": row.get("priority") or content.get("priority") or content.get("importance") or content.get("salience"),
        "timezone": row.get("timezone") or (structured.get("temporal") or {}).get("timezone"),
        "recurrence_rule": row.get("recurrence_rule") or (structured.get("temporal") or {}).get("recurrence_rule"),
        "links": {
            "people": links["people"],
            "projects": links["projects"],
            "topics": links["topics"],
        },
        "requires_confirmation": bool(source_kind == "candidate" or metadata.get("requires_confirmation")),
        "not_synced_external": bool(metadata.get("not_synced_external", item_class == "event")),
        "source": metadata.get("internal_source") or "pipeline",
        "source_refs": [f"outbox:{value}" for value in row.get("source_ids", [])] if source_kind == "confirmed_fact" else [f"outbox:{row['source_id']}"],
        "confidence": float(row.get("confidence", 0.0)),
        "created_at": str(row.get("created_at") or row.get("first_seen_at") or ""),
        "updated_at": str(row.get("last_seen_at") or row.get("created_at") or row.get("first_seen_at") or ""),
        "structured_content": structured,
        "provenance": row.get("provenance") or {},
        "metadata": {
            "fact_type": row.get("fact_type"),
            "candidate_type": row.get("candidate_type"),
            "item_status": metadata.get("item_status"),
            "open_loop_status": metadata.get("open_loop_status"),
            "follow_up_needed": row.get("follow_up_needed", False),
            "thread_type": row.get("thread_type") or _thread_structured(row).get("thread_type"),
            "actionability": row.get("actionability") or _thread_structured(row).get("actionability"),
            "next_move": row.get("next_move") or _thread_structured(row).get("next_move"),
            "last_progressed_at": _to_iso(row.get("last_progressed_at") or _thread_structured(row).get("last_progressed_at")),
            "last_resurfaced_at": _to_iso(row.get("last_resurfaced_at") or _thread_structured(row).get("last_resurfaced_at")),
            "snoozed_until": _to_iso(row.get("snoozed_until") or _thread_structured(row).get("snoozed_until")),
        },
    }


def _filter_status(rows: list[dict[str, Any]], *, status: str, source_kind: str) -> list[dict[str, Any]]:
    if status == "all":
        return rows
    filtered = []
    for row in rows:
        value = _fact_item_status(row) if source_kind == "confirmed_fact" else _candidate_item_status(row)
        if value == status:
            filtered.append(row)
    return filtered


def _apply_item_updates(content: dict[str, Any], *, title: str | None, summary: str | None, due_at: str | None, priority: str | None) -> dict[str, Any]:
    updated = {**content}
    if title is not None:
        updated["title"] = title
    if summary is not None:
        updated["summary"] = summary
        updated.setdefault("evidence", {})["raw_evidence"] = summary
    if priority is not None:
        updated["priority"] = priority
        updated["importance"] = priority
        updated["salience"] = priority
        updated["urgency"] = priority
    if due_at is not None:
        updated.setdefault("time", {})
        if updated.get("item_type") == "event":
            updated["time"]["date"] = due_at
        else:
            updated["time"]["due_date"] = due_at
    return updated


def _event_type_for_completion(kind: str) -> str:
    if kind == "habit":
        return "habit_completed"
    if kind == "reminder":
        return "reminder_dismissed"
    if kind == "thread":
        return "thread_resolved"
    return "task_completed"


def _sophie_content(
    *,
    fact_type: str,
    title: str,
    notes: str | None,
    due_at: str | None,
    remind_at: str | None,
    starts_at: str | None,
    ends_at: str | None,
    timezone_name: str | None,
    location: str | None,
    participants: list[str] | None,
    source_type: str,
    provenance_summary: str | None,
    original_text: str | None,
    source_ref: str | None,
) -> dict[str, Any]:
    item_type = "event" if fact_type == "event" else "task"
    summary = notes or title
    return {
        "schema_version": "v1",
        "item_type": item_type,
        "title": title,
        "summary": summary,
        "salience": None,
        "priority": None,
        "urgency": None,
        "importance": None,
        "sensitivity": "low",
        "time": {
            "due_date": due_at if fact_type in {"task", "reminder"} else None,
            "reminder_at": remind_at,
            "date": starts_at if fact_type == "event" else None,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "timezone": timezone_name,
            "duration": None,
            "follow_up_after_hours": None,
            "stale_after_hours": None,
            "expires_at": None,
        },
        "links": {
            "people": participants or [],
            "projects": [location] if location else [],
            "topics": [],
            "related_facts": [],
            "related_threads": [],
        },
        "lifecycle": {
            "follow_up_after_hours": None,
            "stale_after_hours": None,
            "expires_at": None,
        },
        "evidence": {
            "raw_evidence": original_text or provenance_summary or summary,
            "source_turn_refs": [source_ref] if source_ref else [],
        },
        "metadata": {
            "internal_source": source_type,
            "requires_confirmation": False,
            "item_status": "active",
            "location": location,
            "participants": participants or [],
            "provenance_summary": provenance_summary,
            "source_ref": source_ref,
            "agent_item": {
                "title": title,
                "summary": summary,
                "location": location,
                "participants": participants or [],
                "raw_evidence": original_text or provenance_summary or summary,
            },
        },
    }


def _sophie_response(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content") or {}
    metadata = content.get("metadata") or {}
    return {
        "id": str(row["id"]),
        "kind": _kind_for_row(row),
        "type": row.get("fact_type"),
        "title": content.get("title"),
        "notes": content.get("summary"),
        "status": _fact_item_status(row),
        "dueAt": row.get("due_at").isoformat() if isinstance(row.get("due_at"), datetime) else row.get("due_at"),
        "remindAt": row.get("remind_at").isoformat() if isinstance(row.get("remind_at"), datetime) else row.get("remind_at"),
        "startsAt": row.get("starts_at").isoformat() if isinstance(row.get("starts_at"), datetime) else row.get("starts_at"),
        "endsAt": row.get("ends_at").isoformat() if isinstance(row.get("ends_at"), datetime) else row.get("ends_at"),
        "timezone": row.get("timezone"),
        "createdAt": str(row.get("first_seen_at") or row.get("created_at") or ""),
        "updatedAt": str(row.get("last_seen_at") or row.get("created_at") or ""),
        "location": metadata.get("location"),
        "participants": metadata.get("participants") or [],
    }


def _frontend_manual_response(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content") or {}
    metadata = content.get("metadata") or {}
    created_from = row.get("created_from") or {}
    return {
        "id": str(row["id"]),
        "kind": _kind_for_row(row),
        "type": row.get("fact_type"),
        "title": content.get("title"),
        "notes": content.get("summary"),
        "status": _fact_item_status(row),
        "dueAt": row.get("due_at").isoformat() if isinstance(row.get("due_at"), datetime) else row.get("due_at"),
        "remindAt": row.get("remind_at").isoformat() if isinstance(row.get("remind_at"), datetime) else row.get("remind_at"),
        "startsAt": row.get("starts_at").isoformat() if isinstance(row.get("starts_at"), datetime) else row.get("starts_at"),
        "endsAt": row.get("ends_at").isoformat() if isinstance(row.get("ends_at"), datetime) else row.get("ends_at"),
        "timezone": row.get("timezone"),
        "priority": row.get("priority"),
        "location": metadata.get("location"),
        "participants": metadata.get("participants") or [],
        "createdAt": str(row.get("first_seen_at") or row.get("created_at") or ""),
        "updatedAt": str(row.get("last_seen_at") or row.get("created_at") or ""),
        "sourceType": row.get("source_type"),
        "createdFrom": created_from.get("screen") if isinstance(created_from, dict) else created_from,
    }


def _manual_created_from(*, screen: str, tenant_id: str | None, idempotency_key: str | None, source_ref: str | None) -> dict[str, Any]:
    return {
        "writer": "frontend_manual",
        "screen": screen,
        "tenant_id": tenant_id,
        "idempotency_key": idempotency_key,
        "source_ref": source_ref,
    }


def _manual_action_content(
    *,
    fact_type: str,
    title: str,
    notes: str | None,
    due_at: str | None,
    remind_at: str | None,
    timezone_name: str | None,
    priority: str | None,
    source_type: str,
) -> dict[str, Any]:
    content = _sophie_content(
        fact_type=fact_type,
        title=title,
        notes=notes,
        due_at=due_at,
        remind_at=remind_at,
        starts_at=None,
        ends_at=None,
        timezone_name=timezone_name,
        location=None,
        participants=None,
        source_type=source_type,
        provenance_summary=None,
        original_text=notes,
        source_ref=None,
    )
    content["priority"] = priority
    content["importance"] = priority
    content["salience"] = priority
    content["urgency"] = priority
    return content


def _manual_event_content(
    *,
    title: str,
    notes: str | None,
    starts_at: str | None,
    ends_at: str | None,
    timezone_name: str | None,
    location: str | None,
    participants: list[str] | None,
    priority: str | None,
    source_type: str,
) -> dict[str, Any]:
    content = _sophie_content(
        fact_type="event",
        title=title,
        notes=notes,
        due_at=None,
        remind_at=None,
        starts_at=starts_at,
        ends_at=ends_at,
        timezone_name=timezone_name,
        location=location,
        participants=participants,
        source_type=source_type,
        provenance_summary=None,
        original_text=notes,
        source_ref=None,
    )
    content["priority"] = priority
    content["importance"] = priority
    content["salience"] = priority
    content["urgency"] = priority
    return content


def _manual_habit_content(
    *,
    title: str,
    notes: str | None,
    timezone_name: str | None,
    priority: str | None,
    cadence: str | None,
    source_type: str,
) -> dict[str, Any]:
    content = _manual_action_content(
        fact_type="habit",
        title=title,
        notes=notes,
        due_at=None,
        remind_at=None,
        timezone_name=timezone_name,
        priority=priority,
        source_type=source_type,
    )
    content.setdefault("metadata", {})["agent_item"] = {
        **(content.get("metadata", {}).get("agent_item") or {}),
        "is_habit": True,
        "cadence": cadence,
        "recurrence": cadence,
    }
    content["time"]["recurrence_rule"] = cadence
    return content
