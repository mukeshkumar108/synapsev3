from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.db import Database
from core.items import (
    active_habits,
    apply_memory_control,
    archive_habit_manual,
    archive_reminder_manual,
    archive_task_manual,
    complete_task_manual,
    convert_thread_to_reminder,
    convert_thread_to_task,
    create_action,
    create_event,
    create_habit_manual,
    create_reminder_manual,
    create_task_manual,
    dismiss_thread,
    delete_event_manual,
    due_tasks,
    explain_thread,
    get_event_manual,
    get_habit_manual,
    get_reminder_manual,
    get_task_manual,
    habit_completion_status,
    list_actions,
    list_events,
    list_habits_manual,
    list_reminders_manual,
    list_tasks_manual,
    open_threads,
    pending_reminders,
    dismiss_reminder_manual,
    record_habit_completion,
    resolve_thread,
    snooze_thread,
    sophie_cancel_confirmed_event,
    sophie_create_confirmed_action,
    sophie_create_confirmed_event,
    sophie_delete_confirmed_action,
    sophie_patch_confirmed_action,
    sophie_patch_confirmed_event,
    todays_schedule,
    update_thread_links,
    update_habit_manual,
    update_reminder_manual,
    update_task_manual,
    update_action,
    update_event,
)
from core import pipeline_runner
from core.recall import recall
from core.serving import build_daily_overview, build_instruction_packet, ingest_outbox, query_memory


app = FastAPI(title="Synapse V3")


class MemoryQueryRequest(BaseModel):
    user_id: str
    query_text: str


class RecallRequest(BaseModel):
    user_id: str
    query: str
    limit: int = 5
    recall_type: str | None = None


class OutboxIngestRequest(BaseModel):
    user_id: str
    source_type: str
    raw_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class SessionIngestRequest(BaseModel):
    user_id: str
    session_id: str
    messages: list[SessionMessage]
    source_type: str = "chat"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ItemCreateRequest(BaseModel):
    user_id: str
    title: str
    summary: str
    due_at: str | None = None
    priority: str | None = None
    links: dict[str, Any] = Field(default_factory=dict)
    source: str = "sophie_runtime"
    requires_confirmation: bool = True


class ActionPatchRequest(BaseModel):
    user_id: str
    status: str
    title: str | None = None
    summary: str | None = None
    due_at: str | None = None
    priority: str | None = None


class EventPatchRequest(BaseModel):
    user_id: str
    status: str
    title: str | None = None
    summary: str | None = None
    due_at: str | None = None
    priority: str | None = None


class HabitCompletionRequest(BaseModel):
    user_id: str
    completed_at: str
    status: str = "habit_completed"


class MemoryControlRequest(BaseModel):
    user_id: str
    action: str
    target_id: str | None = None
    target_type: str
    note: str | None = None


class FrontendManualCreateRequest(BaseModel):
    tenantId: str | None = None
    userId: str
    title: str
    notes: str | None = None
    dueAt: str | None = None
    remindAt: str | None = None
    startsAt: str | None = None
    endsAt: str | None = None
    timezone: str | None = None
    location: str | None = None
    participants: list[str] = Field(default_factory=list)
    priority: str | None = None
    sourceType: str | None = None
    sourceRef: str | None = None
    idempotencyKey: str
    createdFrom: str
    cadence: str | None = None


class FrontendManualPatchRequest(BaseModel):
    userId: str
    title: str | None = None
    notes: str | None = None
    dueAt: str | None = None
    remindAt: str | None = None
    startsAt: str | None = None
    endsAt: str | None = None
    timezone: str | None = None
    location: str | None = None
    participants: list[str] | None = None
    priority: str | None = None
    sourceType: str | None = None
    sourceRef: str | None = None
    idempotencyKey: str | None = None
    createdFrom: str
    completedAt: str | None = None
    cadence: str | None = None


class FrontendManualMutationRequest(BaseModel):
    userId: str
    sourceType: str | None = None
    sourceRef: str | None = None
    idempotencyKey: str | None = None
    createdFrom: str
    completedAt: str | None = None


class ThreadSnoozeRequest(FrontendManualMutationRequest):
    snoozedUntil: str


class ThreadConvertRequest(FrontendManualMutationRequest):
    title: str | None = None
    notes: str | None = None
    dueAt: str | None = None
    remindAt: str | None = None
    timezone: str | None = None
    priority: str | None = None


class ThreadLinksObject(BaseModel):
    factIds: list[str] = Field(default_factory=list)
    timelineEventIds: list[str] = Field(default_factory=list)
    sourceArchiveIds: list[str] = Field(default_factory=list)
    outboxIds: list[str] = Field(default_factory=list)


class ThreadLinksPatchRequest(FrontendManualMutationRequest):
    linkType: str = "relates_to"
    add: ThreadLinksObject = Field(default_factory=ThreadLinksObject)
    remove: ThreadLinksObject = Field(default_factory=ThreadLinksObject)
    completedAt: str | None = None


def _is_sophie_confirmed_payload(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("tenantId", "userId", "sourceType", "sourceRef", "idempotencyKey"))


def _require_sophie_user_id(payload: dict[str, Any]) -> str:
    user_id = payload.get("userId") or payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=422, detail="userId is required.")
    return str(user_id)


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    return [str(item) for item in value]


async def get_database() -> AsyncIterator[Database]:
    database = Database()
    try:
        yield database
    finally:
        await database.close()


def schedule_session_pipeline(outbox_id):
    pipeline_runner.schedule_pipeline_run(outbox_id=outbox_id, database_factory=Database)


@app.get("/health")
@app.get("/v3/health")
async def health_check():
    return {"status": "ok", "service": "synapse-v3"}


@app.get("/v3/sessions/instruction-packet")
async def get_instruction_packet(
    user_id: str,
    current_datetime: str | None = None,
    timezone: str = "UTC",
    database: Database = Depends(get_database),
):
    return await build_instruction_packet(
        database,
        user_id=user_id,
        current_datetime=current_datetime,
        timezone_name=timezone,
    )


@app.get("/v3/overview/daily")
async def get_daily_overview(
    user_id: str,
    date: str | None = None,
    timezone: str = "UTC",
    database: Database = Depends(get_database),
):
    return await build_daily_overview(
        database,
        user_id=user_id,
        day=date,
        timezone_name=timezone,
    )


@app.post("/v3/memory/query")
async def post_memory_query(
    request: MemoryQueryRequest,
    database: Database = Depends(get_database),
):
    return await query_memory(
        database,
        user_id=request.user_id,
        query_text=request.query_text,
    )


@app.post("/v3/recall")
async def post_recall(
    request: RecallRequest,
    database: Database = Depends(get_database),
):
    return await recall(
        database,
        user_id=request.user_id,
        query=request.query,
        limit=request.limit,
        recall_type=request.recall_type,
    )


@app.post("/v3/outbox/ingest")
async def post_outbox_ingest(
    request: OutboxIngestRequest,
    database: Database = Depends(get_database),
):
    return await ingest_outbox(
        database,
        user_id=request.user_id,
        source_type=request.source_type,
        raw_content=request.raw_content,
        metadata=request.metadata,
    )


@app.post("/v3/session/ingest")
async def post_session_ingest(
    request: SessionIngestRequest,
    database: Database = Depends(get_database),
):
    result = await pipeline_runner.create_session_outbox(
        database,
        user_id=request.user_id,
        session_id=request.session_id,
        messages=[message.model_dump() for message in request.messages],
        source_type=request.source_type,
        metadata=request.metadata,
    )
    schedule_session_pipeline(result["outbox_id"])
    return {
        "success": True,
        "outbox_id": str(result["outbox_id"]),
        "status": "processing",
    }


@app.get("/v3/actions")
async def get_actions(
    user_id: str,
    status: str = "active",
    limit: int = 20,
    database: Database = Depends(get_database),
):
    return await list_actions(database, user_id=user_id, status=status, limit=limit)


@app.get("/v3/tasks")
async def get_tasks(
    user_id: str | None = None,
    userId: str | None = None,
    database: Database = Depends(get_database),
):
    return await list_tasks_manual(database, user_id=str(user_id or userId))


@app.post("/v3/tasks")
async def post_tasks_manual(
    request: FrontendManualCreateRequest,
    database: Database = Depends(get_database),
):
    return await create_task_manual(
        database,
        user_id=request.userId,
        title=request.title,
        notes=request.notes,
        due_at=request.dueAt,
        timezone_name=request.timezone,
        priority=request.priority,
        screen=request.createdFrom,
        idempotency_key=request.idempotencyKey,
        tenant_id=request.tenantId,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
    )


@app.get("/v3/tasks/{item_id}")
async def get_task_detail(
    item_id: str,
    user_id: str | None = None,
    userId: str | None = None,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await get_task_manual(database, user_id=str(user_id or userId), item_id=UUID(item_id))


@app.patch("/v3/tasks/{item_id}")
async def patch_task_manual(
    item_id: str,
    request: FrontendManualPatchRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await update_task_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        title=request.title,
        notes=request.notes,
        due_at=request.dueAt,
        timezone_name=request.timezone,
        priority=request.priority,
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.post("/v3/tasks/{item_id}/complete")
async def complete_task_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await complete_task_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
        completed_at=request.completedAt,
    )


@app.post("/v3/tasks/{item_id}/archive")
async def archive_task_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await archive_task_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.delete("/v3/tasks/{item_id}")
async def delete_task_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await archive_task_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.get("/v3/reminders")
async def get_reminders(
    user_id: str | None = None,
    userId: str | None = None,
    database: Database = Depends(get_database),
):
    return await list_reminders_manual(database, user_id=str(user_id or userId))


@app.post("/v3/reminders")
async def post_reminders_manual(
    request: FrontendManualCreateRequest,
    database: Database = Depends(get_database),
):
    return await create_reminder_manual(
        database,
        user_id=request.userId,
        title=request.title,
        notes=request.notes,
        remind_at=request.remindAt,
        timezone_name=request.timezone,
        priority=request.priority,
        screen=request.createdFrom,
        idempotency_key=request.idempotencyKey,
        tenant_id=request.tenantId,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
    )


@app.get("/v3/reminders/{item_id}")
async def get_reminder_detail(
    item_id: str,
    user_id: str | None = None,
    userId: str | None = None,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await get_reminder_manual(database, user_id=str(user_id or userId), item_id=UUID(item_id))


@app.patch("/v3/reminders/{item_id}")
async def patch_reminder_manual(
    item_id: str,
    request: FrontendManualPatchRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await update_reminder_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        title=request.title,
        notes=request.notes,
        remind_at=request.remindAt,
        timezone_name=request.timezone,
        priority=request.priority,
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.post("/v3/reminders/{item_id}/dismiss")
async def dismiss_reminder_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await dismiss_reminder_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.post("/v3/reminders/{item_id}/archive")
async def archive_reminder_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await archive_reminder_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.delete("/v3/reminders/{item_id}")
async def delete_reminder_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await archive_reminder_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.post("/v3/actions")
async def post_actions(
    request: dict[str, Any] = Body(...),
    database: Database = Depends(get_database),
):
    if _is_sophie_confirmed_payload(request):
        return await sophie_create_confirmed_action(
            database,
            user_id=_require_sophie_user_id(request),
            kind=str(request.get("kind") or "todo"),
            title=str(request.get("title") or ""),
            notes=request.get("notes"),
            due_at=request.get("dueAt"),
            remind_at=request.get("remindAt"),
            timezone_name=request.get("timezone"),
            source_type=str(request.get("sourceType") or "sophie_confirmed"),
            provenance_summary=request.get("provenanceSummary"),
            confidence=float(request.get("confidence") or 1.0),
            source_ref=request.get("sourceRef"),
            idempotency_key=str(request.get("idempotencyKey") or f"action:{request.get('sourceRef') or request.get('title') or uuid4()}"),
            original_text=request.get("originalText"),
            participants=_string_list(request.get("participants")),
            location=request.get("location"),
            tenant_id=request.get("tenantId"),
        )
    typed = ItemCreateRequest.model_validate(request)
    return await create_action(
        database,
        user_id=typed.user_id,
        title=typed.title,
        summary=typed.summary,
        due_at=typed.due_at,
        priority=typed.priority,
        links=typed.links,
        source=typed.source,
        requires_confirmation=typed.requires_confirmation,
    )


@app.patch("/v3/actions/{item_id}")
async def patch_action(
    item_id: str,
    request: dict[str, Any] = Body(...),
    database: Database = Depends(get_database),
):
    from uuid import UUID

    if _is_sophie_confirmed_payload(request):
        return await sophie_patch_confirmed_action(
            database,
            item_id=UUID(item_id),
            user_id=_require_sophie_user_id(request),
            title=request.get("title"),
            notes=request.get("notes"),
            due_at=request.get("dueAt"),
            remind_at=request.get("remindAt"),
            timezone_name=request.get("timezone"),
            source_type=str(request.get("sourceType") or "sophie_confirmed"),
            provenance_summary=request.get("provenanceSummary"),
            source_ref=request.get("sourceRef"),
            idempotency_key=request.get("idempotencyKey"),
            status=request.get("status"),
            completed_at=request.get("completedAt"),
        )
    typed = ActionPatchRequest.model_validate(request)
    return await update_action(
        database,
        item_id=UUID(item_id),
        user_id=typed.user_id,
        status=typed.status,
        title=typed.title,
        summary=typed.summary,
        due_at=typed.due_at,
        priority=typed.priority,
    )


@app.delete("/v3/actions/{item_id}")
async def delete_action(
    item_id: str,
    request: dict[str, Any] | None = Body(default=None),
    user_id: str | None = None,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    payload = request or {}
    effective_user_id = payload.get("userId") or payload.get("user_id") or user_id
    if not effective_user_id:
        raise HTTPException(status_code=422, detail="userId is required.")
    return await sophie_delete_confirmed_action(
        database,
        item_id=UUID(item_id),
        user_id=str(effective_user_id),
        idempotency_key=payload.get("idempotencyKey"),
    )


@app.get("/v3/events")
async def get_events(
    user_id: str,
    status: str = "active",
    limit: int = 20,
    database: Database = Depends(get_database),
):
    return await list_events(database, user_id=user_id, status=status, limit=limit)


@app.get("/v3/events/{item_id}")
async def get_event_detail(
    item_id: str,
    user_id: str | None = None,
    userId: str | None = None,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await get_event_manual(database, user_id=str(user_id or userId), item_id=UUID(item_id))


@app.post("/v3/events")
async def post_events(
    request: dict[str, Any] = Body(...),
    database: Database = Depends(get_database),
):
    if _is_sophie_confirmed_payload(request):
        return await sophie_create_confirmed_event(
            database,
            user_id=_require_sophie_user_id(request),
            title=str(request.get("title") or ""),
            notes=request.get("notes"),
            starts_at=request.get("startsAt"),
            ends_at=request.get("endsAt"),
            timezone_name=request.get("timezone"),
            location=request.get("location"),
            participants=_string_list(request.get("participants")),
            source_type=str(request.get("sourceType") or "sophie_confirmed"),
            provenance_summary=request.get("provenanceSummary"),
            confidence=float(request.get("confidence") or 1.0),
            source_ref=request.get("sourceRef"),
            idempotency_key=str(request.get("idempotencyKey") or f"event:{request.get('sourceRef') or request.get('title') or uuid4()}"),
            original_text=request.get("originalText"),
            tenant_id=request.get("tenantId"),
        )
    typed = ItemCreateRequest.model_validate(request)
    return await create_event(
        database,
        user_id=typed.user_id,
        title=typed.title,
        summary=typed.summary,
        due_at=typed.due_at,
        priority=typed.priority,
        links=typed.links,
        source=typed.source,
    )


@app.patch("/v3/events/{item_id}")
async def patch_event(
    item_id: str,
    request: dict[str, Any] = Body(...),
    database: Database = Depends(get_database),
):
    from uuid import UUID

    if _is_sophie_confirmed_payload(request):
        return await sophie_patch_confirmed_event(
            database,
            item_id=UUID(item_id),
            user_id=_require_sophie_user_id(request),
            title=request.get("title"),
            notes=request.get("notes"),
            starts_at=request.get("startsAt"),
            ends_at=request.get("endsAt"),
            timezone_name=request.get("timezone"),
            location=request.get("location"),
            participants=_string_list(request.get("participants")),
            source_type=str(request.get("sourceType") or "sophie_confirmed"),
            provenance_summary=request.get("provenanceSummary"),
            source_ref=request.get("sourceRef"),
            idempotency_key=request.get("idempotencyKey"),
        )
    typed = EventPatchRequest.model_validate(request)
    return await update_event(
        database,
        item_id=UUID(item_id),
        user_id=typed.user_id,
        status=typed.status,
        title=typed.title,
        summary=typed.summary,
        due_at=typed.due_at,
        priority=typed.priority,
    )


@app.post("/v3/events/{item_id}/cancel")
async def cancel_event(
    item_id: str,
    request: dict[str, Any] = Body(...),
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await sophie_cancel_confirmed_event(
        database,
        item_id=UUID(item_id),
        user_id=_require_sophie_user_id(request),
        idempotency_key=request.get("idempotencyKey"),
    )


@app.delete("/v3/events/{item_id}")
async def delete_event_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await delete_event_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.get("/v3/ops/schedule/today")
async def get_todays_schedule(
    user_id: str,
    day: str,
    database: Database = Depends(get_database),
):
    return await todays_schedule(database, user_id=user_id, day=day)


@app.get("/v3/ops/tasks/due")
async def get_due_tasks(
    user_id: str,
    now: str,
    database: Database = Depends(get_database),
):
    return await due_tasks(database, user_id=user_id, now=now)


@app.get("/v3/ops/reminders/pending")
async def get_pending_reminders(
    user_id: str,
    database: Database = Depends(get_database),
):
    return await pending_reminders(database, user_id=user_id)


@app.get("/v3/ops/habits/active")
async def get_active_habits(
    user_id: str,
    database: Database = Depends(get_database),
):
    return await active_habits(database, user_id=user_id)


@app.get("/v3/habits")
async def get_habits(
    user_id: str | None = None,
    userId: str | None = None,
    database: Database = Depends(get_database),
):
    return await list_habits_manual(database, user_id=str(user_id or userId))


@app.post("/v3/habits")
async def post_habits_manual(
    request: FrontendManualCreateRequest,
    database: Database = Depends(get_database),
):
    return await create_habit_manual(
        database,
        user_id=request.userId,
        title=request.title,
        notes=request.notes,
        timezone_name=request.timezone,
        priority=request.priority,
        cadence=request.cadence,
        screen=request.createdFrom,
        idempotency_key=request.idempotencyKey,
        tenant_id=request.tenantId,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
    )


@app.get("/v3/habits/{item_id}")
async def get_habit_detail(
    item_id: str,
    user_id: str | None = None,
    userId: str | None = None,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await get_habit_manual(database, user_id=str(user_id or userId), item_id=UUID(item_id))


@app.patch("/v3/habits/{item_id}")
async def patch_habit_manual(
    item_id: str,
    request: FrontendManualPatchRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await update_habit_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        title=request.title,
        notes=request.notes,
        timezone_name=request.timezone,
        priority=request.priority,
        cadence=request.cadence,
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.get("/v3/ops/habits/status")
async def get_habit_completion_status(
    user_id: str,
    day: str,
    database: Database = Depends(get_database),
):
    return await habit_completion_status(database, user_id=user_id, day=day)


@app.get("/v3/ops/threads/open")
async def get_open_threads(
    user_id: str,
    database: Database = Depends(get_database),
):
    return await open_threads(database, user_id=user_id)


@app.patch("/v3/habits/{item_id}/complete")
async def patch_habit_complete(
    item_id: str,
    request: dict[str, Any] = Body(...),
    database: Database = Depends(get_database),
):
    from uuid import UUID

    if "userId" in request:
        return await record_habit_completion(
            database,
            user_id=str(request["userId"]),
            item_id=UUID(item_id),
            completed_at=str(request.get("completedAt") or datetime.now(timezone.utc).isoformat()),
            status="habit_completed",
            source_type=str(request.get("sourceType") or "frontend_manual"),
            screen=str(request.get("createdFrom") or "habits_tab"),
            source_ref=request.get("sourceRef"),
            idempotency_key=request.get("idempotencyKey"),
        )
    typed = HabitCompletionRequest.model_validate(request)
    return await record_habit_completion(
        database,
        user_id=typed.user_id,
        item_id=UUID(item_id),
        completed_at=typed.completed_at,
        status=typed.status,
    )


@app.post("/v3/habits/{item_id}/archive")
async def archive_habit_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await archive_habit_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.delete("/v3/habits/{item_id}")
async def delete_habit_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await archive_habit_manual(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.patch("/v3/threads/{item_id}/resolve")
async def patch_thread_resolve(
    item_id: str,
    user_id: str,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await resolve_thread(database, user_id=user_id, item_id=UUID(item_id))


@app.post("/v3/threads/{item_id}/dismiss")
async def dismiss_thread_endpoint(
    item_id: str,
    request: FrontendManualMutationRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await dismiss_thread(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.post("/v3/threads/{item_id}/snooze")
async def snooze_thread_endpoint(
    item_id: str,
    request: ThreadSnoozeRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await snooze_thread(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        snoozed_until=request.snoozedUntil,
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.post("/v3/threads/{item_id}/convert-to-task")
async def convert_thread_to_task_endpoint(
    item_id: str,
    request: ThreadConvertRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await convert_thread_to_task(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        title=request.title,
        notes=request.notes,
        due_at=request.dueAt,
        timezone_name=request.timezone,
        priority=request.priority,
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey or f"thread-task:{item_id}",
    )


@app.post("/v3/threads/{item_id}/convert-to-reminder")
async def convert_thread_to_reminder_endpoint(
    item_id: str,
    request: ThreadConvertRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await convert_thread_to_reminder(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        title=request.title,
        notes=request.notes,
        remind_at=request.remindAt,
        timezone_name=request.timezone,
        priority=request.priority,
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey or f"thread-reminder:{item_id}",
    )


@app.patch("/v3/threads/{item_id}/links")
async def patch_thread_links_endpoint(
    item_id: str,
    request: ThreadLinksPatchRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await update_thread_links(
        database,
        user_id=request.userId,
        item_id=UUID(item_id),
        additions={
            "fact_ids": [UUID(value) for value in request.add.factIds],
            "timeline_event_ids": [UUID(value) for value in request.add.timelineEventIds],
            "source_archive_ids": [UUID(value) for value in request.add.sourceArchiveIds],
            "outbox_ids": [UUID(value) for value in request.add.outboxIds],
        },
        removals={
            "fact_ids": [UUID(value) for value in request.remove.factIds],
            "timeline_event_ids": [UUID(value) for value in request.remove.timelineEventIds],
            "source_archive_ids": [UUID(value) for value in request.remove.sourceArchiveIds],
            "outbox_ids": [UUID(value) for value in request.remove.outboxIds],
        },
        link_type=request.linkType,
        screen=request.createdFrom,
        source_type=request.sourceType or "frontend_manual",
        source_ref=request.sourceRef,
        idempotency_key=request.idempotencyKey,
    )


@app.get("/v3/threads/{item_id}/explanation")
async def get_thread_explanation(
    item_id: str,
    userId: str,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await explain_thread(database, user_id=userId, item_id=UUID(item_id))


@app.post("/v3/memory-controls")
async def post_memory_controls(
    request: MemoryControlRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await apply_memory_control(
        database,
        user_id=request.user_id,
        action=request.action,
        target_id=UUID(request.target_id) if request.target_id else None,
        target_type=request.target_type,
        note=request.note,
    )
