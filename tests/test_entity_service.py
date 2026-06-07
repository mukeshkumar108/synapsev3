from __future__ import annotations

from uuid import uuid4

import pytest

from core import entity_service, entity_repository, item_repository


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict = {}
        self.candidates: dict = {}
        self.outbox_rows: dict = {}
        self.source_archive_rows: dict = {}
        self.timeline_events: list[dict] = []


async def test_sync_candidate_entities_creates_entities_mentions_and_links() -> None:
    db = FakeDatabase()
    candidate_id = uuid4()
    source_id = uuid4()
    candidate = {
        "id": candidate_id,
        "user_id": "user-1",
        "source_id": source_id,
        "source_type": "chat",
        "original_text": "Call Ashley about Atlas and the contract check-in.",
        "raw_evidence": "Call Ashley about Atlas and the contract check-in.",
        "who_said_it": "user",
        "channel": "chat",
        "conversation_id": "conv-1",
        "created_from": {"writer": "test"},
        "confidence": 0.95,
        "content": {
            "links": {
                "people": ["Ashley"],
                "projects": ["Atlas"],
                "topics": ["contract"],
            }
        },
    }

    await entity_service.sync_candidate_entities(db, candidate)

    entities = list(getattr(db, "entities").values())
    aliases = list(getattr(db, "entity_aliases").values())
    mentions = list(getattr(db, "entity_mentions").values())
    links = list(getattr(db, "entity_links").values())

    assert {(row["entity_type"], row["canonical_name"]) for row in entities} == {
        ("person", "Ashley"),
        ("project", "Atlas"),
        ("topic", "contract"),
    }
    assert {row["alias_text"] for row in aliases} == {"Ashley", "Atlas", "contract"}
    assert all(row["candidate_id"] == candidate_id for row in mentions)
    assert all(row["outbox_id"] == source_id for row in links)
    assert {row["link_type"] for row in links} == {"person_ref", "project_ref", "topic_ref"}


async def test_insert_confirmed_fact_syncs_relationship_subject_entity() -> None:
    db = FakeDatabase()
    source_id = uuid4()
    await item_repository._insert_confirmed_fact(
        db,
        user_id="user-1",
        fact_type="relationship",
        domain="people",
        content={
            "schema_version": "v1",
            "item_type": "fact",
            "title": "Nina",
            "summary": "Nina matters.",
            "links": {
                "people": ["Nina"],
                "projects": [],
                "topics": [],
                "related_facts": [],
                "related_threads": [],
            },
            "evidence": {"raw_evidence": "Nina matters.", "source_turn_refs": []},
            "metadata": {},
            "lifecycle": {},
            "time": {},
        },
        confidence=0.9,
        source_ids=[source_id],
        source_type="chat",
    )

    entities = list(getattr(db, "entities").values())
    links = list(getattr(db, "entity_links").values())

    nina = next(row for row in entities if row["canonical_name"] == "Nina")
    assert nina["entity_type"] == "person"
    assert any(row["link_type"] == "subject" and row["entity_id"] == nina["id"] for row in links)


async def test_resolve_entity_matches_alias_case_insensitively() -> None:
    db = FakeDatabase()
    entity = await entity_repository.upsert_entity(
        db,
        user_id="user-1",
        entity_type="person",
        canonical_name="Krishna",
    )
    await entity_repository.upsert_entity_alias(
        db,
        user_id="user-1",
        entity_id=entity["id"],
        alias_text="my brother",
        alias_kind="nickname",
    )

    resolved = await entity_service.resolve_entity(
        db,
        user_id="user-1",
        name="My Brother",
        entity_type="person",
    )

    assert resolved is not None
    assert resolved["canonical_name"] == "Krishna"
    assert any(alias["alias_text"] == "my brother" for alias in resolved["aliases"])


async def test_backfill_user_entities_derives_timeline_and_source_links() -> None:
    db = FakeDatabase()
    source_id = uuid4()
    archive_id = uuid4()
    fact_id = uuid4()
    db.confirmed_facts[fact_id] = {
        "id": fact_id,
        "user_id": "user-1",
        "fact_type": "thread",
        "domain": "workstreams",
        "content": {
            "schema_version": "v1",
            "item_type": "thread",
            "title": "Waiting on Jordan contract",
            "summary": "Still waiting on Jordan to send the contract.",
            "links": {
                "people": ["Jordan"],
                "projects": ["Atlas"],
                "topics": ["contract"],
                "related_facts": [],
                "related_threads": [],
            },
            "evidence": {"raw_evidence": "Still waiting on Jordan to send the contract.", "source_turn_refs": []},
            "metadata": {"open_loop_status": "active"},
            "lifecycle": {},
            "time": {},
        },
        "confidence": 0.9,
        "source_ids": [source_id],
        "source_type": "chat",
        "who_said_it": "user",
        "original_text": "Still waiting on Jordan to send the contract.",
        "channel": "chat",
        "conversation_id": "conv-1",
        "created_from": {"writer": "test"},
        "status": "active",
    }
    db.outbox_rows[source_id] = {
        "id": source_id,
        "user_id": "user-1",
        "source_archive_id": archive_id,
    }
    db.source_archive_rows[archive_id] = {
        "id": archive_id,
        "user_id": "user-1",
    }
    db.timeline_events.append(
        {
            "id": uuid4(),
            "user_id": "user-1",
            "related_fact_ids": [fact_id],
            "confidence": 0.8,
        }
    )

    summary = await entity_service.backfill_user_entities(db, user_id="user-1")

    entities = list(getattr(db, "entities").values())
    entity_links = list(getattr(db, "entity_links").values())
    assert summary["facts_processed"] == 1
    assert summary["entities_total"] == 3
    assert any(row["canonical_name"] == "Jordan" for row in entities)
    assert any(row["link_type"] == "person_ref_source" and row["source_archive_id"] == archive_id for row in entity_links)
    assert any(str(row["link_type"]).endswith("_timeline") for row in entity_links)
