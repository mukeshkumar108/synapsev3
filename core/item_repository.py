from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from core import embeddings
from core import entity_service
from core.db import Database
from core.operational import extract_operational_fields, normalize_provenance, parse_datetime


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
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
    occurred_at: datetime | None = None,
) -> None:
    event_id = uuid4()
    observed_at = _now_naive()
    event_occurred_at = occurred_at or observed_at
    if hasattr(database, "timeline_events"):
        getattr(database, "timeline_events").append(
            {
                "id": event_id,
                "user_id": user_id,
                "event_type": event_type,
                "timeline_type": timeline_type,
                "title": title,
                "summary": summary,
                "occurred_at": event_occurred_at,
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
        event_occurred_at,
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
            "occurred_at": event_occurred_at,
            "observed_at": observed_at,
            "source_id": source_id,
            "related_fact_ids": related_fact_ids or [],
            "status": "current",
            "confidence": confidence,
        },
    )


async def _fetch_fact_links_for_fact(database: Database, *, user_id: str, from_fact_id: UUID) -> list[dict[str, Any]]:
    if hasattr(database, "fact_links"):
        rows = getattr(database, "fact_links")
        values = rows.values() if isinstance(rows, dict) else rows
        return [row for row in values if row["user_id"] == user_id and row["from_fact_id"] == from_fact_id and row.get("is_active", True)]
    return await _db_fetch(
        database,
        """
        SELECT *
        FROM fact_links
        WHERE user_id = $1 AND from_fact_id = $2 AND is_active = TRUE
        ORDER BY created_at ASC
        """,
        user_id,
        from_fact_id,
    )


async def _upsert_fact_link(
    database: Database,
    *,
    user_id: str,
    from_fact_id: UUID,
    link_type: str,
    confidence: float,
    evidence: dict[str, Any] | None = None,
    created_from: dict[str, Any] | None = None,
    source_type: str | None = None,
    to_fact_id: UUID | None = None,
    to_timeline_event_id: UUID | None = None,
    to_source_archive_id: UUID | None = None,
    to_outbox_id: UUID | None = None,
) -> dict[str, Any]:
    existing = None
    rows = await _fetch_fact_links_for_fact(database, user_id=user_id, from_fact_id=from_fact_id)
    for row in rows:
        if (
            row.get("to_fact_id") == to_fact_id
            and row.get("to_timeline_event_id") == to_timeline_event_id
            and row.get("to_source_archive_id") == to_source_archive_id
            and row.get("to_outbox_id") == to_outbox_id
            and row.get("link_type") == link_type
        ):
            existing = row
            break
    now = _now_naive()
    if existing:
        existing["confidence"] = confidence
        existing["evidence"] = evidence or existing.get("evidence") or {}
        existing["created_from"] = created_from or existing.get("created_from") or {}
        existing["source_type"] = source_type or existing.get("source_type")
        existing["is_active"] = True
        existing["updated_at"] = now
        if not hasattr(database, "fact_links"):
            await database.execute(
                """
                UPDATE fact_links
                SET confidence = $2,
                    evidence = $3::jsonb,
                    created_from = $4::jsonb,
                    source_type = $5,
                    is_active = TRUE,
                    updated_at = $6
                WHERE id = $1
                """,
                existing["id"],
                existing["confidence"],
                existing["evidence"],
                existing["created_from"],
                existing["source_type"],
                existing["updated_at"],
            )
        return existing

    row = {
        "id": uuid4(),
        "user_id": user_id,
        "from_fact_id": from_fact_id,
        "to_fact_id": to_fact_id,
        "to_timeline_event_id": to_timeline_event_id,
        "to_source_archive_id": to_source_archive_id,
        "to_outbox_id": to_outbox_id,
        "link_type": link_type,
        "confidence": confidence,
        "evidence": evidence or {},
        "created_from": created_from or {},
        "source_type": source_type,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    if hasattr(database, "fact_links"):
        rows_attr = getattr(database, "fact_links")
        if isinstance(rows_attr, dict):
            rows_attr[row["id"]] = row
        else:
            rows_attr.append(row)
        return row
    await database.execute(
        """
        INSERT INTO fact_links (
            id, user_id, from_fact_id, to_fact_id, to_timeline_event_id, to_source_archive_id,
            to_outbox_id, link_type, confidence, evidence, created_from, source_type,
            is_active, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10::jsonb, $11::jsonb, $12,
            $13, $14, $15
        )
        """,
        row["id"],
        row["user_id"],
        row["from_fact_id"],
        row["to_fact_id"],
        row["to_timeline_event_id"],
        row["to_source_archive_id"],
        row["to_outbox_id"],
        row["link_type"],
        row["confidence"],
        row["evidence"],
        row["created_from"],
        row["source_type"],
        row["is_active"],
        row["created_at"],
        row["updated_at"],
    )
    return row


async def _deactivate_fact_link(
    database: Database,
    *,
    user_id: str,
    from_fact_id: UUID,
    target_kind: str,
    target_id: UUID,
) -> bool:
    rows = await _fetch_fact_links_for_fact(database, user_id=user_id, from_fact_id=from_fact_id)
    key = {
        "fact": "to_fact_id",
        "timeline_event": "to_timeline_event_id",
        "source_archive": "to_source_archive_id",
        "outbox": "to_outbox_id",
    }[target_kind]
    matched = False
    now = _now_naive()
    for row in rows:
        if row.get(key) != target_id:
            continue
        row["is_active"] = False
        row["updated_at"] = now
        matched = True
        if not hasattr(database, "fact_links"):
            await database.execute(
                "UPDATE fact_links SET is_active = FALSE, updated_at = $2 WHERE id = $1",
                row["id"],
                row["updated_at"],
            )
    return matched


def _serialize_fact_link(row: dict[str, Any]) -> dict[str, Any]:
    target_type = None
    target_id = None
    for key, kind in (
        ("to_fact_id", "fact"),
        ("to_timeline_event_id", "timeline_event"),
        ("to_source_archive_id", "source_archive"),
        ("to_outbox_id", "outbox"),
    ):
        if row.get(key):
            target_type = kind
            target_id = str(row[key])
            break
    return {
        "id": str(row["id"]),
        "linkType": row.get("link_type"),
        "targetType": target_type,
        "targetId": target_id,
        "confidence": row.get("confidence"),
        "isActive": bool(row.get("is_active", True)),
    }


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
        await entity_service.sync_candidate_entities(database, record)
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
    await entity_service.sync_candidate_entities(database, record)
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
        "thread_type": operational.get("thread_type"),
        "actionability": operational.get("actionability"),
        "next_move": operational.get("next_move"),
        "last_progressed_at": _to_naive(operational.get("last_progressed_at")),
        "last_resurfaced_at": _to_naive(operational.get("last_resurfaced_at")),
        "snoozed_until": _to_naive(operational.get("snoozed_until")),
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
        await entity_service.sync_confirmed_fact_entities(database, record)
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
            completed_at, cancelled_at, priority, follow_up_needed,
            thread_type, actionability, next_move, last_progressed_at, last_resurfaced_at, snoozed_until
        ) VALUES (
            $1, $2, $3::fact_type, $4::fact_domain, $5::jsonb, $6,
            $7, $8, $9, $10, $11::fact_status, $12, $13, $14
            , $15::jsonb, $16, $17, $18, $19,
            $20, $21, $22::jsonb, $23::jsonb,
            $24, $25, $26, $27, $28, $29,
            $30, $31, $32, $33,
            $34, $35, $36, $37, $38, $39
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
        operational.get("thread_type"),
        operational.get("actionability"),
        operational.get("next_move"),
        _to_naive(operational.get("last_progressed_at")),
        _to_naive(operational.get("last_resurfaced_at")),
        _to_naive(operational.get("snoozed_until")),
    )
    await embeddings.index_confirmed_fact(database, record)
    await entity_service.sync_confirmed_fact_entities(database, record)
    return record


async def _update_candidate_record(database: Database, row: dict[str, Any]) -> None:
    if hasattr(database, "candidates"):
        rows = getattr(database, "candidates")
        if isinstance(rows, dict):
            rows[row["id"]] = row
        await entity_service.sync_candidate_entities(database, row)
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
    await entity_service.sync_candidate_entities(database, row)


async def _update_fact_record(database: Database, row: dict[str, Any]) -> None:
    if hasattr(database, "confirmed_facts"):
        rows = getattr(database, "confirmed_facts")
        if isinstance(rows, dict):
            rows[row["id"]] = row
        await entity_service.sync_confirmed_fact_entities(database, row)
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
            follow_up_needed = $29,
            thread_type = $30,
            actionability = $31,
            next_move = $32,
            last_progressed_at = $33,
            last_resurfaced_at = $34,
            snoozed_until = $35
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
        row.get("thread_type"),
        row.get("actionability"),
        row.get("next_move"),
        row.get("last_progressed_at"),
        row.get("last_resurfaced_at"),
        row.get("snoozed_until"),
    )
    await embeddings.index_confirmed_fact(database, row)
    await entity_service.sync_confirmed_fact_entities(database, row)


async def _fetch_fact_by_idempotency_key(database: Database, *, user_id: str, idempotency_key: str, writer: str) -> dict[str, Any] | None:
    if hasattr(database, "confirmed_facts"):
        rows = getattr(database, "confirmed_facts")
        values = rows.values() if isinstance(rows, dict) else rows
        for row in values:
            if row["user_id"] != user_id:
                continue
            created_from = row.get("created_from") or {}
            if created_from.get("writer") == writer and created_from.get("idempotency_key") == idempotency_key:
                return row
        return None
    return await _db_fetchone(
        database,
        """
        SELECT *
        FROM confirmed_facts
        WHERE user_id = $1
          AND created_from->>'writer' = $2
          AND created_from->>'idempotency_key' = $3
        ORDER BY last_seen_at DESC NULLS LAST, first_seen_at DESC NULLS LAST
        LIMIT 1
        """,
        user_id,
        writer,
        idempotency_key,
    )
