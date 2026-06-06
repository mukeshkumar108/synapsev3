from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException

from core import embeddings
from core.db import Database
from core.operational import apply_lifecycle_timestamp, extract_operational_fields, normalize_provenance, parse_datetime


ActionStatus = Literal["active", "completed", "dismissed", "stale", "all"]
EventStatus = Literal["active", "dismissed", "confirmed", "all"]
MemoryControlAction = Literal["forget", "correct", "avoid_topic", "dismiss", "resolve_loop"]


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive(value: str | None) -> datetime | None:
    parsed = parse_datetime(value)
    return parsed.replace(tzinfo=None) if parsed else None


def _row_provenance(
    *,
    source_id: UUID | None,
    source_ids: list[UUID] | None,
    source_type: str | None,
    original_text: str | None,
    who_said_it: str | None,
    channel: str | None,
    conversation_id: str | None,
    created_from: dict[str, Any] | None,
) -> dict[str, Any]:
    return normalize_provenance(
        source_id=source_id,
        source_type=source_type,
        original_text=original_text,
        who_said_it=who_said_it,
        channel=channel,
        conversation_id=conversation_id,
        created_from=created_from,
        source_ids=source_ids,
    )


def _kind_for_row(row: dict[str, Any]) -> str:
    structured = row.get("structured_content") or {}
    kind = structured.get("kind")
    if kind:
        return str(kind)
    fact_type = row.get("fact_type") or row.get("candidate_type")
    content = row.get("content") or {}
    metadata = content.get("metadata") or {}
    agent_item = metadata.get("agent_item") or {}
    if agent_item.get("is_habit"):
        return "habit"
    if fact_type == "task" and (content.get("time") or {}).get("reminder_at") and not (content.get("time") or {}).get("due_date"):
        return "reminder"
    return str(fact_type or content.get("item_type") or "fact")


def _refresh_operational_row(row: dict[str, Any], *, item_type: str, source_id: UUID | None, source_ids: list[UUID] | None = None) -> dict[str, Any]:
    provenance = _row_provenance(
        source_id=source_id,
        source_ids=source_ids,
        source_type=row.get("source_type"),
        original_text=row.get("original_text") or row.get("raw_evidence") or ((row.get("content") or {}).get("evidence") or {}).get("raw_evidence"),
        who_said_it=row.get("who_said_it"),
        channel=row.get("channel"),
        conversation_id=row.get("conversation_id"),
        created_from=row.get("created_from"),
    )
    operational = extract_operational_fields(
        item_type=item_type,
        content=row["content"],
        provenance=provenance,
        record_status=row.get("status"),
    )
    row["structured_content"] = operational["structured_content"]
    row["starts_at"] = _to_naive(operational["starts_at"])
    row["ends_at"] = _to_naive(operational["ends_at"])
    row["due_at"] = _to_naive(operational["due_at"])
    row["remind_at"] = _to_naive(operational["remind_at"])
    row["timezone"] = operational["timezone"]
    row["recurrence_rule"] = operational["recurrence_rule"]
    row["completed_at"] = _to_naive(operational["completed_at"])
    row["cancelled_at"] = _to_naive(operational["cancelled_at"])
    row["priority"] = operational["priority"]
    row["source_type"] = operational["source_type"]
    row["who_said_it"] = operational["who_said_it"]
    row["original_text"] = operational["original_text"]
    row["channel"] = operational["channel"]
    row["conversation_id"] = operational["conversation_id"]
    row["created_from"] = operational["created_from"]
    row["provenance"] = operational["provenance"]
    row["follow_up_needed"] = operational["follow_up_needed"]
    if source_ids is not None:
        row["source_ids"] = source_ids
        row["primary_source_id"] = source_ids[0] if source_ids else None
    return row


def _normalize_links(links: dict[str, Any] | None) -> dict[str, list[str]]:
    payload = links or {}
    normalized: dict[str, list[str]] = {}
    for key in ("people", "projects", "topics", "related_facts", "related_threads"):
        values = payload.get(key, [])
        if not isinstance(values, list):
            values = []
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = str(value or "").strip()
            if not cleaned:
                continue
            token = cleaned.lower()
            if token in seen:
                continue
            seen.add(token)
            deduped.append(cleaned)
        normalized[key] = deduped
    return normalized


def _build_content(
    *,
    item_type: str,
    title: str,
    summary: str | None,
    due_at: str | None = None,
    priority: str | None = None,
    links: dict[str, Any] | None = None,
    source: str,
    requires_confirmation: bool,
    not_synced_external: bool = False,
    companion_category: str | None = None,
    open_loop_status: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    normalized_links = _normalize_links(links)
    summary_value = summary or title
    evidence = note or summary_value
    time_key = "due_date" if item_type == "task" else "date"
    return {
        "schema_version": "v1",
        "item_type": item_type,
        "title": title,
        "summary": summary_value,
        "salience": priority,
        "priority": priority,
        "urgency": priority,
        "importance": priority,
        "sensitivity": "low",
        "time": {
            "due_date": due_at if item_type == "task" else None,
            "reminder_at": None,
            "date": due_at if item_type == "event" else None,
            "time": None,
            "duration": None,
            "follow_up_after_hours": 24 if item_type == "thread" else None,
            "stale_after_hours": None,
            "expires_at": None,
        },
        "links": normalized_links,
        "lifecycle": {
            "follow_up_after_hours": 24 if item_type == "thread" else None,
            "stale_after_hours": None,
            "expires_at": None,
        },
        "evidence": {
            "raw_evidence": evidence,
            "source_turn_refs": [],
        },
        "metadata": {
            "companion_category": companion_category,
            "internal_source": source,
            "requires_confirmation": requires_confirmation,
            "not_synced_external": not_synced_external,
            "item_status": "pending" if requires_confirmation else "active",
            "open_loop_status": open_loop_status,
            "agent_item": {
                "title": title,
                "summary": summary_value,
                "raw_evidence": evidence,
                "related_people": normalized_links["people"],
                "related_projects": normalized_links["projects"],
                "related_topics": normalized_links["topics"],
                "source": source,
                "requires_confirmation": requires_confirmation,
                "not_synced_external": not_synced_external,
            },
        },
    }


def _fact_item_status(fact: dict[str, Any]) -> str:
    if fact.get("status") == "dismissed":
        return "dismissed"
    if fact.get("status") == "stale":
        return "stale"
    if fact.get("status") == "historical":
        return "completed"
    return str((fact.get("content") or {}).get("metadata", {}).get("item_status") or "active")


def _candidate_item_status(candidate: dict[str, Any]) -> str:
    status = candidate.get("status")
    if status == "dismissed":
        return "dismissed"
    if status == "expired":
        return "stale"
    return "active"


def _canonical_item(
    *,
    source_kind: str,
    row: dict[str, Any],
    item_class: str,
) -> dict[str, Any]:
    content = row.get("content") or {}
    metadata = content.get("metadata") or {}
    structured = row.get("structured_content") or {}
    links = _normalize_links(content.get("links") or {})
    time_payload = content.get("time") or {}
    status = _fact_item_status(row) if source_kind == "confirmed_fact" else _candidate_item_status(row)
    kind = _kind_for_row(row)
    return {
        "id": str(row["id"]),
        "user_id": row["user_id"],
        "item_class": item_class,
        "item_kind": kind,
        "record_kind": source_kind,
        "status": status,
        "title": content.get("title"),
        "summary": content.get("summary"),
        "starts_at": row.get("starts_at") or time_payload.get("starts_at") or time_payload.get("date"),
        "ends_at": row.get("ends_at") or time_payload.get("ends_at"),
        "due_at": row.get("due_at") or time_payload.get("due_date") or time_payload.get("date"),
        "remind_at": row.get("remind_at") or time_payload.get("reminder_at"),
        "priority": row.get("priority") or content.get("priority") or content.get("importance") or content.get("salience"),
        "timezone": row.get("timezone") or (structured.get("temporal") or {}).get("timezone"),
        "recurrence_rule": row.get("recurrence_rule") or (structured.get("temporal") or {}).get("recurrence_rule"),
        "links": {
            "people": links["people"],
            "projects": links["projects"],
            "topics": links["topics"],
        },
        "requires_confirmation": bool(source_kind == "candidate" or metadata.get("requires_confirmation")),
        "not_synced_external": bool(metadata.get("not_synced_external", item_class == "event")),
        "source": metadata.get("internal_source") or "pipeline",
        "source_refs": [f"outbox:{value}" for value in row.get("source_ids", [])] if source_kind == "confirmed_fact" else [f"outbox:{row['source_id']}"],
        "confidence": float(row.get("confidence", 0.0)),
        "created_at": str(row.get("created_at") or row.get("first_seen_at") or ""),
        "updated_at": str(row.get("last_seen_at") or row.get("created_at") or row.get("first_seen_at") or ""),
        "structured_content": structured,
        "provenance": row.get("provenance") or {},
        "metadata": {
            "fact_type": row.get("fact_type"),
            "candidate_type": row.get("candidate_type"),
            "item_status": metadata.get("item_status"),
            "open_loop_status": metadata.get("open_loop_status"),
            "follow_up_needed": row.get("follow_up_needed", False),
        },
    }


async def _db_fetch(database: Database, query: str, *args) -> list[dict[str, Any]]:
    return await database.fetch(query, *args)


async def _db_fetchone(database: Database, query: str, *args) -> dict[str, Any] | None:
    return await database.fetchone(query, *args)


async def _fetch_confirmed_facts(database: Database, *, user_id: str, fact_types: list[str] | None = None) -> list[dict[str, Any]]:
    if hasattr(database, "confirmed_facts"):
        rows = list(getattr(database, "confirmed_facts").values()) if isinstance(getattr(database, "confirmed_facts"), dict) else list(getattr(database, "confirmed_facts"))
        rows = [row for row in rows if row["user_id"] == user_id]
        if fact_types:
            rows = [row for row in rows if row.get("fact_type") in fact_types]
        return rows
    if fact_types:
        return await _db_fetch(
            database,
            """
            SELECT *
            FROM confirmed_facts
            WHERE user_id = $1 AND fact_type = ANY($2::fact_type[])
            ORDER BY last_seen_at DESC NULLS LAST, first_seen_at DESC NULLS LAST
            """,
            user_id,
            fact_types,
        )
    return await _db_fetch(
        database,
        """
        SELECT *
        FROM confirmed_facts
        WHERE user_id = $1
        ORDER BY last_seen_at DESC NULLS LAST, first_seen_at DESC NULLS LAST
        """,
        user_id,
    )


async def _fetch_candidates(database: Database, *, user_id: str, candidate_types: list[str] | None = None) -> list[dict[str, Any]]:
    if hasattr(database, "candidates"):
        rows = list(getattr(database, "candidates").values()) if isinstance(getattr(database, "candidates"), dict) else list(getattr(database, "candidates"))
        rows = [row for row in rows if row["user_id"] == user_id]
        if candidate_types:
            rows = [row for row in rows if row.get("candidate_type") in candidate_types]
        return rows
    if candidate_types:
        return await _db_fetch(
            database,
            """
            SELECT *
            FROM candidates
            WHERE user_id = $1 AND candidate_type = ANY($2::candidate_type[])
            ORDER BY created_at DESC, id DESC
            """,
            user_id,
            candidate_types,
        )
    return await _db_fetch(
        database,
        """
        SELECT *
        FROM candidates
        WHERE user_id = $1
        ORDER BY created_at DESC, id DESC
        """,
        user_id,
    )


async def _fetch_fact_by_id(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any] | None:
    if hasattr(database, "confirmed_facts"):
        rows = getattr(database, "confirmed_facts")
        row = rows.get(item_id) if isinstance(rows, dict) else next((item for item in rows if item["id"] == item_id), None)
        if row and row["user_id"] == user_id:
            return row
        return None
    return await _db_fetchone(
        database,
        """
        SELECT *
        FROM confirmed_facts
        WHERE id = $1 AND user_id = $2
        """,
        item_id,
        user_id,
    )


async def _fetch_candidate_by_id(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any] | None:
    if hasattr(database, "candidates"):
        rows = getattr(database, "candidates")
        row = rows.get(item_id) if isinstance(rows, dict) else next((item for item in rows if item["id"] == item_id), None)
        if row and row["user_id"] == user_id:
            return row
        return None
    return await _db_fetchone(
        database,
        """
        SELECT *
        FROM candidates
        WHERE id = $1 AND user_id = $2
        """,
        item_id,
        user_id,
    )


async def _fetch_source_archive_by_user(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    if hasattr(database, "source_archive_rows"):
        rows = getattr(database, "source_archive_rows")
        rows = list(rows.values()) if isinstance(rows, dict) else list(rows)
        return [row for row in rows if row["user_id"] == user_id]
    return await _db_fetch(database, "SELECT * FROM source_archive WHERE user_id = $1", user_id)


async def _insert_outbox_reference(database: Database, *, user_id: str, source: str, raw_content: str, metadata: dict[str, Any]) -> UUID:
    outbox_id = uuid4()
    received_at = _now_naive()
    source_type = "chat"
    if hasattr(database, "outbox_rows"):
        rows = getattr(database, "outbox_rows")
        row = {
            "id": outbox_id,
            "user_id": user_id,
            "source_type": source_type,
            "raw_content": raw_content,
            "received_at": received_at,
            "status": "done",
            "retry_count": 0,
            "source_archive_id": None,
            "metadata": metadata,
        }
        if isinstance(rows, dict):
            rows[outbox_id] = row
        else:
            rows.append(row)
        return outbox_id
    await database.execute(
        """
        INSERT INTO outbox (
            id, user_id, source_type, raw_content, received_at, status, retry_count, metadata
        ) VALUES ($1, $2, $3::outbox_source_type, $4, $5, $6::outbox_status, $7, $8::jsonb)
        """,
        outbox_id,
        user_id,
        source_type,
        raw_content,
        received_at,
        "done",
        0,
        metadata,
    )
    return outbox_id


async def _insert_timeline_event(
    database: Database,
    *,
    user_id: str,
    event_type: str,
    timeline_type: str,
    title: str,
    summary: str,
    source_id: UUID | None,
    related_fact_ids: list[UUID] | None = None,
    confidence: float = 1.0,
) -> None:
    event_id = uuid4()
    observed_at = _now_naive()
    if hasattr(database, "timeline_events"):
        getattr(database, "timeline_events").append(
            {
                "id": event_id,
                "user_id": user_id,
                "event_type": event_type,
                "timeline_type": timeline_type,
                "title": title,
                "summary": summary,
                "occurred_at": observed_at,
                "observed_at": observed_at,
                "source_id": source_id,
                "related_fact_ids": related_fact_ids or [],
                "status": "current",
                "confidence": confidence,
            }
        )
        return
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
        event_id,
        user_id,
        event_type,
        timeline_type,
        title,
        summary,
        observed_at,
        observed_at,
        source_id,
        related_fact_ids or [],
        "current",
        confidence,
    )
    await embeddings.index_timeline_event(
        database,
        {
            "id": event_id,
            "user_id": user_id,
            "event_type": event_type,
            "timeline_type": timeline_type,
            "title": title,
            "summary": summary,
            "occurred_at": observed_at,
            "observed_at": observed_at,
            "source_id": source_id,
            "related_fact_ids": related_fact_ids or [],
            "status": "current",
            "confidence": confidence,
        },
    )


async def _insert_candidate(
    database: Database,
    *,
    user_id: str,
    source_id: UUID,
    candidate_type: str,
    content: dict[str, Any],
    confidence: float,
    needs_confirmation: bool,
    source_type: str = "chat",
    who_said_it: str = "user",
    channel: str | None = None,
    conversation_id: str | None = None,
    created_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_id = uuid4()
    created_at = _now_naive()
    provenance = _row_provenance(
        source_id=source_id,
        source_ids=[source_id],
        source_type=source_type,
        original_text=content["evidence"]["raw_evidence"],
        who_said_it=who_said_it,
        channel=channel,
        conversation_id=conversation_id,
        created_from=created_from,
    )
    operational = extract_operational_fields(
        item_type=candidate_type,
        content=content,
        provenance=provenance,
        record_status="pending",
    )
    record = {
        "id": candidate_id,
        "user_id": user_id,
        "source_id": source_id,
        "candidate_type": candidate_type,
        "fact_type": operational["fact_type"],
        "content": content,
        "structured_content": operational["structured_content"],
        "raw_evidence": content["evidence"]["raw_evidence"],
        "confidence": confidence,
        "needs_confirmation": needs_confirmation,
        "status": "pending",
        "reconciliation_instruction": None,
        "merge_target_id": None,
        "created_at": created_at,
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
    }
    if hasattr(database, "candidates"):
        rows = getattr(database, "candidates")
        if isinstance(rows, dict):
            rows[candidate_id] = record
        else:
            rows.append(record)
        return record
    await database.execute(
        """
        INSERT INTO candidates (
            id, user_id, source_id, candidate_type, fact_type, content, structured_content, raw_evidence, confidence,
            needs_confirmation, status, reconciliation_instruction, merge_target_id, created_at,
            starts_at, ends_at, due_at, remind_at, timezone, recurrence_rule, completed_at, cancelled_at,
            priority, source_type, who_said_it, original_text, channel, conversation_id, created_from, provenance, follow_up_needed
        ) VALUES (
            $1, $2, $3, $4::candidate_type, $5::fact_type, $6::jsonb, $7::jsonb, $8, $9,
            $10, $11::candidate_status, $12::reconciliation_instruction, $13, $14,
            $15, $16, $17, $18, $19, $20, $21, $22,
            $23, $24, $25, $26, $27, $28, $29::jsonb, $30::jsonb, $31
        )
        """,
        candidate_id,
        user_id,
        source_id,
        candidate_type,
        operational["fact_type"],
        content,
        operational["structured_content"],
        content["evidence"]["raw_evidence"],
        confidence,
        needs_confirmation,
        "pending",
        None,
        None,
        created_at,
        _to_naive(operational["starts_at"]),
        _to_naive(operational["ends_at"]),
        _to_naive(operational["due_at"]),
        _to_naive(operational["remind_at"]),
        operational["timezone"],
        operational["recurrence_rule"],
        _to_naive(operational["completed_at"]),
        _to_naive(operational["cancelled_at"]),
        operational["priority"],
        operational["source_type"],
        operational["who_said_it"],
        operational["original_text"],
        operational["channel"],
        operational["conversation_id"],
        operational["created_from"] or {},
        operational["provenance"] or {},
        operational["follow_up_needed"],
    )
    return record


async def _insert_confirmed_fact(
    database: Database,
    *,
    user_id: str,
    fact_type: str,
    domain: str,
    content: dict[str, Any],
    confidence: float,
    source_ids: list[UUID],
    status: str = "active",
    user_corrected: bool = False,
    correction_note: str | None = None,
    source_type: str = "chat",
    who_said_it: str = "user",
    channel: str | None = None,
    conversation_id: str | None = None,
    created_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fact_id = uuid4()
    now = _now_naive()
    primary_source_id = source_ids[0] if source_ids else None
    provenance = _row_provenance(
        source_id=primary_source_id,
        source_ids=source_ids,
        source_type=source_type,
        original_text=content["evidence"]["raw_evidence"],
        who_said_it=who_said_it,
        channel=channel,
        conversation_id=conversation_id,
        created_from=created_from,
    )
    operational = extract_operational_fields(
        item_type=fact_type,
        content=content,
        provenance=provenance,
        record_status=status,
    )
    record = {
        "id": fact_id,
        "user_id": user_id,
        "fact_type": fact_type,
        "domain": domain,
        "content": content,
        "structured_content": operational["structured_content"],
        "confidence": confidence,
        "first_seen_at": now,
        "last_seen_at": now,
        "last_confirmed_at": now,
        "source_ids": source_ids,
        "source_type": operational["source_type"],
        "primary_source_id": primary_source_id,
        "who_said_it": operational["who_said_it"],
        "original_text": operational["original_text"],
        "channel": operational["channel"],
        "conversation_id": operational["conversation_id"],
        "created_from": operational["created_from"],
        "provenance": operational["provenance"],
        "status": status,
        "starts_at": _to_naive(operational["starts_at"]),
        "ends_at": _to_naive(operational["ends_at"]),
        "due_at": _to_naive(operational["due_at"]),
        "remind_at": _to_naive(operational["remind_at"]),
        "timezone": operational["timezone"],
        "recurrence_rule": operational["recurrence_rule"],
        "completed_at": _to_naive(operational["completed_at"]),
        "cancelled_at": _to_naive(operational["cancelled_at"]),
        "priority": operational["priority"],
        "follow_up_needed": operational["follow_up_needed"],
        "user_corrected": user_corrected,
        "correction_note": correction_note,
        "expires_at": None,
    }
    if hasattr(database, "confirmed_facts"):
        rows = getattr(database, "confirmed_facts")
        if isinstance(rows, dict):
            rows[fact_id] = record
        else:
            rows.append(record)
        return record
    await database.execute(
        """
        INSERT INTO confirmed_facts (
            id, user_id, fact_type, domain, content, confidence,
            first_seen_at, last_seen_at, last_confirmed_at, source_ids,
            status, user_corrected, correction_note, expires_at,
            structured_content, source_type, primary_source_id, who_said_it, original_text,
            channel, conversation_id, created_from, provenance,
            starts_at, ends_at, due_at, remind_at, timezone, recurrence_rule,
            completed_at, cancelled_at, priority, follow_up_needed
        ) VALUES (
            $1, $2, $3::fact_type, $4::fact_domain, $5::jsonb, $6,
            $7, $8, $9, $10, $11::fact_status, $12, $13, $14
            , $15::jsonb, $16, $17, $18, $19,
            $20, $21, $22::jsonb, $23::jsonb,
            $24, $25, $26, $27, $28, $29,
            $30, $31, $32, $33
        )
        """,
        fact_id,
        user_id,
        fact_type,
        domain,
        content,
        confidence,
        now,
        now,
        now,
        source_ids,
        status,
        user_corrected,
        correction_note,
        None,
        operational["structured_content"],
        operational["source_type"],
        primary_source_id,
        operational["who_said_it"],
        operational["original_text"],
        operational["channel"],
        operational["conversation_id"],
        operational["created_from"] or {},
        operational["provenance"] or {},
        _to_naive(operational["starts_at"]),
        _to_naive(operational["ends_at"]),
        _to_naive(operational["due_at"]),
        _to_naive(operational["remind_at"]),
        operational["timezone"],
        operational["recurrence_rule"],
        _to_naive(operational["completed_at"]),
        _to_naive(operational["cancelled_at"]),
        operational["priority"],
        operational["follow_up_needed"],
    )
    await embeddings.index_confirmed_fact(database, record)
    return record


async def _update_candidate_record(database: Database, row: dict[str, Any]) -> None:
    if hasattr(database, "candidates"):
        rows = getattr(database, "candidates")
        if isinstance(rows, dict):
            rows[row["id"]] = row
        return
    await database.execute(
        """
        UPDATE candidates
        SET content = $2::jsonb,
            structured_content = $3::jsonb,
            raw_evidence = $4,
            status = $5::candidate_status,
            needs_confirmation = $6,
            reconciliation_instruction = $7::reconciliation_instruction,
            merge_target_id = $8,
            starts_at = $9,
            ends_at = $10,
            due_at = $11,
            remind_at = $12,
            timezone = $13,
            recurrence_rule = $14,
            completed_at = $15,
            cancelled_at = $16,
            priority = $17,
            source_type = $18,
            who_said_it = $19,
            original_text = $20,
            channel = $21,
            conversation_id = $22,
            created_from = $23::jsonb,
            provenance = $24::jsonb,
            follow_up_needed = $25
        WHERE id = $1
        """,
        row["id"],
        row["content"],
        row.get("structured_content"),
        row["raw_evidence"],
        row["status"],
        row["needs_confirmation"],
        row.get("reconciliation_instruction"),
        row.get("merge_target_id"),
        row.get("starts_at"),
        row.get("ends_at"),
        row.get("due_at"),
        row.get("remind_at"),
        row.get("timezone"),
        row.get("recurrence_rule"),
        row.get("completed_at"),
        row.get("cancelled_at"),
        row.get("priority"),
        row.get("source_type"),
        row.get("who_said_it"),
        row.get("original_text"),
        row.get("channel"),
        row.get("conversation_id"),
        row.get("created_from") or {},
        row.get("provenance") or {},
        row.get("follow_up_needed", False),
    )


async def _update_fact_record(database: Database, row: dict[str, Any]) -> None:
    if hasattr(database, "confirmed_facts"):
        rows = getattr(database, "confirmed_facts")
        if isinstance(rows, dict):
            rows[row["id"]] = row
        return
    await database.execute(
        """
        UPDATE confirmed_facts
        SET content = $2::jsonb,
            structured_content = $3::jsonb,
            confidence = $4,
            last_seen_at = $5,
            last_confirmed_at = $6,
            source_ids = $7,
            status = $8::fact_status,
            user_corrected = $9,
            correction_note = $10,
            expires_at = $11,
            source_type = $12,
            primary_source_id = $13,
            who_said_it = $14,
            original_text = $15,
            channel = $16,
            conversation_id = $17,
            created_from = $18::jsonb,
            provenance = $19::jsonb,
            starts_at = $20,
            ends_at = $21,
            due_at = $22,
            remind_at = $23,
            timezone = $24,
            recurrence_rule = $25,
            completed_at = $26,
            cancelled_at = $27,
            priority = $28,
            follow_up_needed = $29
        WHERE id = $1
        """,
        row["id"],
        row["content"],
        row.get("structured_content"),
        row["confidence"],
        row["last_seen_at"],
        row["last_confirmed_at"],
        row["source_ids"],
        row["status"],
        row["user_corrected"],
        row["correction_note"],
        row["expires_at"],
        row.get("source_type"),
        row.get("primary_source_id"),
        row.get("who_said_it"),
        row.get("original_text"),
        row.get("channel"),
        row.get("conversation_id"),
        row.get("created_from") or {},
        row.get("provenance") or {},
        row.get("starts_at"),
        row.get("ends_at"),
        row.get("due_at"),
        row.get("remind_at"),
        row.get("timezone"),
        row.get("recurrence_rule"),
        row.get("completed_at"),
        row.get("cancelled_at"),
        row.get("priority"),
        row.get("follow_up_needed", False),
    )
    await embeddings.index_confirmed_fact(database, row)


def _filter_status(rows: list[dict[str, Any]], *, status: str, source_kind: str) -> list[dict[str, Any]]:
    if status == "all":
        return rows
    filtered = []
    for row in rows:
        value = _fact_item_status(row) if source_kind == "confirmed_fact" else _candidate_item_status(row)
        if value == status:
            filtered.append(row)
    return filtered


def _iso_day(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    parsed = parse_datetime(value)
    return parsed.date().isoformat() if parsed else None


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


async def active_habits(database: Database, *, user_id: str) -> dict[str, Any]:
    facts = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["habit", "task"])
    items = []
    for row in facts:
        if row.get("status") != "active" or _kind_for_row(row) != "habit":
            continue
        items.append(_canonical_item(source_kind="confirmed_fact", row=row, item_class="action"))
    return {"items": items}


async def habit_completion_status(database: Database, *, user_id: str, day: str) -> dict[str, Any]:
    habits = await active_habits(database, user_id=user_id)
    events = await _db_fetch(
        database,
        """
        SELECT *
        FROM timeline_events
        WHERE user_id = $1
        ORDER BY observed_at DESC NULLS LAST, occurred_at DESC NULLS LAST
        """,
        user_id,
    ) if not hasattr(database, "timeline_events") else [event for event in getattr(database, "timeline_events") if event["user_id"] == user_id]
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


async def open_threads(database: Database, *, user_id: str) -> dict[str, Any]:
    facts = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["thread"])
    items = []
    for row in facts:
        if row.get("status") != "active":
            continue
        if not row.get("follow_up_needed", True):
            continue
        items.append(_canonical_item(source_kind="confirmed_fact", row=row, item_class="thread"))
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


async def list_events(database: Database, *, user_id: str, status: str = "active", limit: int = 20) -> dict[str, Any]:
    facts = _filter_status(await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["event"]), status="active" if status == "confirmed" else status, source_kind="confirmed_fact")
    candidates = _filter_status(await _fetch_candidates(database, user_id=user_id, candidate_types=["event", "invitation"]), status="active" if status == "confirmed" else status, source_kind="candidate")
    items = [
        *[_canonical_item(source_kind="confirmed_fact", row=row, item_class="event") for row in facts],
        *[_canonical_item(source_kind="candidate", row=row, item_class="event") for row in candidates],
    ]
    if status == "confirmed":
        items = [item for item in items if item["record_kind"] == "confirmed_fact"]
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"items": items[:limit]}


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
    content = _build_content(
        item_type="task",
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
        links=links,
        source=source,
        requires_confirmation=requires_confirmation,
    )
    outbox_id = await _insert_outbox_reference(
        database,
        user_id=user_id,
        source=source,
        raw_content=summary or title,
        metadata={"internal_source": source, "item_class": "action"},
    )
    if requires_confirmation:
        row = await _insert_candidate(
            database,
            user_id=user_id,
            source_id=outbox_id,
            candidate_type="task",
            content=content,
            confidence=0.99,
            needs_confirmation=True,
            source_type=source,
            created_from={"path": "create_action", "source": source},
        )
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type="fact_learned",
            timeline_type="user_life",
            title=title,
            summary=summary,
            source_id=outbox_id,
            confidence=0.99,
        )
        return _canonical_item(source_kind="candidate", row=row, item_class="action")
    row = await _insert_confirmed_fact(
        database,
        user_id=user_id,
        fact_type="task",
        domain="obligations",
        content=content,
        confidence=0.99,
        source_ids=[outbox_id],
        status="active",
        source_type=source,
        created_from={"path": "create_action", "source": source},
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="task_confirmed",
        timeline_type="user_life",
        title=title,
        summary=summary,
        source_id=outbox_id,
        related_fact_ids=[row["id"]],
        confidence=0.99,
    )
    return _canonical_item(source_kind="confirmed_fact", row=row, item_class="action")


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
    content = _build_content(
        item_type="event",
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
        links=links,
        source=source,
        requires_confirmation=True,
        not_synced_external=True,
    )
    outbox_id = await _insert_outbox_reference(
        database,
        user_id=user_id,
        source=source,
        raw_content=summary or title,
        metadata={"internal_source": source, "item_class": "event", "not_synced_external": True},
    )
    row = await _insert_candidate(
        database,
        user_id=user_id,
        source_id=outbox_id,
        candidate_type="event",
        content=content,
        confidence=0.99,
        needs_confirmation=True,
        source_type=source,
        created_from={"path": "create_event", "source": source},
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="fact_learned",
        timeline_type="calendar",
        title=title,
        summary=summary,
        source_id=outbox_id,
        confidence=0.99,
    )
    return _canonical_item(source_kind="candidate", row=row, item_class="event")


def _apply_item_updates(content: dict[str, Any], *, title: str | None, summary: str | None, due_at: str | None, priority: str | None) -> dict[str, Any]:
    updated = {**content}
    if title is not None:
        updated["title"] = title
    if summary is not None:
        updated["summary"] = summary
        updated.setdefault("evidence", {})["raw_evidence"] = summary
    if priority is not None:
        updated["priority"] = priority
        updated["importance"] = priority
        updated["salience"] = priority
        updated["urgency"] = priority
    if due_at is not None:
        updated.setdefault("time", {})
        if updated.get("item_type") == "event":
            updated["time"]["date"] = due_at
        else:
            updated["time"]["due_date"] = due_at
    return updated


def _event_type_for_completion(kind: str) -> str:
    if kind == "habit":
        return "habit_completed"
    if kind == "reminder":
        return "reminder_dismissed"
    if kind == "thread":
        return "thread_resolved"
    return "task_completed"


async def _confirm_candidate_as_fact(
    database: Database,
    *,
    candidate: dict[str, Any],
    fact_type: str,
    domain: str,
    status: str = "active",
) -> dict[str, Any]:
    candidate["status"] = "confirmed"
    await _update_candidate_record(database, candidate)
    row = await _insert_confirmed_fact(
        database,
        user_id=candidate["user_id"],
        fact_type=fact_type,
        domain=domain,
        content=candidate["content"],
        confidence=candidate["confidence"],
        source_ids=[candidate["source_id"]],
        status=status,
        source_type=candidate.get("source_type", "chat"),
        who_said_it=candidate.get("who_said_it", "user"),
        channel=candidate.get("channel"),
        conversation_id=candidate.get("conversation_id"),
        created_from=candidate.get("created_from"),
    )
    return row


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
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if fact and fact.get("fact_type") in {"task", "habit", "reminder"}:
        kind = _kind_for_row(fact)
        fact["content"] = _apply_item_updates(fact["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        fact["last_seen_at"] = _now_naive()
        fact["last_confirmed_at"] = fact["last_seen_at"]
        if status == "completed":
            fact["status"] = "historical"
            fact["content"].setdefault("metadata", {})["item_status"] = "completed"
            fact["content"] = apply_lifecycle_timestamp(
                fact["content"],
                completed_at=fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
            )
            event_type = _event_type_for_completion(kind)
        elif status == "dismissed":
            fact["status"] = "dismissed"
            fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
            fact["content"] = apply_lifecycle_timestamp(
                fact["content"],
                cancelled_at=fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
            )
            event_type = "reminder_dismissed" if kind == "reminder" else "item_dismissed"
        else:
            fact["status"] = "active"
            fact["content"].setdefault("metadata", {})["item_status"] = "active"
            event_type = "state_change"
        _refresh_operational_row(fact, item_type=fact.get("fact_type") or "task", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
        await _update_fact_record(database, fact)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type=event_type,
            timeline_type="user_life",
            title=fact["content"].get("title") or "Action updated",
            summary=fact["content"].get("summary") or "",
            source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
            related_fact_ids=[fact["id"]],
            confidence=fact["confidence"],
        )
        return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="action")

    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=item_id)
    if candidate and candidate.get("candidate_type") in {"task", "habit", "reminder"}:
        kind = _kind_for_row(candidate)
        candidate["content"] = _apply_item_updates(candidate["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        candidate["raw_evidence"] = candidate["content"]["evidence"]["raw_evidence"]
        _refresh_operational_row(candidate, item_type=candidate.get("candidate_type") or "task", source_id=candidate["source_id"], source_ids=[candidate["source_id"]])
        if status == "dismissed":
            candidate["status"] = "dismissed"
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="reminder_dismissed" if kind == "reminder" else "item_dismissed",
                timeline_type="user_life",
                title=candidate["content"].get("title") or "Action dismissed",
                summary=candidate["content"].get("summary") or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class="action")
        if status == "completed":
            fact_type = candidate.get("candidate_type") or "task"
            domain = "habits" if fact_type == "habit" else "obligations"
            fact_row = await _confirm_candidate_as_fact(database, candidate=candidate, fact_type=fact_type, domain=domain, status="historical")
            fact_row["content"].setdefault("metadata", {})["item_status"] = "completed"
            fact_row["content"] = apply_lifecycle_timestamp(
                fact_row["content"],
                completed_at=_now_naive().replace(tzinfo=timezone.utc).isoformat(),
            )
            _refresh_operational_row(fact_row, item_type=fact_type, source_id=candidate["source_id"], source_ids=fact_row.get("source_ids"))
            await _update_fact_record(database, fact_row)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type=_event_type_for_completion(kind),
                timeline_type="user_life",
                title=fact_row["content"].get("title") or "Action completed",
                summary=fact_row["content"].get("summary") or "",
                source_id=candidate["source_id"],
                related_fact_ids=[fact_row["id"]],
                confidence=fact_row["confidence"],
            )
            return _canonical_item(source_kind="confirmed_fact", row=fact_row, item_class="action")
        candidate["status"] = "pending"
        await _update_candidate_record(database, candidate)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type="fact_learned",
            timeline_type="user_life",
            title=candidate["content"].get("title") or "Action updated",
            summary=candidate["content"].get("summary") or "",
            source_id=candidate["source_id"],
            confidence=candidate["confidence"],
        )
        return _canonical_item(source_kind="candidate", row=candidate, item_class="action")
    raise HTTPException(status_code=404, detail="Action not found.")


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
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if fact and fact.get("fact_type") == "event":
        fact["content"] = _apply_item_updates(fact["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        fact["last_seen_at"] = _now_naive()
        fact["last_confirmed_at"] = fact["last_seen_at"]
        if status == "dismissed":
            fact["status"] = "dismissed"
            fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
            event_type = "item_dismissed"
        else:
            fact["status"] = "active"
            fact["content"].setdefault("metadata", {})["item_status"] = "active"
            event_type = "event_confirmed"
        await _update_fact_record(database, fact)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type=event_type,
            timeline_type="calendar",
            title=fact["content"].get("title") or "Event updated",
            summary=fact["content"].get("summary") or "",
            source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
            related_fact_ids=[fact["id"]],
            confidence=fact["confidence"],
        )
        return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="event")

    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=item_id)
    if candidate and candidate.get("candidate_type") in {"event", "invitation"}:
        candidate["content"] = _apply_item_updates(candidate["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        candidate["raw_evidence"] = candidate["content"]["evidence"]["raw_evidence"]
        if status == "dismissed":
            candidate["status"] = "dismissed"
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="item_dismissed",
                timeline_type="calendar",
                title=candidate["content"].get("title") or "Event dismissed",
                summary=candidate["content"].get("summary") or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class="event")
        if status == "confirmed":
            fact_row = await _confirm_candidate_as_fact(database, candidate=candidate, fact_type="event", domain="events", status="active")
            fact_row["content"].setdefault("metadata", {})["item_status"] = "active"
            fact_row["content"]["metadata"]["not_synced_external"] = True
            await _update_fact_record(database, fact_row)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="event_confirmed",
                timeline_type="calendar",
                title=fact_row["content"].get("title") or "Event confirmed",
                summary=fact_row["content"].get("summary") or "",
                source_id=candidate["source_id"],
                related_fact_ids=[fact_row["id"]],
                confidence=fact_row["confidence"],
            )
            return _canonical_item(source_kind="confirmed_fact", row=fact_row, item_class="event")
        candidate["status"] = "pending"
        await _update_candidate_record(database, candidate)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type="fact_learned",
            timeline_type="calendar",
            title=candidate["content"].get("title") or "Event updated",
            summary=candidate["content"].get("summary") or "",
            source_id=candidate["source_id"],
            confidence=candidate["confidence"],
        )
        return _canonical_item(source_kind="candidate", row=candidate, item_class="event")
    raise HTTPException(status_code=404, detail="Event not found.")


async def record_habit_completion(database: Database, *, user_id: str, item_id: UUID, completed_at: str, status: str = "habit_completed") -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or _kind_for_row(fact) != "habit":
        raise HTTPException(status_code=404, detail="Habit not found.")
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    fact["content"] = apply_lifecycle_timestamp(fact["content"], completed_at=completed_at)
    _refresh_operational_row(fact, item_type=fact.get("fact_type") or "habit", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type=status,
        timeline_type="user_life",
        title=fact["content"].get("title") or "Habit update",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="action")


async def resolve_thread(database: Database, *, user_id: str, item_id: UUID) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    fact["status"] = "historical"
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    fact["content"].setdefault("metadata", {})["open_loop_status"] = "resolved"
    fact["content"].setdefault("metadata", {})["item_status"] = "completed"
    fact["follow_up_needed"] = False
    _refresh_operational_row(fact, item_type="thread", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="thread_resolved",
        timeline_type="relationship",
        title=fact["content"].get("title") or "Thread resolved",
        summary=fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="thread")


async def create_avoid_topic_memory(database: Database, *, user_id: str, note: str) -> dict[str, Any]:
    content = _build_content(
        item_type="fact",
        title="user",
        summary=note,
        links={"projects": [note]},
        source="memory_control",
        requires_confirmation=False,
        companion_category="avoid_topic",
        note=note,
    )
    outbox_id = await _insert_outbox_reference(
        database,
        user_id=user_id,
        source="memory_control",
        raw_content=note,
        metadata={"internal_source": "memory_control", "item_class": "memory_control", "action": "avoid_topic"},
    )
    row = await _insert_confirmed_fact(
        database,
        user_id=user_id,
        fact_type="identity",
        domain="profile",
        content=content,
        confidence=1.0,
        source_ids=[outbox_id],
        status="active",
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="fact_learned",
        timeline_type="system",
        title="Avoid topic updated",
        summary=note,
        source_id=outbox_id,
        related_fact_ids=[row["id"]],
        confidence=1.0,
    )
    return _canonical_item(source_kind="confirmed_fact", row=row, item_class="memory_control")


async def apply_memory_control(
    database: Database,
    *,
    user_id: str,
    action: str,
    target_id: UUID | None,
    target_type: str,
    note: str | None,
) -> dict[str, Any]:
    if action == "avoid_topic":
        return await create_avoid_topic_memory(database, user_id=user_id, note=note or "Avoid this topic.")

    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=target_id) if target_id else None
    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=target_id) if target_id else None
    if not fact and not candidate:
        raise HTTPException(status_code=404, detail="Target item not found.")

    if candidate:
        if action in {"forget", "dismiss"}:
            candidate["status"] = "dismissed"
            if note:
                candidate["content"].setdefault("metadata", {})["control_note"] = note
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="item_dismissed",
                timeline_type="system",
                title=candidate["content"].get("title") or "Candidate dismissed",
                summary=note or candidate["content"].get("summary") or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class=target_type if target_type in {"action", "event"} else "memory_control")
        if action == "correct":
            candidate["status"] = "dismissed"
            candidate["content"].setdefault("metadata", {})["control_note"] = note
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="user_correction",
                timeline_type="system",
                title=candidate["content"].get("title") or "Candidate corrected",
                summary=note or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class=target_type if target_type in {"action", "event"} else "memory_control")
        raise HTTPException(status_code=400, detail="Unsupported memory control for candidate.")

    assert fact is not None
    if action in {"forget", "dismiss"}:
        fact["status"] = "dismissed"
        fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
        if note:
            fact["correction_note"] = note
        event_type = "item_dismissed"
    elif action == "correct":
        fact["status"] = "corrected"
        fact["user_corrected"] = True
        fact["correction_note"] = note
        event_type = "user_correction"
    elif action == "resolve_loop":
        fact["status"] = "historical"
        fact["content"].setdefault("metadata", {})["open_loop_status"] = "resolved"
        fact["content"]["metadata"]["item_status"] = "completed"
        fact["follow_up_needed"] = False
        _refresh_operational_row(fact, item_type=fact.get("fact_type") or "thread", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
        event_type = "thread_resolved"
    else:
        raise HTTPException(status_code=400, detail="Unsupported memory control.")
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type=event_type,
        timeline_type="system" if action != "resolve_loop" else "relationship",
        title=fact["content"].get("title") or "Memory control applied",
        summary=note or fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class=target_type if target_type in {"action", "event"} else "memory_control")


async def ensure_user_item_visible(database: Database, *, user_id: str, item_id: UUID, allowed_fact_types: list[str], allowed_candidate_types: list[str]) -> None:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if fact and fact.get("fact_type") in allowed_fact_types:
        return
    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=item_id)
    if candidate and candidate.get("candidate_type") in allowed_candidate_types:
        return
    raise HTTPException(status_code=404, detail="Item not found.")


async def source_archive_count(database: Database, *, user_id: str) -> int:
    return len(await _fetch_source_archive_by_user(database, user_id=user_id))
