from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import (
    _fetch_confirmed_facts,
    _fetch_fact_by_id,
    _fetch_fact_by_idempotency_key,
    _fetch_fact_links_for_fact,
    _fetch_source_archive_by_user,
    _insert_confirmed_fact,
    _insert_timeline_event,
    _update_fact_record,
    _upsert_fact_link,
    _deactivate_fact_link,
)
from core.item_shapes import _manual_action_content, _manual_created_from, _set_thread_field, _thread_snoozed, _thread_structured
from core.item_utils import _to_iso, _uuid_from_ref


async def open_thread_rows(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    facts = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["thread"])
    items = []
    now = datetime.now(timezone.utc)
    for row in facts:
        if row.get("status") != "active":
            continue
        if not row.get("follow_up_needed", True):
            continue
        if _thread_snoozed(row, now=now):
            continue
        items.append(row)
    return items


async def resolve_thread_row(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    now_naive: Callable[[], datetime],
    refresh_operational_row: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    fact["status"] = "historical"
    fact["last_seen_at"] = now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    fact["content"].setdefault("metadata", {})["open_loop_status"] = "resolved"
    fact["content"].setdefault("metadata", {})["item_status"] = "completed"
    fact["follow_up_needed"] = False
    refresh_operational_row(fact, item_type="thread", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="thread_resolved",
        timeline_type="relationship",
        title=fact["content"].get("title") or "Thread resolved",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return fact


async def dismiss_thread_row(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    now_naive: Callable[[], datetime],
    refresh_operational_row: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    created_from = fact.setdefault("created_from", {})
    if idempotency_key and created_from.get("last_mutation_idempotency_key") == idempotency_key:
        return fact
    if idempotency_key:
        created_from["last_mutation_idempotency_key"] = idempotency_key
    created_from["writer"] = "frontend_manual"
    created_from["screen"] = screen
    created_from["source_ref"] = source_ref
    fact["status"] = "dismissed"
    fact["source_type"] = source_type
    fact["who_said_it"] = "user"
    fact["channel"] = source_type
    fact["last_seen_at"] = now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    _set_thread_field(fact["content"], "open_loop_status", "dismissed")
    fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
    fact["follow_up_needed"] = False
    _set_thread_field(fact["content"], "last_resurfaced_at", fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat())
    refresh_operational_row(fact, item_type="thread", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="thread_dismissed",
        timeline_type="relationship",
        title=fact["content"].get("title") or "Thread dismissed",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return fact


async def snooze_thread_row(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    snoozed_until: str,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    now_naive: Callable[[], datetime],
    refresh_operational_row: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    created_from = fact.setdefault("created_from", {})
    if idempotency_key and created_from.get("last_mutation_idempotency_key") == idempotency_key:
        return fact
    if idempotency_key:
        created_from["last_mutation_idempotency_key"] = idempotency_key
    created_from["writer"] = "frontend_manual"
    created_from["screen"] = screen
    created_from["source_ref"] = source_ref
    fact["status"] = "active"
    fact["source_type"] = source_type
    fact["who_said_it"] = "user"
    fact["channel"] = source_type
    fact["last_seen_at"] = now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    _set_thread_field(fact["content"], "open_loop_status", "active")
    _set_thread_field(fact["content"], "snoozed_until", snoozed_until)
    _set_thread_field(fact["content"], "last_resurfaced_at", fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat())
    fact["follow_up_needed"] = True
    refresh_operational_row(fact, item_type="thread", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="thread_snoozed",
        timeline_type="relationship",
        title=fact["content"].get("title") or "Thread snoozed",
        summary=f"Snoozed until {snoozed_until}",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return fact


async def convert_thread_to_fact_rows(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    target_fact_type: str,
    title: str | None,
    notes: str | None,
    due_at: str | None,
    remind_at: str | None,
    timezone_name: str | None,
    priority: str | None,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str,
    now_naive: Callable[[], datetime],
    refresh_operational_row: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    thread = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not thread or thread.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    existing = await _fetch_fact_by_idempotency_key(database, user_id=user_id, idempotency_key=idempotency_key, writer="frontend_manual")
    if existing:
        created_row = existing
    else:
        source_uuid = _uuid_from_ref(source_ref, fallback=idempotency_key)
        if target_fact_type == "task":
            content = _manual_action_content(
                fact_type="task",
                title=title or thread["content"].get("title") or "Follow up",
                notes=notes or thread["content"].get("summary"),
                due_at=due_at,
                remind_at=None,
                timezone_name=timezone_name or thread.get("timezone"),
                priority=priority or thread.get("priority"),
                source_type=source_type,
            )
            domain = "obligations"
            create_event_type = "task_created"
        else:
            content = _manual_action_content(
                fact_type="reminder",
                title=title or thread["content"].get("title") or "Follow up",
                notes=notes or thread["content"].get("summary"),
                due_at=None,
                remind_at=remind_at,
                timezone_name=timezone_name or thread.get("timezone"),
                priority=priority or thread.get("priority"),
                source_type=source_type,
            )
            domain = "obligations"
            create_event_type = "reminder_created"
        created_row = await _insert_confirmed_fact(
            database,
            user_id=user_id,
            fact_type=target_fact_type,
            domain=domain,
            content=content,
            confidence=1.0,
            source_ids=[source_uuid],
            status="active",
            source_type=source_type,
            who_said_it="user",
            channel=source_type,
            created_from=_manual_created_from(screen=screen, tenant_id=None, idempotency_key=idempotency_key, source_ref=source_ref),
        )
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type=create_event_type,
            timeline_type="user_life",
            title=content.get("title") or target_fact_type.title(),
            summary=content.get("summary") or content.get("title") or "",
            source_id=source_uuid,
            related_fact_ids=[created_row["id"]],
            confidence=created_row["confidence"],
        )
        await _upsert_fact_link(
            database,
            user_id=user_id,
            from_fact_id=thread["id"],
            to_fact_id=created_row["id"],
            link_type="spawned_action",
            confidence=1.0,
            evidence={"origin": "thread_conversion", "target_kind": target_fact_type},
            created_from={"writer": "frontend_manual", "screen": screen, "idempotency_key": idempotency_key},
            source_type=source_type,
        )

    thread_created_from = thread.setdefault("created_from", {})
    thread_created_from["writer"] = "frontend_manual"
    thread_created_from["screen"] = screen
    thread_created_from["source_ref"] = source_ref
    thread_created_from["last_mutation_idempotency_key"] = idempotency_key
    thread["source_type"] = source_type
    thread["who_said_it"] = "user"
    thread["channel"] = source_type
    thread["last_seen_at"] = now_naive()
    thread["last_confirmed_at"] = thread["last_seen_at"]
    progressed_at = thread["last_seen_at"].replace(tzinfo=timezone.utc).isoformat()
    _set_thread_field(thread["content"], "last_progressed_at", progressed_at)
    _set_thread_field(thread["content"], "next_move", "wait")
    _set_thread_field(thread["content"], "surface_reason", f"Converted into a {target_fact_type}.")
    thread["follow_up_needed"] = True
    refresh_operational_row(thread, item_type="thread", source_id=thread["source_ids"][0] if thread.get("source_ids") else None, source_ids=thread.get("source_ids"))
    await _update_fact_record(database, thread)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="thread_progressed",
        timeline_type="relationship",
        title=thread["content"].get("title") or "Thread progressed",
        summary=f"Converted into a {target_fact_type}.",
        source_id=thread["source_ids"][0] if thread.get("source_ids") else None,
        related_fact_ids=[thread["id"]],
        confidence=thread["confidence"],
    )
    return thread, created_row


async def update_thread_links_data(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    additions: dict[str, list[UUID]],
    removals: dict[str, list[UUID]],
    link_type: str,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    now_naive: Callable[[], datetime],
    refresh_operational_row: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    created_from = fact.setdefault("created_from", {})
    if idempotency_key and created_from.get("last_mutation_idempotency_key") == idempotency_key:
        return fact, await _fetch_fact_links_for_fact(database, user_id=user_id, from_fact_id=item_id)
    if idempotency_key:
        created_from["last_mutation_idempotency_key"] = idempotency_key
    created_from["writer"] = "frontend_manual"
    created_from["screen"] = screen
    created_from["source_ref"] = source_ref
    added = 0
    removed = 0
    for fact_id in additions.get("fact_ids", []):
        await _upsert_fact_link(
            database,
            user_id=user_id,
            from_fact_id=item_id,
            to_fact_id=fact_id,
            link_type=link_type,
            confidence=1.0,
            evidence={"origin": "thread_links_endpoint"},
            created_from={"writer": "frontend_manual", "screen": screen, "idempotency_key": idempotency_key},
            source_type=source_type,
        )
        added += 1
    for event_id in additions.get("timeline_event_ids", []):
        await _upsert_fact_link(
            database,
            user_id=user_id,
            from_fact_id=item_id,
            to_timeline_event_id=event_id,
            link_type=link_type,
            confidence=1.0,
            evidence={"origin": "thread_links_endpoint"},
            created_from={"writer": "frontend_manual", "screen": screen, "idempotency_key": idempotency_key},
            source_type=source_type,
        )
        added += 1
    for archive_id in additions.get("source_archive_ids", []):
        await _upsert_fact_link(
            database,
            user_id=user_id,
            from_fact_id=item_id,
            to_source_archive_id=archive_id,
            link_type=link_type,
            confidence=1.0,
            evidence={"origin": "thread_links_endpoint"},
            created_from={"writer": "frontend_manual", "screen": screen, "idempotency_key": idempotency_key},
            source_type=source_type,
        )
        added += 1
    for outbox_id in additions.get("outbox_ids", []):
        await _upsert_fact_link(
            database,
            user_id=user_id,
            from_fact_id=item_id,
            to_outbox_id=outbox_id,
            link_type=link_type,
            confidence=1.0,
            evidence={"origin": "thread_links_endpoint"},
            created_from={"writer": "frontend_manual", "screen": screen, "idempotency_key": idempotency_key},
            source_type=source_type,
        )
        added += 1
    for fact_id in removals.get("fact_ids", []):
        removed += int(await _deactivate_fact_link(database, user_id=user_id, from_fact_id=item_id, target_kind="fact", target_id=fact_id))
    for event_id in removals.get("timeline_event_ids", []):
        removed += int(await _deactivate_fact_link(database, user_id=user_id, from_fact_id=item_id, target_kind="timeline_event", target_id=event_id))
    for archive_id in removals.get("source_archive_ids", []):
        removed += int(await _deactivate_fact_link(database, user_id=user_id, from_fact_id=item_id, target_kind="source_archive", target_id=archive_id))
    for outbox_id in removals.get("outbox_ids", []):
        removed += int(await _deactivate_fact_link(database, user_id=user_id, from_fact_id=item_id, target_kind="outbox", target_id=outbox_id))
    fact["last_seen_at"] = now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    fact["source_type"] = source_type
    _set_thread_field(fact["content"], "surface_reason", "Thread links were updated.")
    refresh_operational_row(fact, item_type="thread", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="thread_link_updated",
        timeline_type="relationship",
        title=fact["content"].get("title") or "Thread links updated",
        summary=f"Added {added} link(s), removed {removed} link(s).",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return fact, await _fetch_fact_links_for_fact(database, user_id=user_id, from_fact_id=item_id)


async def explain_thread_data(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    kind_for_row: Callable[[dict[str, Any]], str],
    fact_item_status: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    links = await _fetch_fact_links_for_fact(database, user_id=user_id, from_fact_id=item_id)
    facts_by_id = {row["id"]: row for row in await _fetch_confirmed_facts(database, user_id=user_id)}
    timeline = [event for event in getattr(database, "timeline_events", []) if event["user_id"] == user_id] if hasattr(database, "timeline_events") else await database.fetch("SELECT * FROM timeline_events WHERE user_id = $1", user_id)
    timeline_by_id = {row["id"]: row for row in timeline}
    archive_rows = {row["id"]: row for row in await _fetch_source_archive_by_user(database, user_id=user_id)}
    outbox_rows = {}
    if hasattr(database, "outbox_rows"):
        rows = getattr(database, "outbox_rows")
        rows = rows.values() if isinstance(rows, dict) else rows
        outbox_rows = {row["id"]: row for row in rows if row["user_id"] == user_id}
    metadata = fact.get("content", {}).get("metadata") or {}
    structured_thread = _thread_structured(fact)
    linked_facts = []
    linked_events = []
    linked_sources = []
    for link in links:
        if link.get("to_fact_id") and link["to_fact_id"] in facts_by_id:
            linked = facts_by_id[link["to_fact_id"]]
            linked_facts.append(
                {
                    "id": str(linked["id"]),
                    "kind": kind_for_row(linked),
                    "title": (linked.get("content") or {}).get("title"),
                    "status": fact_item_status(linked),
                    "linkType": link.get("link_type"),
                }
            )
        if link.get("to_timeline_event_id") and link["to_timeline_event_id"] in timeline_by_id:
            event = timeline_by_id[link["to_timeline_event_id"]]
            linked_events.append(
                {
                    "id": str(event["id"]),
                    "eventType": event.get("event_type"),
                    "title": event.get("title"),
                    "summary": event.get("summary"),
                    "linkType": link.get("link_type"),
                }
            )
        if link.get("to_source_archive_id") and link["to_source_archive_id"] in archive_rows:
            archive = archive_rows[link["to_source_archive_id"]]
            linked_sources.append(
                {
                    "type": "source_archive",
                    "id": str(archive["id"]),
                    "sourceType": archive.get("source_type"),
                    "sourceExternalId": archive.get("source_external_id"),
                    "linkType": link.get("link_type"),
                }
            )
        if link.get("to_outbox_id") and link["to_outbox_id"] in outbox_rows:
            outbox = outbox_rows[link["to_outbox_id"]]
            linked_sources.append(
                {
                    "type": "outbox",
                    "id": str(outbox["id"]),
                    "sourceType": outbox.get("source_type"),
                    "rawContent": outbox.get("raw_content"),
                    "linkType": link.get("link_type"),
                }
            )
    why_open = structured_thread.get("resolution_condition") or metadata.get("last_status") or structured_thread.get("surface_reason") or fact.get("content", {}).get("summary")
    why_now = structured_thread.get("surface_reason") or (f"Snooze expired at {_to_iso(fact.get('snoozed_until'))}." if fact.get("snoozed_until") and not _thread_snoozed(fact) else "This thread is still open and marked for follow-up.")
    return {
        "fact": fact,
        "thread_type": fact.get("thread_type") or structured_thread.get("thread_type"),
        "actionability": fact.get("actionability") or structured_thread.get("actionability"),
        "next_move": fact.get("next_move") or structured_thread.get("next_move"),
        "evidence_preview": ((fact.get("content", {}).get("evidence") or {}).get("raw_evidence") or fact.get("content", {}).get("summary")),
        "source_refs": [f"outbox:{value}" for value in fact.get("source_ids", [])],
        "linked_facts": linked_facts,
        "linked_events": linked_events,
        "linked_sources": linked_sources,
        "why_open": why_open,
        "why_now": why_now,
        "confidence": float(fact.get("confidence", 0.0)),
    }
