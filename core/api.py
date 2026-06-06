from __future__ import annotations

from typing import Any, AsyncIterator
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.db import Database
from core.items import (
    active_habits,
    apply_memory_control,
    create_action,
    create_event,
    due_tasks,
    habit_completion_status,
    list_actions,
    list_events,
    open_threads,
    pending_reminders,
    record_habit_completion,
    resolve_thread,
    sophie_cancel_confirmed_event,
    sophie_create_confirmed_action,
    sophie_create_confirmed_event,
    sophie_delete_confirmed_action,
    sophie_patch_confirmed_action,
    sophie_patch_confirmed_event,
    todays_schedule,
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
    request: HabitCompletionRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await record_habit_completion(
        database,
        user_id=request.user_id,
        item_id=UUID(item_id),
        completed_at=request.completed_at,
        status=request.status,
    )


@app.patch("/v3/threads/{item_id}/resolve")
async def patch_thread_resolve(
    item_id: str,
    user_id: str,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await resolve_thread(database, user_id=user_id, item_id=UUID(item_id))


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
