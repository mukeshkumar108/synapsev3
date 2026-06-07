from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from core import recall as recall_service


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict[UUID, dict] = {}
        self.session_summaries: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []
        self.source_archive_rows: dict[UUID, dict] = {}
        self.outbox_rows: dict[UUID, dict] = {}

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


def _fact(*, user_id: str, title: str, summary: str, fact_type: str = "relationship", confidence: float = 0.95) -> dict:
    fact_id = uuid4()
    outbox_id = uuid4()
    return {
        "row": {
            "id": fact_id,
            "user_id": user_id,
            "fact_type": fact_type,
            "domain": "people" if fact_type == "relationship" else "obligations",
            "content": {
                "schema_version": "v1",
                "item_type": "fact" if fact_type != "thread" else "thread",
                "title": title,
                "summary": summary,
                "links": {"people": [title], "projects": [], "related_facts": [], "related_threads": []},
                "metadata": {"agent_item": {}, "companion_category": None},
                "evidence": {"raw_evidence": summary, "source_turn_refs": []},
                "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
            },
            "confidence": confidence,
            "first_seen_at": datetime(2026, 5, 20, 10, 0),
            "last_seen_at": datetime(2026, 5, 22, 10, 0),
            "last_confirmed_at": datetime(2026, 5, 22, 10, 0),
            "source_ids": [outbox_id],
            "status": "active",
            "user_corrected": False,
            "correction_note": None,
            "expires_at": None,
        },
        "outbox_id": outbox_id,
    }


def _archive(*, user_id: str, raw_content: str, session_id: str = "session-1") -> dict:
    archive_id = uuid4()
    outbox_id = uuid4()
    return {
        "archive": {
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
        },
        "outbox": {
            "id": outbox_id,
            "user_id": user_id,
            "source_type": "chat",
            "raw_content": "preview",
            "received_at": datetime(2026, 5, 21, 11, 5),
            "status": "done",
            "retry_count": 0,
            "source_archive_id": archive_id,
            "metadata": {"source_archive_id": str(archive_id)},
        },
    }


async def test_exact_factual_query_returns_fact_item() -> None:
    db = FakeDatabase()
    fact = _fact(user_id="user-1", title="Ashley", summary="Ashley is stressed about her job.")
    db.confirmed_facts[fact["row"]["id"]] = fact["row"]
    db.outbox_rows[fact["outbox_id"]] = {
        "id": fact["outbox_id"],
        "user_id": "user-1",
        "source_type": "chat",
        "raw_content": "preview",
        "received_at": datetime(2026, 5, 22, 10, 0),
        "status": "done",
        "retry_count": 0,
        "source_archive_id": None,
        "metadata": {},
    }

    result = await recall_service.recall(db, user_id="user-1", query="Who is Ashley?", limit=5)

    assert result["recall_type"] == "exact"
    assert result["certainty"] == "high"
    assert result["items"][0]["type"] == "fact"
    assert result["facts"][0]["title"] == "Ashley"
    assert result["facts"][0]["source_refs"][0].startswith("outbox:")


async def test_episodic_query_finds_summary_and_source_archive_excerpt() -> None:
    db = FakeDatabase()
    summary_id = uuid4()
    archive = _archive(
        user_id="user-1",
        raw_content="User: We had that conversation about God and the universe and whether meaning comes from within.",
    )
    db.session_summaries[summary_id] = {
        "id": summary_id,
        "user_id": "user-1",
        "source_id": archive["outbox"]["id"],
        "summary": "We talked about God and the universe.",
        "tags": ["personal"],
        "open_items": [],
        "key_decisions": [],
        "emotional_tone": "neutral",
        "occurred_at": datetime(2026, 5, 21, 11, 0),
    }
    db.source_archive_rows[archive["archive"]["id"]] = archive["archive"]
    db.outbox_rows[archive["outbox"]["id"]] = archive["outbox"]

    result = await recall_service.recall(
        db,
        user_id="user-1",
        query="remember that conversation about God and the universe",
        limit=5,
    )

    assert result["recall_type"] == "episodic"
    assert result["episodes"]
    assert any(item["type"] == "episode" for item in result["items"])
    assert any("God and the universe" in item["evidence_preview"] for item in result["episodes"])
    assert all(len(item["evidence_preview"]) < 200 for item in result["episodes"])


async def test_hybrid_query_returns_mixed_lane_results_and_preserves_labels() -> None:
    db = FakeDatabase()
    fact = _fact(user_id="user-1", title="Ashley", summary="Ashley is stressed about her job.")
    db.confirmed_facts[fact["row"]["id"]] = fact["row"]
    db.outbox_rows[fact["outbox_id"]] = {
        "id": fact["outbox_id"],
        "user_id": "user-1",
        "source_type": "chat",
        "raw_content": "preview",
        "received_at": datetime(2026, 5, 22, 10, 0),
        "status": "done",
        "retry_count": 0,
        "source_archive_id": None,
        "metadata": {},
    }
    thread = _fact(user_id="user-1", title="Waiting on Jordan contract", summary="Still waiting on Jordan.", fact_type="thread", confidence=0.88)
    db.confirmed_facts[thread["row"]["id"]] = thread["row"]
    db.outbox_rows[thread["outbox_id"]] = {
        "id": thread["outbox_id"],
        "user_id": "user-1",
        "source_type": "chat",
        "raw_content": "preview",
        "received_at": datetime(2026, 5, 22, 9, 0),
        "status": "done",
        "retry_count": 0,
        "source_archive_id": None,
        "metadata": {},
    }
    db.timeline_events.append(
        {
            "id": uuid4(),
            "user_id": "user-1",
            "event_type": "relationship_update",
            "title": "Ashley update",
            "summary": "Ashley has been under stress lately.",
            "occurred_at": datetime(2026, 5, 22, 9, 30),
            "observed_at": datetime(2026, 5, 22, 9, 30),
            "source_id": fact["outbox_id"],
            "related_fact_ids": [fact["row"]["id"]],
            "status": "current",
            "confidence": 0.8,
            "timeline_type": "relationship",
        }
    )

    result = await recall_service.recall(db, user_id="user-1", query="what happened with Ashley and Jordan", limit=5)

    assert result["recall_type"] == "hybrid"
    assert {item["type"] for item in result["items"]} >= {"fact", "continuity_note", "timeline_event"}
    assert all(item["metadata"]["lane"] in {"factual", "episodic", "continuity"} for item in result["items"])


async def test_weak_unmatched_query_and_user_isolation() -> None:
    db = FakeDatabase()
    other_archive = _archive(user_id="user-2", raw_content="User: secret other user transcript about Ashley.")
    db.source_archive_rows[other_archive["archive"]["id"]] = other_archive["archive"]
    db.outbox_rows[other_archive["outbox"]["id"]] = other_archive["outbox"]
    db.session_summaries[uuid4()] = {
        "id": uuid4(),
        "user_id": "user-2",
        "source_id": other_archive["outbox"]["id"],
        "summary": "Other user summary.",
        "tags": [],
        "open_items": [],
        "key_decisions": [],
        "emotional_tone": "neutral",
        "occurred_at": datetime(2026, 5, 21, 11, 0),
    }

    result = await recall_service.recall(db, user_id="user-1", query="nothingmatcheshere", limit=5)

    assert result["items"] == []
    assert result["weak_recall"] is True
    assert result["certainty"] == "low"
    assert result["facts"] == []
    assert result["episodes"] == []
    assert result["timeline"] == []


async def test_limit_and_recall_type_inference_respected() -> None:
    db = FakeDatabase()
    for idx in range(6):
        fact = _fact(user_id="user-1", title=f"Ashley {idx}", summary=f"Ashley {idx} is in memory.")
        db.confirmed_facts[fact["row"]["id"]] = fact["row"]
        db.outbox_rows[fact["outbox_id"]] = {
            "id": fact["outbox_id"],
            "user_id": "user-1",
            "source_type": "chat",
            "raw_content": "preview",
            "received_at": datetime(2026, 5, 22, 10, 0),
            "status": "done",
            "retry_count": 0,
            "source_archive_id": None,
            "metadata": {},
        }

    exact = await recall_service.recall(db, user_id="user-1", query="What is Ashley?", limit=3)
    hybrid = await recall_service.recall(db, user_id="user-1", query="Ashley", limit=3)

    assert exact["recall_type"] == "exact"
    assert hybrid["recall_type"] == "hybrid"
    assert len(exact["items"]) == 3
    assert len(hybrid["items"]) == 3
