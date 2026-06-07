from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import (
    _fetch_confirmed_facts,
    _fetch_fact_by_id,
    _fetch_fact_by_idempotency_key,
    _insert_confirmed_fact,
    _insert_timeline_event,
    _update_fact_record,
)
from core.item_shapes import _frontend_manual_response, _kind_for_row, _manual_created_from
from core.item_utils import _now_naive, _refresh_operational_row, _uuid_from_ref


async def manual_list_by_kind(database: Database, *, user_id: str, kind: str, fact_types: list[str]) -> dict[str, Any]:
    rows = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=fact_types)
    items = []
    for row in rows:
        if _kind_for_row(row) != kind:
            continue
        if row.get("status") == "corrected":
            continue
        items.append(_frontend_manual_response(row))
    items.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)
    return {"items": items}


async def manual_get_by_kind(database: Database, *, user_id: str, item_id: UUID, kind: str, fact_types: list[str]) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") not in fact_types or _kind_for_row(row) != kind:
        raise HTTPException(status_code=404, detail=f"{kind.title()} not found.")
    return _frontend_manual_response(row)


async def manual_create_fact(
    database: Database,
    *,
    user_id: str,
    fact_type: str,
    domain: str,
    content: dict[str, Any],
    confidence: float,
    source_type: str,
    screen: str,
    tenant_id: str | None,
    source_ref: str | None,
    idempotency_key: str,
    event_type: str,
) -> dict[str, Any]:
    existing = await _fetch_fact_by_idempotency_key(database, user_id=user_id, idempotency_key=idempotency_key, writer="frontend_manual")
    if existing:
        return _frontend_manual_response(existing)
    source_uuid = _uuid_from_ref(source_ref, fallback=idempotency_key)
    row = await _insert_confirmed_fact(
        database,
        user_id=user_id,
        fact_type=fact_type,
        domain=domain,
        content=content,
        confidence=confidence,
        source_ids=[source_uuid],
        status="active",
        source_type=source_type,
        who_said_it="user",
        channel=source_type,
        created_from=_manual_created_from(screen=screen, tenant_id=tenant_id, idempotency_key=idempotency_key, source_ref=source_ref),
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type=event_type,
        timeline_type="calendar" if fact_type == "event" else "user_life",
        title=content.get("title") or fact_type.title(),
        summary=content.get("summary") or content.get("title") or "",
        source_id=source_uuid,
        related_fact_ids=[row["id"]],
        confidence=confidence,
    )
    return _frontend_manual_response(row)


async def manual_mutate_fact(
    database: Database,
    *,
    row: dict[str, Any],
    source_type: str,
    screen: str,
    source_ref: str | None,
    idempotency_key: str | None,
    event_type: str | None,
) -> dict[str, Any]:
    created_from = row.setdefault("created_from", {})
    if isinstance(created_from, dict) and idempotency_key and created_from.get("last_mutation_idempotency_key") == idempotency_key:
        return _frontend_manual_response(row)
    if isinstance(created_from, dict):
        created_from["writer"] = "frontend_manual"
        created_from["screen"] = screen
        created_from["source_ref"] = source_ref
        if idempotency_key:
            created_from["last_mutation_idempotency_key"] = idempotency_key
    row["source_type"] = source_type
    row["who_said_it"] = "user"
    row["channel"] = source_type
    row["last_seen_at"] = _now_naive()
    row["last_confirmed_at"] = row["last_seen_at"]
    _refresh_operational_row(row, item_type=row["fact_type"], source_id=row["source_ids"][0] if row.get("source_ids") else None, source_ids=row.get("source_ids"))
    await _update_fact_record(database, row)
    if event_type:
        await _insert_timeline_event(
            database,
            user_id=row["user_id"],
            event_type=event_type,
            timeline_type="calendar" if row.get("fact_type") == "event" else "user_life",
            title=(row.get("content") or {}).get("title") or row.get("fact_type", "item").title(),
            summary=(row.get("content") or {}).get("summary") or "",
            source_id=row["source_ids"][0] if row.get("source_ids") else None,
            related_fact_ids=[row["id"]],
            confidence=row["confidence"],
        )
    return _frontend_manual_response(row)
