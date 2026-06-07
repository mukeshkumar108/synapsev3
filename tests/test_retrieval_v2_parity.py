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


def _fact(*, user_id: str, title: str, summary: str, fact_type: str = "relationship", confidence: float = 0.95) -> tuple[dict, UUID]:
    fact_id = uuid4()
    outbox_id = uuid4()
    row = {
        "id": fact_id,
        "user_id": user_id,
        "fact_type": fact_type,
        "domain": "people" if fact_type == "relationship" else "obligations",
        "content": {
            "schema_version": "v1",
            "item_type": "fact" if fact_type != "thread" else "thread",
            "title": title,
            "summary": summary,
            "links": {"people": [title], "projects": [], "topics": [], "related_facts": [], "related_threads": []},
            "metadata": {"agent_item": {}, "companion_category": None, "open_loop_status": "active" if fact_type == "thread" else None},
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
    }
    return row, outbox_id


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


async def test_recall_v2_exact_mode_matches_current_fact_priority() -> None:
    db = FakeDatabase()
    fact, outbox_id = _fact(user_id="user-1", title="Ashley", summary="Ashley is stressed about her job.")
    db.confirmed_facts[fact["id"]] = fact
    db.outbox_rows[outbox_id] = {"id": outbox_id, "user_id": "user-1", "source_type": "chat", "raw_content": "preview", "received_at": datetime(2026, 5, 22, 10, 0), "status": "done", "retry_count": 0, "source_archive_id": None, "metadata": {}}

    result = await recall_service.recall(db, user_id="user-1", query="Who is Ashley?", limit=5)

    assert result["recall_type"] == "exact"
    assert result["certainty"] == "high"
    assert result["items"][0]["type"] == "fact"
    assert result["facts"][0]["title"] == "Ashley"


async def test_recall_v2_episodic_mode_matches_current_episode_priority() -> None:
    db = FakeDatabase()
    summary_id = uuid4()
    archive = _archive(user_id="user-1", raw_content="User: We had that conversation about God and the universe and whether meaning comes from within.")
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

    result = await recall_service.recall(db, user_id="user-1", query="remember that conversation about God and the universe", limit=5)

    assert result["recall_type"] == "episodic"
    assert result["episodes"]
    assert any(item["metadata"]["source_kind"] == "session_summary" for item in result["episodes"])


async def test_recall_v2_unmatched_query_preserves_weak_recall_contract() -> None:
    db = FakeDatabase()
    result = await recall_service.recall(db, user_id="user-1", query="absolutely unrelated query text", limit=5)
    assert result["items"] == []
    assert result["weak_recall"] is True
    assert result["certainty"] == "low"
