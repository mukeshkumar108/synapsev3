from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI
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
    request: ItemCreateRequest,
    database: Database = Depends(get_database),
):
    return await create_action(
        database,
        user_id=request.user_id,
        title=request.title,
        summary=request.summary,
        due_at=request.due_at,
        priority=request.priority,
        links=request.links,
        source=request.source,
        requires_confirmation=request.requires_confirmation,
    )


@app.patch("/v3/actions/{item_id}")
async def patch_action(
    item_id: str,
    request: ActionPatchRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await update_action(
        database,
        item_id=UUID(item_id),
        user_id=request.user_id,
        status=request.status,
        title=request.title,
        summary=request.summary,
        due_at=request.due_at,
        priority=request.priority,
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
    request: ItemCreateRequest,
    database: Database = Depends(get_database),
):
    return await create_event(
        database,
        user_id=request.user_id,
        title=request.title,
        summary=request.summary,
        due_at=request.due_at,
        priority=request.priority,
        links=request.links,
        source=request.source,
    )


@app.patch("/v3/events/{item_id}")
async def patch_event(
    item_id: str,
    request: EventPatchRequest,
    database: Database = Depends(get_database),
):
    from uuid import UUID

    return await update_event(
        database,
        item_id=UUID(item_id),
        user_id=request.user_id,
        status=request.status,
        title=request.title,
        summary=request.summary,
        due_at=request.due_at,
        priority=request.priority,
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
