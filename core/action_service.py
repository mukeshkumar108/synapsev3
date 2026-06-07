from __future__ import annotations

from datetime import timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import _fetch_fact_by_id
from core.operational import apply_lifecycle_timestamp
from core.item_shapes import _kind_for_row, _manual_action_content
from core.item_utils import _now_naive


ManualResponse = Callable[[dict[str, Any]], dict[str, Any]]
ManualCreateFact = Callable[..., Awaitable[dict[str, Any]]]
ManualMutateFact = Callable[..., Awaitable[dict[str, Any]]]
ManualListByKind = Callable[..., Awaitable[dict[str, Any]]]
ManualGetByKind = Callable[..., Awaitable[dict[str, Any]]]
def _completion_timestamp(explicit_value: str | None) -> str:
    return explicit_value or _now_naive().replace(tzinfo=timezone.utc).isoformat()


async def list_tasks_manual(
    database: Database,
    *,
    user_id: str,
    manual_list_by_kind: ManualListByKind,
) -> dict[str, Any]:
    return await manual_list_by_kind(database, user_id=user_id, kind="task", fact_types=["task"])


async def get_task_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    manual_get_by_kind: ManualGetByKind,
) -> dict[str, Any]:
    return await manual_get_by_kind(database, user_id=user_id, item_id=item_id, kind="task", fact_types=["task"])


async def create_task_manual(
    database: Database,
    *,
    user_id: str,
    title: str,
    notes: str | None,
    due_at: str | None,
    timezone_name: str | None,
    priority: str | None,
    screen: str,
    idempotency_key: str,
    tenant_id: str | None,
    source_type: str,
    source_ref: str | None,
    manual_create_fact: ManualCreateFact,
) -> dict[str, Any]:
    content = _manual_action_content(
        fact_type="task",
        title=title,
        notes=notes,
        due_at=due_at,
        remind_at=None,
        timezone_name=timezone_name,
        priority=priority,
        source_type=source_type,
    )
    return await manual_create_fact(
        database,
        user_id=user_id,
        fact_type="task",
        domain="obligations",
        content=content,
        confidence=1.0,
        source_type=source_type,
        screen=screen,
        tenant_id=tenant_id,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="task_created",
    )


async def update_task_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    title: str | None,
    notes: str | None,
    due_at: str | None,
    timezone_name: str | None,
    priority: str | None,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    manual_mutate_fact: ManualMutateFact,
) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") != "task" or _kind_for_row(row) != "task":
        raise HTTPException(status_code=404, detail="Task not found.")
    content = row["content"]
    if title is not None:
        content["title"] = title
    if notes is not None:
        content["summary"] = notes
        content.setdefault("evidence", {})["raw_evidence"] = notes
    content.setdefault("time", {})
    if due_at is not None:
        content["time"]["due_date"] = due_at
    if timezone_name is not None:
        content["time"]["timezone"] = timezone_name
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
        event_type="task_updated",
    )


async def complete_task_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    completed_at: str | None,
    manual_mutate_fact: ManualMutateFact,
) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") != "task" or _kind_for_row(row) != "task":
        raise HTTPException(status_code=404, detail="Task not found.")
    row["status"] = "historical"
    row["content"].setdefault("metadata", {})["item_status"] = "completed"
    row["content"] = apply_lifecycle_timestamp(row["content"], completed_at=_completion_timestamp(completed_at))
    return await manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="task_completed",
    )


async def archive_task_manual(
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
    if not row or row.get("fact_type") != "task" or _kind_for_row(row) != "task":
        raise HTTPException(status_code=404, detail="Task not found.")
    row["status"] = "historical"
    row["content"].setdefault("metadata", {})["item_status"] = "archived"
    return await manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="task_archived",
    )


async def list_reminders_manual(
    database: Database,
    *,
    user_id: str,
    manual_list_by_kind: ManualListByKind,
) -> dict[str, Any]:
    return await manual_list_by_kind(database, user_id=user_id, kind="reminder", fact_types=["reminder"])


async def get_reminder_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    manual_get_by_kind: ManualGetByKind,
) -> dict[str, Any]:
    return await manual_get_by_kind(database, user_id=user_id, item_id=item_id, kind="reminder", fact_types=["reminder"])


async def create_reminder_manual(
    database: Database,
    *,
    user_id: str,
    title: str,
    notes: str | None,
    remind_at: str | None,
    timezone_name: str | None,
    priority: str | None,
    screen: str,
    idempotency_key: str,
    tenant_id: str | None,
    source_type: str,
    source_ref: str | None,
    manual_create_fact: ManualCreateFact,
) -> dict[str, Any]:
    content = _manual_action_content(
        fact_type="reminder",
        title=title,
        notes=notes,
        due_at=None,
        remind_at=remind_at,
        timezone_name=timezone_name,
        priority=priority,
        source_type=source_type,
    )
    return await manual_create_fact(
        database,
        user_id=user_id,
        fact_type="reminder",
        domain="obligations",
        content=content,
        confidence=1.0,
        source_type=source_type,
        screen=screen,
        tenant_id=tenant_id,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="reminder_created",
    )


async def update_reminder_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    title: str | None,
    notes: str | None,
    remind_at: str | None,
    timezone_name: str | None,
    priority: str | None,
    screen: str,
    source_type: str,
    source_ref: str | None,
    idempotency_key: str | None,
    manual_mutate_fact: ManualMutateFact,
) -> dict[str, Any]:
    row = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not row or row.get("fact_type") != "reminder" or _kind_for_row(row) != "reminder":
        raise HTTPException(status_code=404, detail="Reminder not found.")
    content = row["content"]
    if title is not None:
        content["title"] = title
    if notes is not None:
        content["summary"] = notes
        content.setdefault("evidence", {})["raw_evidence"] = notes
    content.setdefault("time", {})
    if remind_at is not None:
        content["time"]["reminder_at"] = remind_at
    if timezone_name is not None:
        content["time"]["timezone"] = timezone_name
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
        event_type="reminder_updated",
    )


async def dismiss_reminder_manual(
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
    if not row or row.get("fact_type") != "reminder" or _kind_for_row(row) != "reminder":
        raise HTTPException(status_code=404, detail="Reminder not found.")
    row["status"] = "dismissed"
    row["content"].setdefault("metadata", {})["item_status"] = "dismissed"
    row["content"] = apply_lifecycle_timestamp(row["content"], cancelled_at=_now_naive().replace(tzinfo=timezone.utc).isoformat())
    return await manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="reminder_dismissed",
    )


async def archive_reminder_manual(
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
    if not row or row.get("fact_type") != "reminder" or _kind_for_row(row) != "reminder":
        raise HTTPException(status_code=404, detail="Reminder not found.")
    row["status"] = "historical"
    row["content"].setdefault("metadata", {})["item_status"] = "archived"
    row["content"] = apply_lifecycle_timestamp(row["content"], cancelled_at=_now_naive().replace(tzinfo=timezone.utc).isoformat())
    return await manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type="reminder_archived",
    )
