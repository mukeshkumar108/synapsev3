from __future__ import annotations

from datetime import timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import (
    _fetch_candidate_by_id,
    _fetch_candidates,
    _fetch_fact_by_id,
    _fetch_confirmed_facts,
    _fetch_fact_by_idempotency_key,
    _insert_candidate,
    _insert_confirmed_fact,
    _insert_outbox_reference,
    _insert_timeline_event,
    _update_candidate_record,
    _update_fact_record,
)
from core.operational import apply_lifecycle_timestamp
from core.item_shapes import (
    _apply_item_updates,
    _build_content,
    _canonical_item,
    _frontend_manual_response,
    _filter_status,
    _sophie_content,
    _sophie_response,
)
from core.item_utils import _now_naive, _refresh_operational_row, _uuid_from_ref


RefreshOperationalRow = Callable[..., dict[str, Any]]


async def list_events(
    database: Database,
    *,
    user_id: str,
    status: str,
    limit: int,
) -> dict[str, Any]:
    facts = _filter_status(
        await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["event"]),
        status="active" if status == "confirmed" else status,
        source_kind="confirmed_fact",
    )
    candidates = _filter_status(
        await _fetch_candidates(database, user_id=user_id, candidate_types=["event", "invitation"]),
        status="active" if status == "confirmed" else status,
        source_kind="candidate",
    )
    items = [
        *[_canonical_item(source_kind="confirmed_fact", row=row, item_class="event") for row in facts],
        *[_canonical_item(source_kind="candidate", row=row, item_class="event") for row in candidates],
    ]
    if status == "confirmed":
        items = [item for item in items if item["record_kind"] == "confirmed_fact"]
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"items": items[:limit]}


async def create_event(
    database: Database,
    *,
    user_id: str,
    title: str,
    summary: str,
    due_at: str | None,
    priority: str | None,
    links: dict[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    content = _build_content(
        item_type="event",
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
        links=links,
        source=source,
        requires_confirmation=True,
        not_synced_external=True,
    )
    outbox_id = await _insert_outbox_reference(
        database,
        user_id=user_id,
        source=source,
        raw_content=summary or title,
        metadata={"internal_source": source, "item_class": "event", "not_synced_external": True},
    )
    row = await _insert_candidate(
        database,
        user_id=user_id,
        source_id=outbox_id,
        candidate_type="event",
        content=content,
        confidence=0.99,
        needs_confirmation=True,
        source_type=source,
        created_from={"path": "create_event", "source": source},
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="fact_learned",
        timeline_type="calendar",
        title=title,
        summary=summary,
        source_id=outbox_id,
        confidence=0.99,
    )
    return _canonical_item(source_kind="candidate", row=row, item_class="event")


async def sophie_create_confirmed_event(
    database: Database,
    *,
    user_id: str,
    title: str,
    notes: str | None,
    starts_at: str | None,
    ends_at: str | None,
    timezone_name: str | None,
    location: str | None,
    participants: list[str] | None,
    source_type: str,
    provenance_summary: str | None,
    confidence: float,
    source_ref: str | None,
    idempotency_key: str,
    original_text: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    existing = await _fetch_fact_by_idempotency_key(database, user_id=user_id, idempotency_key=idempotency_key, writer="sophie_confirmed_action")
    if existing:
        return _sophie_response(existing)

    source_uuid = _uuid_from_ref(source_ref, fallback=idempotency_key)
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
        provenance_summary=provenance_summary,
        original_text=original_text,
        source_ref=source_ref,
    )
    row = await _insert_confirmed_fact(
        database,
        user_id=user_id,
        fact_type="event",
        domain="events",
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
            "writer_kind": "event",
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
            "source_ref": source_ref,
            "provenance_summary": provenance_summary,
        },
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="event_created",
        timeline_type="calendar",
        title=title,
        summary=notes or title,
        source_id=source_uuid,
        related_fact_ids=[row["id"]],
        confidence=confidence,
    )
    return _sophie_response(row)


async def sophie_patch_confirmed_event(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    title: str | None,
    notes: str | None,
    starts_at: str | None,
    ends_at: str | None,
    timezone_name: str | None,
    location: str | None,
    participants: list[str] | None,
    source_type: str,
    provenance_summary: str | None,
    source_ref: str | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "event":
        raise HTTPException(status_code=404, detail="Event not found.")
    created_from = fact.setdefault("created_from", {})
    if idempotency_key and created_from.get("last_mutation_idempotency_key") == idempotency_key:
        return _sophie_response(fact)
    if idempotency_key:
        created_from["last_mutation_idempotency_key"] = idempotency_key
    content = fact["content"]
    if title is not None:
        content["title"] = title
    if notes is not None:
        content["summary"] = notes
        content.setdefault("evidence", {})["raw_evidence"] = notes
    content.setdefault("time", {})
    if starts_at is not None:
        content["time"]["date"] = starts_at
        content["time"]["starts_at"] = starts_at
    if ends_at is not None:
        content["time"]["ends_at"] = ends_at
    if timezone_name is not None:
        content["time"]["timezone"] = timezone_name
    metadata = content.setdefault("metadata", {})
    if location is not None:
        metadata["location"] = location
    if participants is not None:
        metadata["participants"] = participants
        content.setdefault("links", {})["people"] = participants
    if provenance_summary is not None:
        metadata["provenance_summary"] = provenance_summary
    if source_ref is not None:
        metadata["source_ref"] = source_ref
    fact["content"] = content
    fact["status"] = "active"
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    fact["source_type"] = source_type
    _refresh_operational_row(fact, item_type="event", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="event_updated",
        timeline_type="calendar",
        title=fact["content"].get("title") or "Event updated",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return _sophie_response(fact)


async def sophie_cancel_confirmed_event(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "event":
        raise HTTPException(status_code=404, detail="Event not found.")
    created_from = fact.setdefault("created_from", {})
    if idempotency_key and created_from.get("last_mutation_idempotency_key") == idempotency_key:
        return _sophie_response(fact)
    if idempotency_key:
        created_from["last_mutation_idempotency_key"] = idempotency_key
    fact["status"] = "dismissed"
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    fact["content"].setdefault("metadata", {})["item_status"] = "cancelled"
    fact["content"] = apply_lifecycle_timestamp(
        fact["content"],
        cancelled_at=fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
    )
    _refresh_operational_row(fact, item_type="event", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="event_cancelled",
        timeline_type="calendar",
        title=fact["content"].get("title") or "Event cancelled",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return _sophie_response(fact)


async def get_event_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") != "event":
        raise HTTPException(status_code=404, detail="Event not found.")
    return _frontend_manual_response(row)


async def delete_event_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    manual_mutate_fact: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") != "event":
        raise HTTPException(status_code=404, detail="Event not found.")
    row["status"] = "dismissed"
    row["content"].setdefault("metadata", {})["item_status"] = "cancelled"
    row["content"] = apply_lifecycle_timestamp(row["content"], cancelled_at=_now_naive().replace(tzinfo=timezone.utc).isoformat())
    return await manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="event_cancelled",
    )


async def update_event(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    status: str,
    title: str | None,
    summary: str | None,
    due_at: str | None,
    priority: str | None,
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if fact and fact.get("fact_type") == "event":
        fact["content"] = _apply_item_updates(fact["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        fact["last_seen_at"] = _now_naive()
        fact["last_confirmed_at"] = fact["last_seen_at"]
        if status == "dismissed":
            fact["status"] = "dismissed"
            fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
            event_type = "item_dismissed"
        else:
            fact["status"] = "active"
            fact["content"].setdefault("metadata", {})["item_status"] = "active"
            event_type = "event_confirmed"
        await _update_fact_record(database, fact)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type=event_type,
            timeline_type="calendar",
            title=fact["content"].get("title") or "Event updated",
            summary=fact["content"].get("summary") or "",
            source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
            related_fact_ids=[fact["id"]],
            confidence=fact["confidence"],
        )
        return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="event")

    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=item_id)
    if candidate and candidate.get("candidate_type") in {"event", "invitation"}:
        candidate["content"] = _apply_item_updates(candidate["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        candidate["raw_evidence"] = candidate["content"]["evidence"]["raw_evidence"]
        if status == "dismissed":
            candidate["status"] = "dismissed"
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="item_dismissed",
                timeline_type="calendar",
                title=candidate["content"].get("title") or "Event dismissed",
                summary=candidate["content"].get("summary") or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class="event")
        if status == "confirmed":
            fact_row = await _insert_confirmed_fact(
                database,
                user_id=candidate["user_id"],
                fact_type="event",
                domain="events",
                content=candidate["content"],
                confidence=candidate["confidence"],
                source_ids=[candidate["source_id"]],
                status="active",
                source_type=candidate.get("source_type", "chat"),
                who_said_it=candidate.get("who_said_it", "user"),
                channel=candidate.get("channel"),
                conversation_id=candidate.get("conversation_id"),
                created_from=candidate.get("created_from"),
            )
            candidate["status"] = "confirmed"
            await _update_candidate_record(database, candidate)
            fact_row["content"].setdefault("metadata", {})["item_status"] = "active"
            fact_row["content"]["metadata"]["not_synced_external"] = True
            await _update_fact_record(database, fact_row)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="event_confirmed",
                timeline_type="calendar",
                title=fact_row["content"].get("title") or "Event confirmed",
                summary=fact_row["content"].get("summary") or "",
                source_id=candidate["source_id"],
                related_fact_ids=[fact_row["id"]],
                confidence=fact_row["confidence"],
            )
            return _canonical_item(source_kind="confirmed_fact", row=fact_row, item_class="event")
        candidate["status"] = "pending"
        await _update_candidate_record(database, candidate)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type="fact_learned",
            timeline_type="calendar",
            title=candidate["content"].get("title") or "Event updated",
            summary=candidate["content"].get("summary") or "",
            source_id=candidate["source_id"],
            confidence=candidate["confidence"],
        )
        return _canonical_item(source_kind="candidate", row=candidate, item_class="event")
    raise HTTPException(status_code=404, detail="Event not found.")
