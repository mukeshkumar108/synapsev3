from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from agent_contract import AgentInput, AgentOutput, Participant, TranscriptTurn
from agents import (
    event_agent,
    fact_agent,
    session_summary_agent,
    state_agent,
    task_agent,
    thread_agent,
    triage_agent,
)
from core.candidates import candidate_records_from_outputs, candidate_signature, fetch_candidates_for_source, persist_candidate_records
from core.db import Database
from core import embeddings
from core import reconciliation
from core import source_archive


def format_session_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, message in enumerate(messages):
        role = str(message.get("role", "user")).strip().lower()
        label = "User" if role == "user" else "Sophie" if role == "assistant" else role.title()
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"[Turn {i}] {label}: {content}")
    return "\n".join(lines)


def _outbox_preview(raw_content: str) -> str | None:
    if not raw_content:
        return None
    first_line = raw_content.splitlines()[0].strip()
    if not first_line:
        return None
    return first_line[:240]


def _context_from_messages(
    messages: list[dict[str, Any]],
    *,
    timezone_name: str,
    received_at: datetime,
) -> dict[str, Any]:
    latest_timestamp = None
    for message in reversed(messages):
        timestamp = message.get("timestamp")
        if isinstance(timestamp, str) and timestamp.strip():
            latest_timestamp = timestamp
            break
    current_dt = latest_timestamp or received_at.replace(tzinfo=timezone.utc).isoformat()
    current_date = current_dt.split("T", 1)[0]
    return {
        "current_date": current_date,
        "current_datetime": current_dt,
        "timezone": timezone_name,
    }


def _occurred_at_from_messages(messages: list[dict[str, Any]]) -> datetime | None:
    for message in messages:
        timestamp = message.get("timestamp")
        if isinstance(timestamp, str) and timestamp.strip():
            normalized = timestamp.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                return parsed
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return None


def _source_context(outbox_row: dict[str, Any], *, raw_content: str, source_row: dict[str, Any] | None) -> dict[str, Any]:
    metadata = outbox_row.get("metadata") or {}
    archive_metadata = (source_row or {}).get("metadata") or {}
    return {
        "source_type": outbox_row.get("source_type") or metadata.get("source_type") or archive_metadata.get("source_type") or "chat",
        "original_text": raw_content,
        "who_said_it": metadata.get("who_said_it") or archive_metadata.get("who_said_it") or "user",
        "channel": metadata.get("channel") or archive_metadata.get("channel") or outbox_row.get("source_type") or "chat",
        "conversation_id": metadata.get("conversation_id") or archive_metadata.get("conversation_id"),
        "created_from": {
            "pipeline": "session_ingest",
            "outbox_id": str(outbox_row["id"]),
            "source_archive_id": str(source_row["id"]) if source_row else metadata.get("source_archive_id"),
        },
    }


def _agent_input(outbox_row: dict[str, Any], *, raw_content: str, messages: list[dict[str, Any]]) -> AgentInput:
    metadata = outbox_row.get("metadata") or {}
    timezone_name = metadata.get("timezone", "UTC")
    received_at = outbox_row.get("received_at") or datetime.now(timezone.utc).replace(tzinfo=None)
    context = _context_from_messages(messages, timezone_name=timezone_name, received_at=received_at)

    participants = [
        Participant(id="user", name="User", role="user"),
        Participant(id="sophie", name="Sophie", role="assistant"),
    ]

    turns: list[TranscriptTurn] = []
    for i, message in enumerate(messages):
        role = str(message.get("role", "user")).strip().lower()
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        speaker_id = "sophie" if role == "assistant" else "user"
        turns.append(
            TranscriptTurn(
                index=i,
                speaker_id=speaker_id,
                content=content,
                source_message_id=message.get("id"),
            )
        )

    interaction_mode = metadata.get("interaction_mode", "real_life")

    return AgentInput(
        user_id=outbox_row["user_id"],
        source_type=outbox_row["source_type"],
        raw_content=raw_content,
        interaction_mode=interaction_mode,
        participants=participants,
        turns=turns,
        context=context,
    )


def _extraction_outputs(agent_input: AgentInput, triage_output: AgentOutput) -> list[AgentOutput]:
    item = triage_output.items[0] if triage_output.items else {}
    outputs: list[AgentOutput] = []
    if item.get("has_tasks"):
        outputs.append(task_agent.run(agent_input))
    if item.get("has_events") or item.get("has_invitations"):
        outputs.append(event_agent.run(agent_input))
    if item.get("has_facts"):
        outputs.append(fact_agent.run(agent_input))
    if item.get("has_state_change"):
        outputs.append(state_agent.run(agent_input))
    if item.get("has_threads"):
        outputs.append(thread_agent.run(agent_input))
    return outputs


async def create_session_outbox(
    database: Database,
    *,
    user_id: str,
    session_id: str,
    messages: list[dict[str, Any]],
    source_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    received_at = datetime.now(timezone.utc).replace(tzinfo=None)
    outbox_id = uuid4()
    raw_content = format_session_transcript(messages)
    payload = {
        "messages": messages,
        "raw_content": raw_content,
    }
    archive_metadata = {
        **(metadata or {}),
        "source_type": "chat",
        "session_id": session_id,
    }
    source_row = await source_archive.create_or_reuse_session_archive(
        database,
        user_id=user_id,
        session_id=session_id,
        payload=payload,
        metadata=archive_metadata,
        conversation_id=(metadata or {}).get("conversation_id"),
        occurred_at=_occurred_at_from_messages(messages),
        captured_at=received_at,
    )
    preview = _outbox_preview(raw_content)
    stored_metadata = {
        **archive_metadata,
        "source_archive_id": str(source_row["id"]),
        "source_ref": str(source_row["id"]),
    }
    await database.execute(
        """
        INSERT INTO outbox (
            id, user_id, source_type, raw_content, received_at, status, retry_count, source_archive_id, metadata
        ) VALUES ($1, $2, $3::outbox_source_type, $4, $5, $6::outbox_status, $7, $8, $9::jsonb)
        """,
        outbox_id,
        user_id,
        source_type,
        preview,
        received_at,
        "pending",
        0,
        source_row["id"],
        stored_metadata,
    )
    return {
        "outbox_id": outbox_id,
        "raw_content": preview,
        "received_at": received_at,
        "source_archive_id": source_row["id"],
    }


async def _fetch_outbox_row(database: Database, *, outbox_id: UUID) -> dict[str, Any] | None:
    return await database.fetchone(
        """
        SELECT *
        FROM outbox
        WHERE id = $1
        """,
        outbox_id,
    )


async def _load_source_material(
    database: Database,
    *,
    outbox_row: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    source_archive_id = outbox_row.get("source_archive_id")
    if source_archive_id:
        source_row = await source_archive.get_source_archive_for_user(
            database,
            source_archive_id=source_archive_id,
            user_id=outbox_row["user_id"],
        )
        if source_row:
            payload = source_row.get("payload") or {}
            messages = payload.get("messages") or []
            raw_content = payload.get("raw_content")
            if not raw_content and messages:
                raw_content = format_session_transcript(messages)
            return raw_content or "", messages, source_row
    metadata = outbox_row.get("metadata") or {}
    messages = metadata.get("messages") or []
    return outbox_row.get("raw_content") or format_session_transcript(messages), messages, None


async def _update_outbox_status(database: Database, *, outbox_id: UUID, status: str) -> None:
    await database.execute(
        """
        UPDATE outbox
        SET status = $2::outbox_status
        WHERE id = $1
        """,
        outbox_id,
        status,
    )


async def _insert_session_summary(
    database: Database,
    *,
    outbox_row: dict[str, Any],
    summary_output: AgentOutput,
    occurred_at: datetime,
) -> UUID | None:
    if summary_output.status != "success" or not summary_output.items:
        return None
    existing = await database.fetchone(
        """
        SELECT *
        FROM session_summaries
        WHERE source_id = $1
        """,
        outbox_row["id"],
    )
    if existing:
        await embeddings.index_session_summary(database, existing)
        return existing["id"]
    item = summary_output.items[0]
    summary_id = uuid4()
    summary_row = {
        "id": summary_id,
        "user_id": outbox_row["user_id"],
        "source_id": outbox_row["id"],
        "summary": item["summary"],
        "tags": item["tags"],
        "open_items": item["open_items"],
        "key_decisions": item["key_decisions"],
        "emotional_tone": item["emotional_tone"],
        "occurred_at": occurred_at,
    }
    await database.execute(
        """
        INSERT INTO session_summaries (
            id, user_id, source_id, summary, tags, open_items, key_decisions, emotional_tone, occurred_at
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
        """,
        summary_row["id"],
        summary_row["user_id"],
        summary_row["source_id"],
        summary_row["summary"],
        summary_row["tags"],
        summary_row["open_items"],
        summary_row["key_decisions"],
        summary_row["emotional_tone"],
        summary_row["occurred_at"],
    )
    await embeddings.index_session_summary(database, summary_row)
    timeline_row = {
        "id": uuid4(),
        "user_id": outbox_row["user_id"],
        "event_type": "session",
        "timeline_type": "interaction",
        "title": "Session summary",
        "summary": item["summary"],
        "occurred_at": occurred_at,
        "observed_at": occurred_at,
        "source_id": outbox_row["id"],
        "related_fact_ids": [],
        "status": "current",
        "confidence": 1.0,
    }
    await database.execute(
        """
        INSERT INTO timeline_events (
            id, user_id, event_type, timeline_type, title, summary,
            occurred_at, observed_at, source_id, related_fact_ids, status, confidence
        ) VALUES (
            $1, $2, $3::event_type, $4::timeline_type, $5, $6,
            $7, $8, $9, $10, $11::timeline_status, $12
        )
        """,
        timeline_row["id"],
        timeline_row["user_id"],
        timeline_row["event_type"],
        timeline_row["timeline_type"],
        timeline_row["title"],
        timeline_row["summary"],
        timeline_row["occurred_at"],
        timeline_row["observed_at"],
        timeline_row["source_id"],
        timeline_row["related_fact_ids"],
        timeline_row["status"],
        timeline_row["confidence"],
    )
    await embeddings.index_timeline_event(database, timeline_row)
    return summary_id


async def run_pipeline_for_outbox(
    database: Database,
    *,
    outbox_id: UUID,
) -> dict[str, Any]:
    outbox_row = await _fetch_outbox_row(database, outbox_id=outbox_id)
    if not outbox_row:
        raise ValueError(f"Outbox row not found: {outbox_id}")

    await _update_outbox_status(database, outbox_id=outbox_id, status="processing")
    raw_content, messages, source_row = await _load_source_material(database, outbox_row=outbox_row)
    agent_input = _agent_input(outbox_row, raw_content=raw_content, messages=messages)
    occurred_at = outbox_row.get("received_at") or datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        summary_output = session_summary_agent.run(agent_input)
        await _insert_session_summary(
            database,
            outbox_row=outbox_row,
            summary_output=summary_output,
            occurred_at=occurred_at,
        )

        triage_output = triage_agent.run(agent_input)
        extraction_outputs = _extraction_outputs(agent_input, triage_output)
        candidate_records = candidate_records_from_outputs(
            user_id=agent_input.user_id,
            source_id=outbox_row["id"],
            outputs=extraction_outputs,
            created_at=occurred_at,
            interaction_mode=agent_input.interaction_mode,
            source_context=_source_context(outbox_row, raw_content=raw_content, source_row=source_row),
        )
        existing_source_candidates = await fetch_candidates_for_source(database, source_id=outbox_row["id"])
        existing_by_signature = {candidate_signature(record): record for record in existing_source_candidates}
        new_records: list[dict[str, Any]] = []
        candidates_to_process: list[dict[str, Any]] = []
        for record in candidate_records:
            existing = existing_by_signature.get(candidate_signature(record))
            if existing:
                if existing.get("status") == "pending":
                    candidates_to_process.append(existing)
                continue
            new_records.append(record)
            candidates_to_process.append(record)
            existing_by_signature[candidate_signature(record)] = record

        await persist_candidate_records(database, new_records)

        instructions = await reconciliation.reconcile_candidates(
            database,
            candidates=candidates_to_process,
        )
        await reconciliation.apply_reconciliation_results(
            database,
            candidates=candidates_to_process,
            instructions=instructions,
            now=datetime.now(timezone.utc),
        )
        await _update_outbox_status(database, outbox_id=outbox_id, status="done")
        return {
            "outbox_id": str(outbox_id),
            "session_summary_status": summary_output.status,
            "triage_status": triage_output.status,
            "candidate_count": len(candidates_to_process),
            "instruction_count": len(instructions),
            "status": "done",
        }
    except Exception:
        await _update_outbox_status(database, outbox_id=outbox_id, status="failed")
        raise


async def _run_pipeline_with_new_database(
    *,
    outbox_id: UUID,
    database_factory: Callable[[], Database],
) -> None:
    database = database_factory()
    try:
        await run_pipeline_for_outbox(database, outbox_id=outbox_id)
    finally:
        await database.close()


def schedule_pipeline_run(
    *,
    outbox_id: UUID,
    database_factory: Callable[[], Database] = Database,
) -> asyncio.Task[Any]:
    return asyncio.create_task(
        _run_pipeline_with_new_database(outbox_id=outbox_id, database_factory=database_factory)
    )
