from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from core.db import Database
from core.item_shapes import (
    _build_content,
    _canonical_item,
    _fact_item_status,
    _frontend_manual_response,
    _kind_for_row,
)
from core.item_utils import _now_naive, _refresh_operational_row, _to_naive
from core.item_repository import (
    _serialize_fact_link,
    _update_candidate_record,
    _update_fact_record,
    _insert_timeline_event,
)
from core.operational import parse_datetime
from core import action_service
from core import action_update_service
from core import event_service
from core import habit_service
from core import manual_item_service
from core import memory_control_service
from core import operational_read_service
from core import sophie_action_service
from core import thread_service


ActionStatus = Literal["active", "completed", "dismissed", "stale", "all"]
EventStatus = Literal["active", "dismissed", "confirmed", "all"]
MemoryControlAction = Literal["forget", "correct", "avoid_topic", "dismiss", "resolve_loop"]


async def todays_schedule(database: Database, *, user_id: str, day: str) -> dict[str, Any]:
    return await operational_read_service.todays_schedule(database, user_id=user_id, day=day)


async def due_tasks(database: Database, *, user_id: str, now: str) -> dict[str, Any]:
    return await operational_read_service.due_tasks(database, user_id=user_id, now=now)


async def pending_reminders(database: Database, *, user_id: str) -> dict[str, Any]:
    return await operational_read_service.pending_reminders(database, user_id=user_id)


async def active_habits(database: Database, *, user_id: str) -> dict[str, Any]:
    return await habit_service.active_habits(database, user_id=user_id)


async def habit_completion_status(database: Database, *, user_id: str, day: str) -> dict[str, Any]:
    return await habit_service.habit_completion_status(
        database,
        user_id=user_id,
        day=day,
        active_habits_fn=active_habits,
    )


async def open_threads(database: Database, *, user_id: str) -> dict[str, Any]:
    rows = await thread_service.open_thread_rows(database, user_id=user_id)
    return {"items": [_canonical_item(source_kind="confirmed_fact", row=row, item_class="thread") for row in rows]}


async def list_actions(database: Database, *, user_id: str, status: str = "active", limit: int = 20) -> dict[str, Any]:
    return await operational_read_service.list_actions(database, user_id=user_id, status=status, limit=limit)


async def list_events(database: Database, *, user_id: str, status: str = "active", limit: int = 20) -> dict[str, Any]:
    return await event_service.list_events(database, user_id=user_id, status=status, limit=limit)


async def create_action(
    database: Database,
    *,
    user_id: str,
    title: str,
    summary: str,
    due_at: str | None,
    priority: str | None,
    links: dict[str, Any] | None,
    source: str,
    requires_confirmation: bool,
) -> dict[str, Any]:
    return await action_update_service.create_action(
        database,
        user_id=user_id,
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
        links=links,
        source=source,
        requires_confirmation=requires_confirmation,
    )


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
    return await event_service.create_event(
        database,
        user_id=user_id,
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
        links=links,
        source=source,
    )


async def _manual_list_by_kind(database: Database, *, user_id: str, kind: str, fact_types: list[str]) -> dict[str, Any]:
    return await manual_item_service.manual_list_by_kind(database, user_id=user_id, kind=kind, fact_types=fact_types)


async def _manual_get_by_kind(database: Database, *, user_id: str, item_id: UUID, kind: str, fact_types: list[str]) -> dict[str, Any]:
    return await manual_item_service.manual_get_by_kind(database, user_id=user_id, item_id=item_id, kind=kind, fact_types=fact_types)


async def _manual_create_fact(
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
    return await manual_item_service.manual_create_fact(
        database,
        user_id=user_id,
        fact_type=fact_type,
        domain=domain,
        content=content,
        confidence=confidence,
        source_type=source_type,
        screen=screen,
        tenant_id=tenant_id,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type=event_type,
    )


async def _manual_mutate_fact(
    database: Database,
    *,
    row: dict[str, Any],
    source_type: str,
    screen: str,
    source_ref: str | None,
    idempotency_key: str | None,
    event_type: str | None,
) -> dict[str, Any]:
    return await manual_item_service.manual_mutate_fact(
        database,
        row=row,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        event_type=event_type,
    )


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
    return await sophie_action_service.sophie_create_confirmed_action(
        database,
        user_id=user_id,
        kind=kind,
        title=title,
        notes=notes,
        due_at=due_at,
        remind_at=remind_at,
        timezone_name=timezone_name,
        source_type=source_type,
        provenance_summary=provenance_summary,
        confidence=confidence,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        original_text=original_text,
        participants=participants,
        location=location,
        tenant_id=tenant_id,
    )


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
    return await sophie_action_service.sophie_patch_confirmed_action(
        database,
        item_id=item_id,
        user_id=user_id,
        title=title,
        notes=notes,
        due_at=due_at,
        remind_at=remind_at,
        timezone_name=timezone_name,
        source_type=source_type,
        provenance_summary=provenance_summary,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        status=status,
        completed_at=completed_at,
    )


async def sophie_delete_confirmed_action(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    return await sophie_action_service.sophie_delete_confirmed_action(
        database,
        item_id=item_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )


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
    return await event_service.sophie_create_confirmed_event(
        database,
        user_id=user_id,
        title=title,
        notes=notes,
        starts_at=starts_at,
        ends_at=ends_at,
        timezone_name=timezone_name,
        location=location,
        participants=participants,
        source_type=source_type,
        provenance_summary=provenance_summary,
        confidence=confidence,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        original_text=original_text,
        tenant_id=tenant_id,
    )


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
    return await event_service.sophie_patch_confirmed_event(
        database,
        item_id=item_id,
        user_id=user_id,
        title=title,
        notes=notes,
        starts_at=starts_at,
        ends_at=ends_at,
        timezone_name=timezone_name,
        location=location,
        participants=participants,
        source_type=source_type,
        provenance_summary=provenance_summary,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
    )


async def sophie_cancel_confirmed_event(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    return await event_service.sophie_cancel_confirmed_event(
        database,
        item_id=item_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )


async def list_tasks_manual(database: Database, *, user_id: str) -> dict[str, Any]:
    return await action_service.list_tasks_manual(database, user_id=user_id, manual_list_by_kind=_manual_list_by_kind)


async def get_task_manual(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any]:
    return await action_service.get_task_manual(database, user_id=user_id, item_id=item_id, manual_get_by_kind=_manual_get_by_kind)


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
    tenant_id: str | None = None,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
) -> dict[str, Any]:
    return await action_service.create_task_manual(
        database,
        user_id=user_id,
        title=title,
        notes=notes,
        due_at=due_at,
        timezone_name=timezone_name,
        priority=priority,
        screen=screen,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        source_type=source_type,
        source_ref=source_ref,
        manual_create_fact=_manual_create_fact,
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
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await action_service.update_task_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        title=title,
        notes=notes,
        due_at=due_at,
        timezone_name=timezone_name,
        priority=priority,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def complete_task_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    return await action_service.complete_task_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        completed_at=completed_at,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def archive_task_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await action_service.archive_task_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def list_reminders_manual(database: Database, *, user_id: str) -> dict[str, Any]:
    return await action_service.list_reminders_manual(database, user_id=user_id, manual_list_by_kind=_manual_list_by_kind)


async def get_reminder_manual(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any]:
    return await action_service.get_reminder_manual(database, user_id=user_id, item_id=item_id, manual_get_by_kind=_manual_get_by_kind)


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
    tenant_id: str | None = None,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
) -> dict[str, Any]:
    return await action_service.create_reminder_manual(
        database,
        user_id=user_id,
        title=title,
        notes=notes,
        remind_at=remind_at,
        timezone_name=timezone_name,
        priority=priority,
        screen=screen,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        source_type=source_type,
        source_ref=source_ref,
        manual_create_fact=_manual_create_fact,
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
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await action_service.update_reminder_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        title=title,
        notes=notes,
        remind_at=remind_at,
        timezone_name=timezone_name,
        priority=priority,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def dismiss_reminder_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await action_service.dismiss_reminder_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def archive_reminder_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await action_service.archive_reminder_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def get_event_manual(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any]:
    return await event_service.get_event_manual(database, user_id=user_id, item_id=item_id)


async def delete_event_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await event_service.delete_event_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def list_habits_manual(database: Database, *, user_id: str) -> dict[str, Any]:
    return await habit_service.list_habits_manual(database, user_id=user_id, manual_list_by_kind=_manual_list_by_kind)


async def get_habit_manual(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any]:
    return await habit_service.get_habit_manual(database, user_id=user_id, item_id=item_id, manual_get_by_kind=_manual_get_by_kind)


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
    tenant_id: str | None = None,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
) -> dict[str, Any]:
    return await habit_service.create_habit_manual(
        database,
        user_id=user_id,
        title=title,
        notes=notes,
        timezone_name=timezone_name,
        priority=priority,
        cadence=cadence,
        screen=screen,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        source_type=source_type,
        source_ref=source_ref,
        manual_create_fact=_manual_create_fact,
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
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await habit_service.update_habit_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        title=title,
        notes=notes,
        timezone_name=timezone_name,
        priority=priority,
        cadence=cadence,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def archive_habit_manual(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await habit_service.archive_habit_manual(
        database,
        user_id=user_id,
        item_id=item_id,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
    )


async def _confirm_candidate_as_fact(
    database: Database,
    *,
    candidate: dict[str, Any],
    fact_type: str,
    domain: str,
    status: str = "active",
) -> dict[str, Any]:
    return await action_update_service._confirm_candidate_as_fact(
        database,
        candidate=candidate,
        fact_type=fact_type,
        domain=domain,
        status=status,
    )


async def update_action(
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
    return await action_update_service.update_action(
        database,
        item_id=item_id,
        user_id=user_id,
        status=status,
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
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
    return await event_service.update_event(
        database,
        item_id=item_id,
        user_id=user_id,
        status=status,
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
    )


async def record_habit_completion(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    completed_at: str,
    status: str = "habit_completed",
    source_type: str | None = None,
    screen: str | None = None,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return await habit_service.record_habit_completion(
        database,
        user_id=user_id,
        item_id=item_id,
        completed_at=completed_at,
        status=status,
        source_type=source_type,
        screen=screen,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        manual_mutate_fact=_manual_mutate_fact,
        refresh_operational_row=_refresh_operational_row,
        update_fact_record=_update_fact_record,
        insert_timeline_event=_insert_timeline_event,
        to_naive=_to_naive,
    )


async def resolve_thread(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any]:
    fact = await thread_service.resolve_thread_row(
        database,
        user_id=user_id,
        item_id=item_id,
        now_naive=_now_naive,
        refresh_operational_row=_refresh_operational_row,
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="thread")


async def dismiss_thread(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    fact = await thread_service.dismiss_thread_row(
        database,
        user_id=user_id,
        item_id=item_id,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        now_naive=_now_naive,
        refresh_operational_row=_refresh_operational_row,
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="thread")


async def snooze_thread(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    snoozed_until: str,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    fact = await thread_service.snooze_thread_row(
        database,
        user_id=user_id,
        item_id=item_id,
        snoozed_until=snoozed_until,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        now_naive=_now_naive,
        refresh_operational_row=_refresh_operational_row,
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="thread")


async def _convert_thread_to_fact(
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
) -> dict[str, Any]:
    thread, created_row = await thread_service.convert_thread_to_fact_rows(
        database,
        user_id=user_id,
        item_id=item_id,
        target_fact_type=target_fact_type,
        title=title,
        notes=notes,
        due_at=due_at,
        remind_at=remind_at,
        timezone_name=timezone_name,
        priority=priority,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        now_naive=_now_naive,
        refresh_operational_row=_refresh_operational_row,
    )
    return {
        "thread": _canonical_item(source_kind="confirmed_fact", row=thread, item_class="thread"),
        "item": _frontend_manual_response(created_row),
    }


async def convert_thread_to_task(
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
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    return await _convert_thread_to_fact(
        database,
        user_id=user_id,
        item_id=item_id,
        target_fact_type="task",
        title=title,
        notes=notes,
        due_at=due_at,
        remind_at=None,
        timezone_name=timezone_name,
        priority=priority,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
    )


async def convert_thread_to_reminder(
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
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    return await _convert_thread_to_fact(
        database,
        user_id=user_id,
        item_id=item_id,
        target_fact_type="reminder",
        title=title,
        notes=notes,
        due_at=None,
        remind_at=remind_at,
        timezone_name=timezone_name,
        priority=priority,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
    )


async def update_thread_links(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    additions: dict[str, list[UUID]],
    removals: dict[str, list[UUID]],
    link_type: str,
    screen: str,
    source_type: str = "frontend_manual",
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    fact, links = await thread_service.update_thread_links_data(
        database,
        user_id=user_id,
        item_id=item_id,
        additions=additions,
        removals=removals,
        link_type=link_type,
        screen=screen,
        source_type=source_type,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        now_naive=_now_naive,
        refresh_operational_row=_refresh_operational_row,
    )
    return {
        "thread": _canonical_item(source_kind="confirmed_fact", row=fact, item_class="thread"),
        "links": [_serialize_fact_link(link) for link in links],
    }


async def explain_thread(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any]:
    data = await thread_service.explain_thread_data(
        database,
        user_id=user_id,
        item_id=item_id,
        kind_for_row=_kind_for_row,
        fact_item_status=_fact_item_status,
    )
    fact = data["fact"]
    return {
        "id": str(fact["id"]),
        "title": fact.get("content", {}).get("title"),
        "summary": fact.get("content", {}).get("summary"),
        "thread_type": data["thread_type"],
        "actionability": data["actionability"],
        "next_move": data["next_move"],
        "evidence_preview": data["evidence_preview"],
        "source_refs": data["source_refs"],
        "linked_facts": data["linked_facts"],
        "linked_events": data["linked_events"],
        "linked_sources": data["linked_sources"],
        "why_open": data["why_open"],
        "why_now": data["why_now"],
        "confidence": data["confidence"],
    }


async def create_avoid_topic_memory(database: Database, *, user_id: str, note: str) -> dict[str, Any]:
    return await memory_control_service.create_avoid_topic_memory(database, user_id=user_id, note=note)


async def apply_memory_control(
    database: Database,
    *,
    user_id: str,
    action: str,
    target_id: UUID | None,
    target_type: str,
    note: str | None,
) -> dict[str, Any]:
    return await memory_control_service.apply_memory_control(
        database,
        user_id=user_id,
        action=action,
        target_id=target_id,
        target_type=target_type,
        note=note,
    )


async def ensure_user_item_visible(database: Database, *, user_id: str, item_id: UUID, allowed_fact_types: list[str], allowed_candidate_types: list[str]) -> None:
    await operational_read_service.ensure_user_item_visible(
        database,
        user_id=user_id,
        item_id=item_id,
        allowed_fact_types=allowed_fact_types,
        allowed_candidate_types=allowed_candidate_types,
    )


async def source_archive_count(database: Database, *, user_id: str) -> int:
    return await operational_read_service.source_archive_count(database, user_id=user_id)
