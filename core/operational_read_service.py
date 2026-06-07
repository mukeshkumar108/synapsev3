from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import (
    _fetch_candidate_by_id,
    _fetch_candidates,
    _fetch_confirmed_facts,
    _fetch_fact_by_id,
    _fetch_source_archive_by_user,
)
from core.item_shapes import _canonical_item, _filter_status, _kind_for_row
from core.item_utils import _iso_day
from core.operational import parse_datetime


async def todays_schedule(database: Database, *, user_id: str, day: str) -> dict[str, Any]:
    facts = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["event"])
    items = []
    for row in facts:
        starts_at = row.get("starts_at") or ((row.get("content") or {}).get("time") or {}).get("starts_at") or ((row.get("content") or {}).get("time") or {}).get("date")
        if _iso_day(starts_at) != day:
            continue
        if row.get("status") != "active":
            continue
        items.append(_canonical_item(source_kind="confirmed_fact", row=row, item_class="event"))
    items.sort(key=lambda item: item.get("starts_at") or item.get("due_at") or "")
    return {"items": items}


async def due_tasks(database: Database, *, user_id: str, now: str) -> dict[str, Any]:
    facts = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["task"])
    cutoff = parse_datetime(now)
    items = []
    for row in facts:
        if row.get("status") != "active" or _kind_for_row(row) != "task":
            continue
        due = row.get("due_at") or ((row.get("content") or {}).get("time") or {}).get("due_date")
        due_dt = parse_datetime(due) if isinstance(due, str) else (due.replace(tzinfo=timezone.utc) if isinstance(due, datetime) and due.tzinfo is None else due)
        if cutoff is not None and due_dt is not None and due_dt <= cutoff:
            items.append(_canonical_item(source_kind="confirmed_fact", row=row, item_class="action"))
    items.sort(key=lambda item: item.get("due_at") or "")
    return {"items": items}


async def pending_reminders(database: Database, *, user_id: str) -> dict[str, Any]:
    facts = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["task", "reminder"])
    items = []
    for row in facts:
        if row.get("status") != "active" or _kind_for_row(row) != "reminder":
            continue
        items.append(_canonical_item(source_kind="confirmed_fact", row=row, item_class="action"))
    items.sort(key=lambda item: item.get("remind_at") or "")
    return {"items": items}


async def list_actions(database: Database, *, user_id: str, status: str = "active", limit: int = 20) -> dict[str, Any]:
    facts = _filter_status(await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["task"]), status=status, source_kind="confirmed_fact")
    candidates = _filter_status(await _fetch_candidates(database, user_id=user_id, candidate_types=["task"]), status=status, source_kind="candidate")
    items = [
        *[_canonical_item(source_kind="confirmed_fact", row=row, item_class="action") for row in facts],
        *[_canonical_item(source_kind="candidate", row=row, item_class="action") for row in candidates],
    ]
    items.sort(key=lambda item: (item["status"] != "active", item["updated_at"]), reverse=False)
    return {"items": items[:limit]}


async def ensure_user_item_visible(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    allowed_fact_types: list[str],
    allowed_candidate_types: list[str],
) -> None:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if fact and fact.get("fact_type") in allowed_fact_types:
        return
    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=item_id)
    if candidate and candidate.get("candidate_type") in allowed_candidate_types:
        return
    raise HTTPException(status_code=404, detail="Item not found.")


async def source_archive_count(database: Database, *, user_id: str) -> int:
    return len(await _fetch_source_archive_by_user(database, user_id=user_id))
