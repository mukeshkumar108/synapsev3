from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from core.db import Database


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_fake_rows(database: Database, attr: str) -> list[dict[str, Any]] | dict[UUID, dict[str, Any]]:
    existing = getattr(database, attr, None)
    if existing is None:
        existing = {}
        setattr(database, attr, existing)
    return existing


def _use_fake_storage(database: Database, attr: str) -> bool:
    return hasattr(database, attr) or not hasattr(database, "execute") or not hasattr(database, "fetchone")


async def fetch_entities(
    database: Database,
    *,
    user_id: str,
    entity_type: str | None = None,
) -> list[dict[str, Any]]:
    if _use_fake_storage(database, "entities"):
        rows = _ensure_fake_rows(database, "entities")
        values = rows.values() if isinstance(rows, dict) else rows
        items = [row for row in values if row["user_id"] == user_id]
        if entity_type is not None:
            items = [row for row in items if row["entity_type"] == entity_type]
        return sorted(items, key=lambda row: (row["entity_type"], str(row["canonical_name"]).lower()))

    if entity_type is None:
        return await database.fetch(
            """
            SELECT *
            FROM entities
            WHERE user_id = $1
            ORDER BY entity_type, canonical_name
            """,
            user_id,
        )
    return await database.fetch(
        """
        SELECT *
        FROM entities
        WHERE user_id = $1 AND entity_type = $2
        ORDER BY canonical_name
        """,
        user_id,
        entity_type,
    )


async def fetch_entity_aliases(
    database: Database,
    *,
    user_id: str,
    entity_id: UUID,
) -> list[dict[str, Any]]:
    if _use_fake_storage(database, "entity_aliases"):
        rows = _ensure_fake_rows(database, "entity_aliases")
        values = rows.values() if isinstance(rows, dict) else rows
        return [
            row
            for row in values
            if row["user_id"] == user_id and row["entity_id"] == entity_id
        ]

    return await database.fetch(
        """
        SELECT *
        FROM entity_aliases
        WHERE user_id = $1 AND entity_id = $2
        ORDER BY is_primary DESC, alias_text
        """,
        user_id,
        entity_id,
    )


async def resolve_entity_by_name(
    database: Database,
    *,
    user_id: str,
    name: str,
    entity_type: str | None = None,
) -> dict[str, Any] | None:
    normalized = name.strip().lower()
    if not normalized:
        return None

    entities = await fetch_entities(database, user_id=user_id, entity_type=entity_type)
    for row in entities:
        if str(row["canonical_name"]).strip().lower() == normalized:
            return row

    if _use_fake_storage(database, "entity_aliases"):
        alias_rows = _ensure_fake_rows(database, "entity_aliases")
        values = alias_rows.values() if isinstance(alias_rows, dict) else alias_rows
        matching_ids = [
            row["entity_id"]
            for row in values
            if row["user_id"] == user_id and str(row["alias_text"]).strip().lower() == normalized
        ]
        for row in entities:
            if row["id"] in matching_ids:
                return row
        return None

    if entity_type is None:
        return await database.fetchone(
            """
            SELECT e.*
            FROM entity_aliases a
            JOIN entities e ON e.id = a.entity_id
            WHERE a.user_id = $1
              AND lower(a.alias_text) = lower($2)
            ORDER BY a.is_primary DESC, a.confidence DESC NULLS LAST
            LIMIT 1
            """,
            user_id,
            name,
        )
    return await database.fetchone(
        """
        SELECT e.*
        FROM entity_aliases a
        JOIN entities e ON e.id = a.entity_id
        WHERE a.user_id = $1
          AND e.entity_type = $3
          AND lower(a.alias_text) = lower($2)
        ORDER BY a.is_primary DESC, a.confidence DESC NULLS LAST
        LIMIT 1
        """,
        user_id,
        name,
        entity_type,
    )


async def fetch_entity_links(
    database: Database,
    *,
    user_id: str,
    entity_id: UUID,
) -> list[dict[str, Any]]:
    if _use_fake_storage(database, "entity_links"):
        rows = _ensure_fake_rows(database, "entity_links")
        values = rows.values() if isinstance(rows, dict) else rows
        return [
            row
            for row in values
            if row["user_id"] == user_id and row["entity_id"] == entity_id and row.get("is_active", True)
        ]
    return await database.fetch(
        """
        SELECT *
        FROM entity_links
        WHERE user_id = $1 AND entity_id = $2 AND is_active = TRUE
        ORDER BY created_at DESC
        """,
        user_id,
        entity_id,
    )


async def upsert_entity(
    database: Database,
    *,
    user_id: str,
    entity_type: str,
    canonical_name: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_name = canonical_name.strip()
    if _use_fake_storage(database, "entities"):
        rows = _ensure_fake_rows(database, "entities")
        values = rows.values() if isinstance(rows, dict) else rows
        for row in values:
            if row["user_id"] == user_id and row["entity_type"] == entity_type and str(row["canonical_name"]).lower() == normalized_name.lower():
                row["metadata"] = {**(row.get("metadata") or {}), **(metadata or {})}
                row["updated_at"] = _now_naive()
                return row
        record = {
            "id": uuid4(),
            "user_id": user_id,
            "entity_type": entity_type,
            "canonical_name": normalized_name,
            "status": "active",
            "metadata": metadata or {},
            "created_at": _now_naive(),
            "updated_at": _now_naive(),
        }
        if isinstance(rows, dict):
            rows[record["id"]] = record
        else:
            rows.append(record)
        return record

    row = await database.fetchone(
        """
        SELECT *
        FROM entities
        WHERE user_id = $1 AND entity_type = $2 AND lower(canonical_name) = lower($3)
        LIMIT 1
        """,
        user_id,
        entity_type,
        normalized_name,
    )
    now = _now_naive()
    if row:
        merged_metadata = {**(row.get("metadata") or {}), **(metadata or {})}
        await database.execute(
            """
            UPDATE entities
            SET metadata = $2::jsonb, updated_at = $3
            WHERE id = $1
            """,
            row["id"],
            merged_metadata,
            now,
        )
        row["metadata"] = merged_metadata
        row["updated_at"] = now
        return row

    entity_id = uuid4()
    await database.execute(
        """
        INSERT INTO entities (
            id, user_id, entity_type, canonical_name, status, metadata, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6::jsonb, $7, $8
        )
        """,
        entity_id,
        user_id,
        entity_type,
        normalized_name,
        "active",
        metadata or {},
        now,
        now,
    )
    return {
        "id": entity_id,
        "user_id": user_id,
        "entity_type": entity_type,
        "canonical_name": normalized_name,
        "status": "active",
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }


async def upsert_entity_alias(
    database: Database,
    *,
    user_id: str,
    entity_id: UUID,
    alias_text: str,
    alias_kind: str,
    confidence: float = 1.0,
    is_primary: bool = False,
) -> dict[str, Any]:
    normalized_alias = alias_text.strip()
    if _use_fake_storage(database, "entity_aliases"):
        rows = _ensure_fake_rows(database, "entity_aliases")
        values = rows.values() if isinstance(rows, dict) else rows
        for row in values:
            if row["user_id"] == user_id and row["entity_id"] == entity_id and str(row["alias_text"]).lower() == normalized_alias.lower():
                row["alias_kind"] = alias_kind
                row["confidence"] = confidence
                row["is_primary"] = is_primary or row.get("is_primary", False)
                row["updated_at"] = _now_naive()
                return row
        record = {
            "id": uuid4(),
            "user_id": user_id,
            "entity_id": entity_id,
            "alias_text": normalized_alias,
            "alias_kind": alias_kind,
            "confidence": confidence,
            "is_primary": is_primary,
            "created_at": _now_naive(),
            "updated_at": _now_naive(),
        }
        if isinstance(rows, dict):
            rows[record["id"]] = record
        else:
            rows.append(record)
        return record

    row = await database.fetchone(
        """
        SELECT *
        FROM entity_aliases
        WHERE user_id = $1 AND entity_id = $2 AND lower(alias_text) = lower($3)
        LIMIT 1
        """,
        user_id,
        entity_id,
        normalized_alias,
    )
    now = _now_naive()
    if row:
        await database.execute(
            """
            UPDATE entity_aliases
            SET alias_kind = $2, confidence = $3, is_primary = $4, updated_at = $5
            WHERE id = $1
            """,
            row["id"],
            alias_kind,
            confidence,
            is_primary or row.get("is_primary", False),
            now,
        )
        row["alias_kind"] = alias_kind
        row["confidence"] = confidence
        row["is_primary"] = is_primary or row.get("is_primary", False)
        row["updated_at"] = now
        return row

    alias_id = uuid4()
    await database.execute(
        """
        INSERT INTO entity_aliases (
            id, user_id, entity_id, alias_text, alias_kind, confidence, is_primary, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9
        )
        """,
        alias_id,
        user_id,
        entity_id,
        normalized_alias,
        alias_kind,
        confidence,
        is_primary,
        now,
        now,
    )
    return {
        "id": alias_id,
        "user_id": user_id,
        "entity_id": entity_id,
        "alias_text": normalized_alias,
        "alias_kind": alias_kind,
        "confidence": confidence,
        "is_primary": is_primary,
        "created_at": now,
        "updated_at": now,
    }


async def insert_entity_mention(
    database: Database,
    *,
    user_id: str,
    entity_id: UUID,
    surface_text: str,
    source_type: str,
    original_text: str | None,
    who_said_it: str | None,
    channel: str | None,
    conversation_id: str | None,
    created_from: dict[str, Any] | None,
    confidence: float = 1.0,
    source_archive_id: UUID | None = None,
    outbox_id: UUID | None = None,
    timeline_event_id: UUID | None = None,
    fact_id: UUID | None = None,
    candidate_id: UUID | None = None,
) -> dict[str, Any]:
    mention = {
        "id": uuid4(),
        "user_id": user_id,
        "entity_id": entity_id,
        "surface_text": surface_text.strip(),
        "source_type": source_type,
        "source_archive_id": source_archive_id,
        "outbox_id": outbox_id,
        "timeline_event_id": timeline_event_id,
        "fact_id": fact_id,
        "candidate_id": candidate_id,
        "confidence": confidence,
        "original_text": original_text,
        "who_said_it": who_said_it,
        "channel": channel,
        "conversation_id": conversation_id,
        "created_from": created_from or {},
        "created_at": _now_naive(),
    }
    if _use_fake_storage(database, "entity_mentions"):
        rows = _ensure_fake_rows(database, "entity_mentions")
        if isinstance(rows, dict):
            rows[mention["id"]] = mention
        else:
            rows.append(mention)
        return mention

    await database.execute(
        """
        INSERT INTO entity_mentions (
            id, user_id, entity_id, surface_text, source_type,
            source_archive_id, outbox_id, timeline_event_id, fact_id, candidate_id,
            confidence, original_text, who_said_it, channel, conversation_id, created_from, created_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16::jsonb, $17
        )
        """,
        mention["id"],
        mention["user_id"],
        mention["entity_id"],
        mention["surface_text"],
        mention["source_type"],
        mention["source_archive_id"],
        mention["outbox_id"],
        mention["timeline_event_id"],
        mention["fact_id"],
        mention["candidate_id"],
        mention["confidence"],
        mention["original_text"],
        mention["who_said_it"],
        mention["channel"],
        mention["conversation_id"],
        mention["created_from"],
        mention["created_at"],
    )
    return mention


async def upsert_entity_link(
    database: Database,
    *,
    user_id: str,
    entity_id: UUID,
    link_type: str,
    confidence: float = 1.0,
    evidence: dict[str, Any] | None = None,
    created_from: dict[str, Any] | None = None,
    fact_id: UUID | None = None,
    candidate_id: UUID | None = None,
    timeline_event_id: UUID | None = None,
    source_archive_id: UUID | None = None,
    outbox_id: UUID | None = None,
) -> dict[str, Any]:
    def _matches(row: dict[str, Any]) -> bool:
        return (
            row["user_id"] == user_id
            and row["entity_id"] == entity_id
            and row.get("link_type") == link_type
            and row.get("fact_id") == fact_id
            and row.get("candidate_id") == candidate_id
            and row.get("timeline_event_id") == timeline_event_id
            and row.get("source_archive_id") == source_archive_id
            and row.get("outbox_id") == outbox_id
        )

    if _use_fake_storage(database, "entity_links"):
        rows = _ensure_fake_rows(database, "entity_links")
        values = rows.values() if isinstance(rows, dict) else rows
        for row in values:
            if _matches(row):
                row["confidence"] = confidence
                row["evidence"] = evidence or row.get("evidence") or {}
                row["created_from"] = created_from or row.get("created_from") or {}
                row["is_active"] = True
                row["updated_at"] = _now_naive()
                return row
        record = {
            "id": uuid4(),
            "user_id": user_id,
            "entity_id": entity_id,
            "fact_id": fact_id,
            "candidate_id": candidate_id,
            "timeline_event_id": timeline_event_id,
            "source_archive_id": source_archive_id,
            "outbox_id": outbox_id,
            "link_type": link_type,
            "confidence": confidence,
            "evidence": evidence or {},
            "created_from": created_from or {},
            "is_active": True,
            "created_at": _now_naive(),
            "updated_at": _now_naive(),
        }
        if isinstance(rows, dict):
            rows[record["id"]] = record
        else:
            rows.append(record)
        return record

    row = await database.fetchone(
        """
        SELECT *
        FROM entity_links
        WHERE user_id = $1
          AND entity_id = $2
          AND link_type = $3
          AND fact_id IS NOT DISTINCT FROM $4
          AND candidate_id IS NOT DISTINCT FROM $5
          AND timeline_event_id IS NOT DISTINCT FROM $6
          AND source_archive_id IS NOT DISTINCT FROM $7
          AND outbox_id IS NOT DISTINCT FROM $8
        LIMIT 1
        """,
        user_id,
        entity_id,
        link_type,
        fact_id,
        candidate_id,
        timeline_event_id,
        source_archive_id,
        outbox_id,
    )
    now = _now_naive()
    if row:
        await database.execute(
            """
            UPDATE entity_links
            SET confidence = $2, evidence = $3::jsonb, created_from = $4::jsonb, is_active = TRUE, updated_at = $5
            WHERE id = $1
            """,
            row["id"],
            confidence,
            evidence or row.get("evidence") or {},
            created_from or row.get("created_from") or {},
            now,
        )
        row["confidence"] = confidence
        row["evidence"] = evidence or row.get("evidence") or {}
        row["created_from"] = created_from or row.get("created_from") or {}
        row["is_active"] = True
        row["updated_at"] = now
        return row

    link_id = uuid4()
    await database.execute(
        """
        INSERT INTO entity_links (
            id, user_id, entity_id, fact_id, candidate_id, timeline_event_id, source_archive_id, outbox_id,
            link_type, confidence, evidence, created_from, is_active, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11::jsonb, $12::jsonb, TRUE, $13, $14
        )
        """,
        link_id,
        user_id,
        entity_id,
        fact_id,
        candidate_id,
        timeline_event_id,
        source_archive_id,
        outbox_id,
        link_type,
        confidence,
        evidence or {},
        created_from or {},
        now,
        now,
    )
    return {
        "id": link_id,
        "user_id": user_id,
        "entity_id": entity_id,
        "fact_id": fact_id,
        "candidate_id": candidate_id,
        "timeline_event_id": timeline_event_id,
        "source_archive_id": source_archive_id,
        "outbox_id": outbox_id,
        "link_type": link_type,
        "confidence": confidence,
        "evidence": evidence or {},
        "created_from": created_from or {},
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
