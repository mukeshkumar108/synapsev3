from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from core import entity_repository, recall as recall_service


pytestmark = pytest.mark.anyio


class FakeDatabase:
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


async def test_entity_alias_expansion_resolves_canonical_person_name() -> None:
    db = FakeDatabase()
    entity = await entity_repository.upsert_entity(db, user_id="user-1", entity_type="person", canonical_name="Krishna")
    await entity_repository.upsert_entity_alias(db, user_id="user-1", entity_id=entity["id"], alias_text="my brother", alias_kind="nickname")

    result = await recall_service.recall(db, user_id="user-1", query="what did I say about my brother", limit=5)

    assert result["resolved_entities"][0]["canonical_name"] == "Krishna"
    assert "my brother" in [alias.lower() for alias in result["resolved_entities"][0]["aliases"]]


async def test_entity_link_lane_returns_fact_linked_to_resolved_entity() -> None:
    db = FakeDatabase()
    outbox_id = uuid4()
    fact_id = uuid4()
    db.confirmed_facts[fact_id] = {
        "id": fact_id,
        "user_id": "user-1",
        "fact_type": "relationship",
        "domain": "people",
        "content": {
            "schema_version": "v1",
            "item_type": "fact",
            "title": "Krishna",
            "summary": "Krishna has been overwhelmed with work.",
            "links": {"people": ["Krishna"], "projects": [], "topics": ["work"], "related_facts": [], "related_threads": []},
            "metadata": {"agent_item": {}},
            "evidence": {"raw_evidence": "Krishna has been overwhelmed with work.", "source_turn_refs": []},
            "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
        },
        "confidence": 0.95,
        "first_seen_at": datetime(2026, 5, 20, 10, 0),
        "last_seen_at": datetime(2026, 5, 22, 10, 0),
        "last_confirmed_at": datetime(2026, 5, 22, 10, 0),
        "source_ids": [outbox_id],
        "status": "active",
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }
    db.outbox_rows[outbox_id] = {"id": outbox_id, "user_id": "user-1", "source_type": "chat", "raw_content": "preview", "received_at": datetime(2026, 5, 22, 10, 0), "status": "done", "retry_count": 0, "source_archive_id": None, "metadata": {}}
    entity = await entity_repository.upsert_entity(db, user_id="user-1", entity_type="person", canonical_name="Krishna")
    await entity_repository.upsert_entity_alias(db, user_id="user-1", entity_id=entity["id"], alias_text="my brother", alias_kind="nickname")
    await entity_repository.upsert_entity_link(db, user_id="user-1", entity_id=entity["id"], fact_id=fact_id, outbox_id=outbox_id, link_type="person_ref", confidence=0.9)

    result = await recall_service.recall(db, user_id="user-1", query="what did I say about my brother", limit=5)

    assert result["items"]
    assert result["items"][0]["title"] == "Krishna"
    assert "entity_link_match" in result["items"][0]["evidence"]["match_reasons"]


async def test_entity_link_lane_returns_timeline_and_source_archive_candidates() -> None:
    db = FakeDatabase()
    entity = await entity_repository.upsert_entity(db, user_id="user-1", entity_type="person", canonical_name="Ashley")
    await entity_repository.upsert_entity_alias(db, user_id="user-1", entity_id=entity["id"], alias_text="Ash", alias_kind="nickname")
    timeline_id = uuid4()
    archive_id = uuid4()
    db.timeline_events.append(
        {
            "id": timeline_id,
            "user_id": "user-1",
            "event_type": "relationship_update",
            "title": "Ashley update",
            "summary": "Ashley sounded stressed.",
            "occurred_at": datetime(2026, 5, 22, 9, 30),
            "observed_at": datetime(2026, 5, 22, 9, 30),
            "source_id": None,
            "related_fact_ids": [],
            "status": "current",
            "confidence": 0.8,
            "timeline_type": "relationship",
        }
    )
    db.source_archive_rows[archive_id] = {
        "id": archive_id,
        "user_id": "user-1",
        "source_type": "sophie_session",
        "source_external_id": None,
        "session_id": "s1",
        "conversation_id": None,
        "occurred_at": datetime(2026, 5, 21, 11, 0),
        "captured_at": datetime(2026, 5, 21, 11, 5),
        "payload": {"raw_content": "Ashley said work was overwhelming.", "messages": []},
        "metadata": {},
        "created_at": datetime(2026, 5, 21, 11, 5),
    }
    await entity_repository.upsert_entity_link(db, user_id="user-1", entity_id=entity["id"], timeline_event_id=timeline_id, link_type="person_ref_timeline", confidence=0.8)
    await entity_repository.upsert_entity_link(db, user_id="user-1", entity_id=entity["id"], source_archive_id=archive_id, link_type="person_ref_source", confidence=0.8)

    result = await recall_service.recall(db, user_id="user-1", query="what did Ash say", limit=5)

    assert any(item["type"] == "timeline_event" for item in result["items"])
    assert any(item["type"] == "episode" for item in result["items"])


async def test_merge_dedupe_collapses_duplicate_fact_hit_from_alias_and_lexical() -> None:
    db = FakeDatabase()
    outbox_id = uuid4()
    fact_id = uuid4()
    db.confirmed_facts[fact_id] = {
        "id": fact_id,
        "user_id": "user-1",
        "fact_type": "relationship",
        "domain": "people",
        "content": {
            "schema_version": "v1",
            "item_type": "fact",
            "title": "Krishna",
            "summary": "Krishna is my brother and he is stressed.",
            "links": {"people": ["Krishna"], "projects": [], "topics": [], "related_facts": [], "related_threads": []},
            "metadata": {"agent_item": {}},
            "evidence": {"raw_evidence": "Krishna is my brother and he is stressed.", "source_turn_refs": []},
            "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
        },
        "confidence": 0.95,
        "first_seen_at": datetime(2026, 5, 20, 10, 0),
        "last_seen_at": datetime(2026, 5, 22, 10, 0),
        "last_confirmed_at": datetime(2026, 5, 22, 10, 0),
        "source_ids": [outbox_id],
        "status": "active",
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }
    db.outbox_rows[outbox_id] = {"id": outbox_id, "user_id": "user-1", "source_type": "chat", "raw_content": "preview", "received_at": datetime(2026, 5, 22, 10, 0), "status": "done", "retry_count": 0, "source_archive_id": None, "metadata": {}}
    entity = await entity_repository.upsert_entity(db, user_id="user-1", entity_type="person", canonical_name="Krishna")
    await entity_repository.upsert_entity_alias(db, user_id="user-1", entity_id=entity["id"], alias_text="my brother", alias_kind="nickname")
    await entity_repository.upsert_entity_link(db, user_id="user-1", entity_id=entity["id"], fact_id=fact_id, outbox_id=outbox_id, link_type="person_ref", confidence=0.9)

    result = await recall_service.recall(db, user_id="user-1", query="Krishna my brother", limit=5)

    matching = [item for item in result["items"] if item["type"] == "fact" and item["id"] == str(fact_id)]
    assert len(matching) == 1
    assert {"lexical_match", "entity_link_match"} <= set(matching[0]["evidence"]["match_reasons"])
