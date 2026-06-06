from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from agent_contract import AgentOutput
from core.db import Database
from core.operational import extract_operational_fields, normalize_provenance, parse_datetime


def candidate_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    content = record["content"]
    return (
        record["candidate_type"],
        record["raw_evidence"],
        content.get("title"),
        content.get("summary"),
    )


def _pick_first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _candidate_type_for(agent_name: str, item: dict[str, Any]) -> str:
    if agent_name == "task_agent":
        if item.get("is_habit"):
            return "habit"
        if item.get("reminder_at") and not item.get("due_date"):
            return "reminder"
        return "task"
    if agent_name == "event_agent":
        return "invitation" if item.get("is_invitation") else "event"
    if agent_name == "fact_agent":
        return "fact"
    if agent_name == "state_agent":
        return "state"
    if agent_name == "thread_agent":
        return "thread"
    raise ValueError(f"Unsupported agent for candidate mapping: {agent_name}")


def _needs_confirmation(item: dict[str, Any]) -> bool:
    value = item.get("needs_confirmation")
    return bool(value) if value is not None else False


def _importance(item: dict[str, Any]) -> Any:
    return _pick_first(item, "importance", "priority", "salience")


def _title_for(candidate_type: str, item: dict[str, Any]) -> Any:
    if candidate_type == "fact":
        return _pick_first(item, "subject", "person_name")
    return _pick_first(item, "title")


def _summary_for(candidate_type: str, item: dict[str, Any]) -> Any:
    if candidate_type in {"task", "reminder", "habit"}:
        return _pick_first(item, "description")
    if candidate_type == "fact":
        return _pick_first(item, "content")
    if candidate_type == "state":
        return _pick_first(item, "current_focus")
    return _pick_first(item, "summary", "description")


def _open_loop_status(candidate_type: str, item: dict[str, Any]) -> Any:
    explicit = item.get("open_loop_status")
    if explicit is not None:
        return explicit
    if candidate_type == "thread":
        return "active"
    return None


def _normalize_content(candidate_type: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "item_type": "task" if candidate_type in {"habit", "reminder"} else candidate_type,
        "title": _title_for(candidate_type, item),
        "summary": _summary_for(candidate_type, item),
        "salience": item.get("salience"),
        "priority": item.get("priority"),
        "urgency": item.get("urgency"),
        "importance": _importance(item),
        "sensitivity": item.get("sensitivity"),
        "time": {
            "due_date": item.get("due_date"),
            "reminder_at": item.get("reminder_at"),
            "date": item.get("date"),
            "time": item.get("time"),
            "duration": item.get("duration"),
            "starts_at": item.get("starts_at") or item.get("time"),
            "ends_at": item.get("ends_at"),
            "timezone": item.get("timezone"),
            "recurrence_rule": item.get("recurrence"),
            "follow_up_after_hours": item.get("follow_up_after_hours"),
            "stale_after_hours": item.get("stale_after_hours"),
            "expires_at": item.get("expires_at"),
        },
        "links": {
            "people": item.get("related_people", []),
            "projects": item.get("related_projects", []),
            "topics": item.get("related_topics", []),
            "related_facts": item.get("related_facts", []),
            "related_threads": item.get("related_threads", []),
        },
        "lifecycle": {
            "follow_up_after_hours": item.get("follow_up_after_hours"),
            "stale_after_hours": item.get("stale_after_hours"),
            "expires_at": item.get("expires_at"),
        },
        "evidence": {
            "raw_evidence": item["raw_evidence"],
            "source_turn_refs": item.get("source_turn_refs", []),
        },
        "metadata": {
            "companion_category": item.get("companion_category"),
            "open_loop_status": _open_loop_status(candidate_type, item),
            "last_status": item.get("last_status"),
            "follow_up_question": item.get("follow_up_question"),
            "involves": item.get("involves", []),
            "waiting_on": item.get("waiting_on"),
            "last_surfaced_at": item.get("last_surfaced_at"),
            "agent_item": item,
        },
    }


def build_candidate_record(
    *,
    user_id: str,
    source_id: UUID,
    agent_name: str,
    item: dict[str, Any],
    created_at: datetime | None = None,
    interaction_mode: str = "real_life",
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = (created_at or datetime.now(timezone.utc)).replace(tzinfo=None)
    candidate_type = _candidate_type_for(agent_name, item)
    content = _normalize_content(candidate_type, item)
    provenance = normalize_provenance(
        source_id=source_id,
        source_type=(source_context or {}).get("source_type"),
        original_text=(source_context or {}).get("original_text") or item.get("raw_evidence"),
        who_said_it=(source_context or {}).get("who_said_it"),
        channel=(source_context or {}).get("channel"),
        conversation_id=(source_context or {}).get("conversation_id"),
        created_from=(source_context or {}).get("created_from"),
        source_ids=[source_id],
    )
    operational = extract_operational_fields(
        item_type=candidate_type,
        content=content,
        provenance=provenance,
        record_status="pending",
    )
    return {
        "id": uuid4(),
        "user_id": user_id,
        "source_id": source_id,
        "candidate_type": candidate_type,
        "fact_type": candidate_type,
        "content": content,
        "structured_content": operational["structured_content"],
        "raw_evidence": item["raw_evidence"],
        "confidence": float(item["confidence"]),
        "needs_confirmation": _needs_confirmation(item),
        "status": "pending",
        "reconciliation_instruction": None,
        "merge_target_id": None,
        "created_at": timestamp,
        "starts_at": operational["starts_at"],
        "ends_at": operational["ends_at"],
        "due_at": operational["due_at"],
        "remind_at": operational["remind_at"],
        "timezone": operational["timezone"],
        "recurrence_rule": operational["recurrence_rule"],
        "completed_at": operational["completed_at"],
        "cancelled_at": operational["cancelled_at"],
        "priority": operational["priority"],
        "source_type": operational["source_type"],
        "who_said_it": operational["who_said_it"],
        "original_text": operational["original_text"],
        "channel": operational["channel"],
        "conversation_id": operational["conversation_id"],
        "created_from": operational["created_from"],
        "provenance": operational["provenance"],
        "follow_up_needed": operational["follow_up_needed"],
        "claimed_by_entity_id": item.get("claimed_by_entity_id"),
        "subject_entity_id": item.get("subject_entity_id"),
        "claim_type": item.get("claim_type", "direct"),
        "claim_status": "pending",
        "interaction_mode": interaction_mode,
    }


async def persist_candidate_records(
    database: Database,
    records: list[dict[str, Any]],
) -> None:
    for record in records:
        await database.execute(
            """
            INSERT INTO candidates (
                id,
                user_id,
                source_id,
                candidate_type,
                fact_type,
                content,
                structured_content,
                raw_evidence,
                confidence,
                needs_confirmation,
                status,
                reconciliation_instruction,
                merge_target_id,
                created_at,
                starts_at,
                ends_at,
                due_at,
                remind_at,
                timezone,
                recurrence_rule,
                completed_at,
                cancelled_at,
                priority,
                source_type,
                who_said_it,
                original_text,
                channel,
                conversation_id,
                created_from,
                provenance,
                follow_up_needed,
                claimed_by_entity_id,
                subject_entity_id,
                claim_type,
                claim_status,
                interaction_mode
            ) VALUES (
                $1, $2, $3, $4::candidate_type, $5::fact_type, $6::jsonb, $7::jsonb, $8, $9, $10,
                $11::candidate_status, $12::reconciliation_instruction, $13, $14,
                $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28::jsonb, $29::jsonb, $30,
                $31, $32, $33, $34, $35
            )
            """,
            record["id"],
            record["user_id"],
            record["source_id"],
            record["candidate_type"],
            record.get("fact_type"),
            record["content"],
            record.get("structured_content"),
            record["raw_evidence"],
            record["confidence"],
            record["needs_confirmation"],
            record["status"],
            record["reconciliation_instruction"],
            record["merge_target_id"],
            record["created_at"],
            parse_datetime(record.get("starts_at")).replace(tzinfo=None) if parse_datetime(record.get("starts_at")) else None,
            parse_datetime(record.get("ends_at")).replace(tzinfo=None) if parse_datetime(record.get("ends_at")) else None,
            parse_datetime(record.get("due_at")).replace(tzinfo=None) if parse_datetime(record.get("due_at")) else None,
            parse_datetime(record.get("remind_at")).replace(tzinfo=None) if parse_datetime(record.get("remind_at")) else None,
            record.get("timezone"),
            record.get("recurrence_rule"),
            parse_datetime(record.get("completed_at")).replace(tzinfo=None) if parse_datetime(record.get("completed_at")) else None,
            parse_datetime(record.get("cancelled_at")).replace(tzinfo=None) if parse_datetime(record.get("cancelled_at")) else None,
            record.get("priority"),
            record.get("source_type"),
            record.get("who_said_it"),
            record.get("original_text"),
            record.get("channel"),
            record.get("conversation_id"),
            record.get("created_from") or {},
            record.get("provenance") or {},
            record.get("follow_up_needed", False),
            record.get("claimed_by_entity_id"),
            record.get("subject_entity_id"),
            record.get("claim_type", "direct"),
            record.get("claim_status", "pending"),
            record.get("interaction_mode", "real_life"),
        )


async def fetch_candidates_for_source(
    database: Database,
    *,
    source_id: UUID,
) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM candidates
        WHERE source_id = $1
        ORDER BY created_at, id
        """,
        source_id,
    )


def candidate_records_from_outputs(
    *,
    user_id: str,
    source_id: UUID,
    outputs: list[AgentOutput],
    created_at: datetime | None = None,
    interaction_mode: str = "real_life",
    source_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for output in outputs:
        if output.status != "success":
            continue
        for item in output.items:
            if not isinstance(item, dict):
                raise ValueError(f"Agent item must be an object for persistence: {output.agent}")
            records.append(
                build_candidate_record(
                    user_id=user_id,
                    source_id=source_id,
                    agent_name=output.agent,
                    item=item,
                    created_at=created_at,
                    interaction_mode=interaction_mode,
                    source_context=source_context,
                )
            )
    return records
