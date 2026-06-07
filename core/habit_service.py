from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import _fetch_fact_by_id, _fetch_confirmed_facts
from core.operational import apply_lifecycle_timestamp
from core.item_shapes import _canonical_item, _kind_for_row, _manual_habit_content
from core.item_utils import _iso_day, _now_naive


ManualListByKind = Callable[..., Awaitable[dict[str, Any]]]
ManualGetByKind = Callable[..., Awaitable[dict[str, Any]]]
ManualCreateFact = Callable[..., Awaitable[dict[str, Any]]]
ManualMutateFact = Callable[..., Awaitable[dict[str, Any]]]
RefreshOperationalRow = Callable[..., dict[str, Any]]
UpdateFactRecord = Callable[..., Awaitable[None]]
InsertTimelineEvent = Callable[..., Awaitable[None]]


async def active_habits(
    database: Database,
    *,
    user_id: str,
) -> dict[str, Any]:
    facts = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["habit", "task"])
    items = []
    for row in facts:
        if row.get("status") != "active" or _kind_for_row(row) != "habit":
            continue
        items.append(_canonical_item(source_kind="confirmed_fact", row=row, item_class="action"))
    return {"items": items}


async def habit_completion_status(
    database: Database,
    *,
    user_id: str,
    day: str,
    active_habits_fn: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    habits = await active_habits_fn(database, user_id=user_id)
    events = (
        await database.fetch(
            """
            SELECT *
            FROM timeline_events
            WHERE user_id = $1
            ORDER BY observed_at DESC NULLS LAST, occurred_at DESC NULLS LAST
            """,
            user_id,
        )
        if not hasattr(database, "timeline_events")
        else [event for event in getattr(database, "timeline_events") if event["user_id"] == user_id]
    )
    by_fact: dict[str, str] = {}
    for event in events:
        event_day = _iso_day(event.get("occurred_at"))
        if event_day != day:
            continue
        event_type = event.get("event_type")
        for fact_id in event.get("related_fact_ids", []) or []:
            if event_type in {"habit_completed", "habit_partial", "habit_missed"}:
                by_fact[str(fact_id)] = event_type
    return {
        "items": [
            {
                **item,
                "completion_status": by_fact.get(item["id"], "pending"),
            }
            for item in habits["items"]
        ]
    }


async def list_habits_manual(
    database: Database,
    *,
    user_id: str,
    manual_list_by_kind: ManualListByKind,
) -> dict[str, Any]:
    return await manual_list_by_kind(database, user_id=user_id, kind="habit", fact_types=["habit"])


async def get_habit_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    manual_get_by_kind: ManualGetByKind,
) -> dict[str, Any]:
    return await manual_get_by_kind(database, user_id=user_id, item_id=item_id, kind="habit", fact_types=["habit"])


async def create_habit_manual(
    database: Database,
    *,
    user_id: str,
    title: str,
    notes: str | None,
    timezone_name: str | None,
    priority: str | None,
    cadence: str | None,
    screen: str,
    idempotency_key: str,
    tenant_id: str | None,
    source_type: str,
    source_ref: str | None,
    manual_create_fact: ManualCreateFact,
) -> dict[str, Any]:
    content = _manual_habit_content(
        title=title,
        notes=notes,
        timezone_name=timezone_name,
        priority=priority,
        cadence=cadence,
        source_type=source_type,
    )
    return await manual_create_fact(
        database,
        user_id=user_id,
        fact_type="habit",
        domain="habits",
        content=content,
        confidence=1.0,
        source_type=source_type,
        screen=screen,
        tenant_id=tenant_id,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="habit_created",
    )


async def update_habit_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    title: str | None,
    notes: str | None,
    timezone_name: str | None,
    priority: str | None,
    cadence: str | None,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    manual_mutate_fact: ManualMutateFact,
) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") != "habit" or _kind_for_row(row) != "habit":
        raise HTTPException(status_code=404, detail="Habit not found.")
    content = row["content"]
    if title is not None:
        content["title"] = title
    if notes is not None:
        content["summary"] = notes
        content.setdefault("evidence", {})["raw_evidence"] = notes
    content.setdefault("time", {})
    if timezone_name is not None:
        content["time"]["timezone"] = timezone_name
    if cadence is not None:
        content["time"]["recurrence_rule"] = cadence
        content.setdefault("metadata", {}).setdefault("agent_item", {})["cadence"] = cadence
        content["metadata"]["agent_item"]["recurrence"] = cadence
        content["metadata"]["agent_item"]["is_habit"] = True
    if priority is not None:
        content["priority"] = priority
        content["importance"] = priority
        content["salience"] = priority
        content["urgency"] = priority
    row["content"] = content
    return await manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="habit_updated",
    )


async def archive_habit_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    manual_mutate_fact: ManualMutateFact,
) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") != "habit" or _kind_for_row(row) != "habit":
        raise HTTPException(status_code=404, detail="Habit not found.")
    row["status"] = "historical"
    row["content"].setdefault("metadata", {})["item_status"] = "archived"
    return await manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="habit_archived",
    )


async def record_habit_completion(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    completed_at: str,
    status: str,
    source_type: str | None,
    screen: str | None,
    source_ref: str | None,
    idempotency_key: str | None,
    manual_mutate_fact: ManualMutateFact,
    refresh_operational_row: RefreshOperationalRow,
    update_fact_record: UpdateFactRecord,
    insert_timeline_event: InsertTimelineEvent,
    to_naive: Callable[[str | None], Any],
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or _kind_for_row(fact) != "habit":
        raise HTTPException(status_code=404, detail="Habit not found.")
    fact["content"] = apply_lifecycle_timestamp(fact["content"], completed_at=completed_at)
    if source_type or screen or source_ref or idempotency_key:
        return await manual_mutate_fact(
            database,
            row=fact,
            source_type=source_type or fact.get("source_type") or "frontend_manual",
            screen=screen or "habits_tab",
            source_ref=source_ref,
            idempotency_key=idempotency_key,
            event_type=status,
        )
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    refresh_operational_row(fact, item_type=fact.get("fact_type") or "habit", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await update_fact_record(database, fact)
    await insert_timeline_event(
        database,
        user_id=user_id,
        event_type=status,
        timeline_type="user_life",
        title=fact["content"].get("title") or "Habit update",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
        occurred_at=to_naive(completed_at),
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="action")
