from __future__ import annotations

from datetime import timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import (
    _fetch_fact_by_id,
    _fetch_fact_by_idempotency_key,
    _insert_confirmed_fact,
    _insert_timeline_event,
    _update_fact_record,
)
from core.item_shapes import _sophie_content, _sophie_response
from core.item_utils import _now_naive, _refresh_operational_row, _uuid_from_ref
from core.operational import apply_lifecycle_timestamp


async def sophie_create_confirmed_action(
    database: Database,
    *,
    user_id: str,
    kind: str,
    title: str,
    notes: str | None,
    due_at: str | None,
    remind_at: str | None,
    timezone_name: str | None,
    source_type: str,
    provenance_summary: str | None,
    confidence: float,
    source_ref: str | None,
    idempotency_key: str,
    original_text: str | None = None,
    participants: list[str] | None = None,
    location: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    existing = await _fetch_fact_by_idempotency_key(database, user_id=user_id, idempotency_key=idempotency_key, writer="sophie_confirmed_action")
    if existing:
        return _sophie_response(existing)

    fact_type = "reminder" if kind == "reminder" else "task"
    source_uuid = _uuid_from_ref(source_ref, fallback=idempotency_key)
    content = _sophie_content(
        fact_type=fact_type,
        title=title,
        notes=notes,
        due_at=due_at,
        remind_at=remind_at,
        starts_at=None,
        ends_at=None,
        timezone_name=timezone_name,
        location=location,
        participants=participants,
        source_type=source_type,
        provenance_summary=provenance_summary,
        original_text=original_text,
        source_ref=source_ref,
    )
    row = await _insert_confirmed_fact(
        database,
        user_id=user_id,
        fact_type=fact_type,
        domain="obligations",
        content=content,
        confidence=confidence,
        source_ids=[source_uuid],
        status="active",
        source_type=source_type,
        who_said_it="user",
        channel=source_type,
        created_from={
            "writer": "sophie_confirmed_action",
            "mode": "confirmed_write",
            "writer_kind": kind,
            "tenant_id": tenant_id,
            "source_ref": source_ref,
            "idempotency_key": idempotency_key,
            "provenance_summary": provenance_summary,
        },
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="reminder_created" if fact_type == "reminder" else "task_created",
        timeline_type="user_life",
        title=title,
        summary=notes or title,
        source_id=source_uuid,
        related_fact_ids=[row["id"]],
        confidence=confidence,
    )
    return _sophie_response(row)


async def sophie_patch_confirmed_action(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    title: str | None,
    notes: str | None,
    due_at: str | None,
    remind_at: str | None,
    timezone_name: str | None,
    source_type: str,
    provenance_summary: str | None,
    source_ref: str | None,
    idempotency_key: str | None,
    status: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") not in {"task", "reminder"}:
        raise HTTPException(status_code=404, detail="Action not found.")
    if idempotency_key:
        created_from = fact.setdefault("created_from", {})
        if created_from.get("last_mutation_idempotency_key") == idempotency_key:
            return _sophie_response(fact)
        created_from["last_mutation_idempotency_key"] = idempotency_key
    content = fact["content"]
    if title is not None:
        content["title"] = title
    if notes is not None:
        content["summary"] = notes
        content.setdefault("evidence", {})["raw_evidence"] = notes
    content.setdefault("time", {})
    if due_at is not None:
        content["time"]["due_date"] = due_at
    if remind_at is not None:
        content["time"]["reminder_at"] = remind_at
    if timezone_name is not None:
        content["time"]["timezone"] = timezone_name
    if provenance_summary is not None:
        content.setdefault("metadata", {})["provenance_summary"] = provenance_summary
    if source_ref is not None:
        content.setdefault("metadata", {})["source_ref"] = source_ref
    fact["content"] = content
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    timeline_event = None
    if fact["fact_type"] == "task" and (status == "completed" or completed_at):
        fact["status"] = "historical"
        fact["content"].setdefault("metadata", {})["item_status"] = "completed"
        fact["content"] = apply_lifecycle_timestamp(
            fact["content"],
            completed_at=completed_at or fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
        )
        timeline_event = "task_completed"
    elif fact["fact_type"] == "reminder" and status == "dismissed":
        fact["status"] = "dismissed"
        fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
        fact["content"] = apply_lifecycle_timestamp(
            fact["content"],
            cancelled_at=fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
        )
        timeline_event = "reminder_dismissed"
    else:
        fact["status"] = "active"
        fact["content"].setdefault("metadata", {})["item_status"] = "active"
    fact["source_type"] = source_type
    _refresh_operational_row(fact, item_type=fact["fact_type"], source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    if timeline_event:
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type=timeline_event,
            timeline_type="user_life",
            title=fact["content"].get("title") or "Action updated",
            summary=fact["content"].get("summary") or "",
            source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
            related_fact_ids=[fact["id"]],
            confidence=fact["confidence"],
        )
    return _sophie_response(fact)


async def sophie_delete_confirmed_action(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") not in {"task", "reminder"}:
        raise HTTPException(status_code=404, detail="Action not found.")
    created_from = fact.setdefault("created_from", {})
    if idempotency_key and created_from.get("last_mutation_idempotency_key") == idempotency_key:
        return _sophie_response(fact)
    if idempotency_key:
        created_from["last_mutation_idempotency_key"] = idempotency_key
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    if fact["fact_type"] == "reminder":
        fact["status"] = "dismissed"
        fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
        fact["content"] = apply_lifecycle_timestamp(
            fact["content"],
            cancelled_at=fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
        )
        event_type = "reminder_dismissed"
    else:
        fact["status"] = "historical"
        fact["content"].setdefault("metadata", {})["item_status"] = "archived"
        event_type = "task_archived"
    _refresh_operational_row(fact, item_type=fact["fact_type"], source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type=event_type,
        timeline_type="user_life",
        title=fact["content"].get("title") or "Action archived",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return _sophie_response(fact)
