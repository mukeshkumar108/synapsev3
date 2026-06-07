from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

import migrate
from core import embeddings, recall as recall_service
from core.config import get_settings


pytestmark = pytest.mark.anyio


async def _connect_or_skip():
    try:
        database_url = get_settings().get_database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL is not configured")
    try:
        await migrate.apply_schema()
        conn = await asyncpg.connect(database_url)
        await conn.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
        await conn.set_type_codec(
            "json",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
        return conn
    except OSError:
        pytest.skip("Postgres is not available for integration assertions")


async def _cleanup_user(conn: asyncpg.Connection, user_id: str) -> None:
    await conn.execute("DELETE FROM retrieval_embeddings WHERE user_id = $1", user_id)
    await conn.execute("DELETE FROM timeline_events WHERE user_id = $1", user_id)
    await conn.execute("DELETE FROM session_summaries WHERE user_id = $1", user_id)
    await conn.execute("DELETE FROM confirmed_facts WHERE user_id = $1", user_id)
    await conn.execute("DELETE FROM outbox WHERE user_id = $1", user_id)
    await conn.execute("DELETE FROM source_archive WHERE user_id = $1", user_id)


class RecallFakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict[UUID, dict] = {}
        self.session_summaries: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []
        self.source_archive_rows: dict[UUID, dict] = {}
        self.outbox_rows: dict[UUID, dict] = {}
        self.retrieval_embeddings: list[dict] = []

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            user_id = args[0]
            return [row for row in self.confirmed_facts.values() if row["user_id"] == user_id and row["status"] == "active"]
        if "FROM session_summaries" in query:
            user_id = args[0]
            rows = [row for row in self.session_summaries.values() if row["user_id"] == user_id]
            return sorted(rows, key=lambda row: row["occurred_at"], reverse=True)
        if "FROM timeline_events" in query:
            user_id = args[0]
            return [row for row in self.timeline_events if row["user_id"] == user_id]
        if "FROM source_archive" in query:
            user_id = args[0]
            rows = [row for row in self.source_archive_rows.values() if row["user_id"] == user_id]
            return sorted(rows, key=lambda row: row["captured_at"], reverse=True)
        if "FROM outbox" in query:
            user_id = args[0]
            rows = [row for row in self.outbox_rows.values() if row["user_id"] == user_id]
            return sorted(rows, key=lambda row: row["received_at"], reverse=True)
        return []


def _archive(*, user_id: str, raw_content: str, session_id: str) -> tuple[dict, dict]:
    archive_id = uuid4()
    outbox_id = uuid4()
    archive = {
        "id": archive_id,
        "user_id": user_id,
        "source_type": "sophie_session",
        "source_external_id": None,
        "session_id": session_id,
        "conversation_id": None,
        "occurred_at": datetime(2026, 5, 21, 11, 0),
        "captured_at": datetime(2026, 5, 21, 11, 5),
        "payload": {"raw_content": raw_content, "messages": []},
        "metadata": {},
        "created_at": datetime(2026, 5, 21, 11, 5),
    }
    outbox = {
        "id": outbox_id,
        "user_id": user_id,
        "source_type": "chat",
        "raw_content": "preview",
        "received_at": datetime(2026, 5, 21, 11, 5),
        "status": "done",
        "retry_count": 0,
        "source_archive_id": archive_id,
        "metadata": {"source_archive_id": str(archive_id)},
    }
    return archive, outbox


async def _append_embedding(
    db: RecallFakeDatabase,
    *,
    user_id: str,
    source_type: str,
    source_id: UUID,
    text: str,
    source_archive_id: UUID | None = None,
    chunk_index: int | None = None,
) -> None:
    provider = embeddings.DeterministicEmbeddingProvider()
    [vector] = await provider.embed_texts([text])
    db.retrieval_embeddings.append(
        {
            "id": uuid4(),
            "user_id": user_id,
            "source_type": source_type,
            "source_id": source_id,
            "source_archive_id": source_archive_id,
            "chunk_index": chunk_index,
            "text": text,
            "embedding": vector,
            "metadata": {},
            "created_at": datetime(2026, 5, 21, 11, 5),
            "updated_at": datetime(2026, 5, 21, 11, 5),
        }
    )


async def test_pgvector_extension_and_retrieval_embeddings_table_exist_after_migrate() -> None:
    conn = await _connect_or_skip()
    try:
        ext = await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        table_exists = await conn.fetchval(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'retrieval_embeddings'
            """
        )
    finally:
        await conn.close()

    assert ext == "vector"
    assert table_exists == 1


async def test_embedding_provider_defaults_to_deterministic_local() -> None:
    provider = embeddings.get_embedding_provider()
    assert isinstance(provider, embeddings.DeterministicEmbeddingProvider)


async def test_confirmed_fact_and_session_summary_embeddings_upsert_without_duplicates() -> None:
    conn = await _connect_or_skip()
    user_id = f"semantic-fact-{uuid4()}"
    fact_id = uuid4()
    source_id = uuid4()
    summary_id = uuid4()
    fact_content = {
        "schema_version": "v1",
        "item_type": "fact",
        "title": "Ashley",
        "summary": "Ashley is under pressure at work.",
        "evidence": {"raw_evidence": "Ashley said work has been overwhelming."},
    }
    fact_row = {
        "id": fact_id,
        "user_id": user_id,
        "fact_type": "relationship",
        "domain": "people",
        "content": fact_content,
        "confidence": 0.95,
        "first_seen_at": datetime(2026, 5, 22, 10, 0),
        "last_seen_at": datetime(2026, 5, 22, 10, 0),
        "last_confirmed_at": datetime(2026, 5, 22, 10, 0),
        "source_ids": [source_id],
        "status": "active",
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }
    summary_row = {
        "id": summary_id,
        "user_id": user_id,
        "source_id": source_id,
        "summary": "We talked about Ashley feeling overwhelmed at work.",
        "tags": ["personal"],
        "open_items": [],
        "key_decisions": [],
        "emotional_tone": "neutral",
        "occurred_at": datetime(2026, 5, 22, 10, 0),
    }
    try:
        await _cleanup_user(conn, user_id)
        await conn.execute(
            """
            INSERT INTO outbox (
                id, user_id, source_type, raw_content, received_at, status, retry_count, metadata
            ) VALUES ($1, $2, 'chat'::outbox_source_type, $3, $4, 'done'::outbox_status, 0, '{}'::jsonb)
            """,
            source_id,
            user_id,
            "preview",
            datetime(2026, 5, 22, 10, 0),
        )
        await conn.execute(
            """
            INSERT INTO confirmed_facts (
                id, user_id, fact_type, domain, content, confidence,
                first_seen_at, last_seen_at, last_confirmed_at, source_ids,
                status, user_corrected, correction_note, expires_at
            ) VALUES (
                $1, $2, 'relationship'::fact_type, 'people'::fact_domain, $3::jsonb, 0.95,
                $4, $4, $4, $5, 'active'::fact_status, false, null, null
            )
            """,
            fact_id,
            user_id,
            json.dumps(fact_content),
            datetime(2026, 5, 22, 10, 0),
            [source_id],
        )
        await conn.execute(
            """
            INSERT INTO session_summaries (
                id, user_id, source_id, summary, tags, open_items, key_decisions, emotional_tone, occurred_at
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
            """,
            summary_id,
            user_id,
            source_id,
            summary_row["summary"],
            summary_row["tags"],
            summary_row["open_items"],
            summary_row["key_decisions"],
            summary_row["emotional_tone"],
            summary_row["occurred_at"],
        )

        db = type("ConnDatabase", (), {"execute": conn.execute})()
        await embeddings.index_confirmed_fact(db, fact_row)
        await embeddings.index_confirmed_fact(db, fact_row)
        await embeddings.index_session_summary(db, summary_row)
        await embeddings.index_session_summary(db, summary_row)

        rows = await conn.fetch(
            """
            SELECT source_type, source_id::text AS source_id, COUNT(*) AS row_count
            FROM retrieval_embeddings
            WHERE user_id = $1
            GROUP BY source_type, source_id
            ORDER BY source_type
            """,
            user_id,
        )
    finally:
        await _cleanup_user(conn, user_id)
        await conn.close()

    counts = {(row["source_type"], row["source_id"]): row["row_count"] for row in rows}
    assert counts[("confirmed_fact", str(fact_id))] == 1
    assert counts[("session_summary", str(summary_id))] == 1


async def test_source_archive_chunks_upsert_without_duplicates() -> None:
    conn = await _connect_or_skip()
    user_id = f"semantic-archive-{uuid4()}"
    archive_id = uuid4()
    long_text = (
        "User: We talked about God, the universe, meaning, and whether purpose comes from within. "
        "Assistant: We explored how spiritual questions keep coming back when work feels empty. "
        "User: I also mentioned wanting a calmer relationship with uncertainty."
    )
    archive_row = {
        "id": archive_id,
        "user_id": user_id,
        "source_type": "sophie_session",
        "source_external_id": None,
        "session_id": "session-semantic",
        "conversation_id": None,
        "occurred_at": datetime(2026, 5, 21, 11, 0),
        "captured_at": datetime(2026, 5, 21, 11, 0),
        "payload": {"raw_content": long_text, "messages": []},
        "metadata": {},
        "created_at": datetime(2026, 5, 21, 11, 0),
    }
    try:
        await _cleanup_user(conn, user_id)
        await conn.execute(
            """
            INSERT INTO source_archive (
                id, user_id, source_type, source_external_id, session_id, conversation_id,
                occurred_at, captured_at, payload, metadata, created_at
            ) VALUES ($1, $2, $3, null, $4, null, $5, $5, $6::jsonb, '{}'::jsonb, $5)
            """,
            archive_id,
            user_id,
            archive_row["source_type"],
            archive_row["session_id"],
            archive_row["occurred_at"],
            json.dumps(archive_row["payload"]),
        )
        db = type("ConnDatabase", (), {"execute": conn.execute})()
        expected_chunks = embeddings.chunk_text(long_text)
        await embeddings.index_source_archive(db, archive_row)
        await embeddings.index_source_archive(db, archive_row)
        chunk_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM retrieval_embeddings
            WHERE user_id = $1 AND source_type = 'source_archive_chunk' AND source_id = $2
            """,
            user_id,
            archive_id,
        )
    finally:
        await _cleanup_user(conn, user_id)
        await conn.close()

    assert chunk_count == len(expected_chunks)


async def test_semantic_episodic_query_can_match_low_overlap_archive_chunk() -> None:
    db = RecallFakeDatabase()
    archive, outbox = _archive(
        user_id="user-1",
        session_id="session-semantic",
        raw_content="User: We explored God, the universe, and whether meaning comes from within.",
    )
    db.source_archive_rows[archive["id"]] = archive
    db.outbox_rows[outbox["id"]] = outbox
    summary_id = uuid4()
    db.session_summaries[summary_id] = {
        "id": summary_id,
        "user_id": "user-1",
        "source_id": outbox["id"],
        "summary": "We discussed existential questions and inner purpose.",
        "tags": ["reflective"],
        "open_items": [],
        "key_decisions": [],
        "emotional_tone": "neutral",
        "occurred_at": datetime(2026, 5, 21, 11, 0),
    }
    await _append_embedding(
        db,
        user_id="user-1",
        source_type="source_archive_chunk",
        source_id=archive["id"],
        source_archive_id=archive["id"],
        chunk_index=0,
        text="God the universe spiritual questions and meaning from within",
    )
    await _append_embedding(
        db,
        user_id="user-1",
        source_type="session_summary",
        source_id=summary_id,
        text="existential spiritual meaning and inner purpose",
    )

    result = await recall_service.recall(
        db,
        user_id="user-1",
        query="remember that sacred purpose conversation",
        limit=5,
    )

    assert result["recall_type"] == "episodic"
    assert result["episodes"]
    archive_episode = next(
        item for item in result["episodes"] if item["metadata"]["source_kind"] == "source_archive"
    )
    assert archive_episode["metadata"]["vector_score"] > 0.15
    assert archive_episode["metadata"]["vector_score"] >= archive_episode["metadata"]["lexical_score"]
    assert "meaning from within" in archive_episode["evidence_preview"].lower()


async def test_hybrid_scoring_and_user_isolation_hold_for_vector_hits() -> None:
    db = RecallFakeDatabase()
    user_archive, user_outbox = _archive(user_id="user-1", session_id="u1", raw_content="User: Ashley is dealing with work pressure.")
    other_archive, other_outbox = _archive(user_id="user-2", session_id="u2", raw_content="User: Ashley is dealing with work pressure.")
    db.source_archive_rows[user_archive["id"]] = user_archive
    db.source_archive_rows[other_archive["id"]] = other_archive
    db.outbox_rows[user_outbox["id"]] = user_outbox
    db.outbox_rows[other_outbox["id"]] = other_outbox
    await _append_embedding(
        db,
        user_id="user-1",
        source_type="source_archive_chunk",
        source_id=user_archive["id"],
        source_archive_id=user_archive["id"],
        chunk_index=0,
        text="Ashley work career pressure",
    )
    await _append_embedding(
        db,
        user_id="user-2",
        source_type="source_archive_chunk",
        source_id=other_archive["id"],
        source_archive_id=other_archive["id"],
        chunk_index=0,
        text="Ashley work career pressure",
    )

    result = await recall_service.recall(db, user_id="user-1", query="what happened with Ashley's career stress", limit=5)

    assert result["items"]
    assert all("u2" not in item["title"] for item in result["items"])
    assert all("user-2" not in "".join(item["source_refs"]) for item in result["items"])


async def test_weak_unmatched_query_still_sets_weak_recall_true() -> None:
    db = RecallFakeDatabase()

    result = await recall_service.recall(db, user_id="user-1", query="absolutely unrelated query text", limit=5)

    assert result["items"] == []
    assert result["weak_recall"] is True
    assert result["certainty"] == "low"
