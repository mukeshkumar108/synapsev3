from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from core.db import Database
from core import embeddings


async def get_source_archive_for_user(
    database: Database,
    *,
    source_archive_id: UUID,
    user_id: str,
) -> dict[str, Any] | None:
    return await database.fetchone(
        """
        SELECT *
        FROM source_archive
        WHERE id = $1 AND user_id = $2
        """,
        source_archive_id,
        user_id,
    )


async def get_source_archive_by_session(
    database: Database,
    *,
    user_id: str,
    source_type: str,
    session_id: str,
) -> dict[str, Any] | None:
    return await database.fetchone(
        """
        SELECT *
        FROM source_archive
        WHERE user_id = $1
          AND source_type = $2
          AND session_id = $3
        """,
        user_id,
        source_type,
        session_id,
    )


async def create_source_archive(
    database: Database,
    *,
    user_id: str,
    source_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    source_external_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
    occurred_at: datetime | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    archive_id = uuid4()
    archive_metadata = metadata or {}
    captured = captured_at or datetime.now(timezone.utc).replace(tzinfo=None)
    row = {
        "id": archive_id,
        "user_id": user_id,
        "source_type": source_type,
        "source_external_id": source_external_id,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "occurred_at": occurred_at,
        "captured_at": captured,
        "payload": payload,
        "metadata": archive_metadata,
        "created_at": captured,
    }
    await database.execute(
        """
        INSERT INTO source_archive (
            id, user_id, source_type, source_external_id, session_id, conversation_id,
            occurred_at, captured_at, payload, metadata, created_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9::jsonb, $10::jsonb, $11
        )
        """,
        archive_id,
        user_id,
        source_type,
        source_external_id,
        session_id,
        conversation_id,
        occurred_at,
        captured,
        payload,
        archive_metadata,
        captured,
    )
    await embeddings.index_source_archive(database, row)
    return row


async def create_or_reuse_session_archive(
    database: Database,
    *,
    user_id: str,
    session_id: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    occurred_at: datetime | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    existing = await get_source_archive_by_session(
        database,
        user_id=user_id,
        source_type="sophie_session",
        session_id=session_id,
    )
    if existing:
        await embeddings.index_source_archive(database, existing)
        return existing
    return await create_source_archive(
        database,
        user_id=user_id,
        source_type="sophie_session",
        payload=payload,
        metadata=metadata,
        session_id=session_id,
        conversation_id=conversation_id,
        occurred_at=occurred_at,
        captured_at=captured_at,
    )
