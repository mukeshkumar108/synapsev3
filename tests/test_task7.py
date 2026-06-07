from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_contract import AgentOutput
from core.api import app, get_database
from core import pipeline_runner, recall as recall_service


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.outbox_rows: dict[UUID, dict] = {}
        self.source_archive_rows: dict[UUID, dict] = {}
        self.session_summaries: dict[UUID, dict] = {}
        self.candidates: dict[UUID, dict] = {}
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []

    async def execute(self, query: str, *args):
        if "INSERT INTO source_archive" in query:
            self.source_archive_rows[args[0]] = {
                "id": args[0],
                "user_id": args[1],
                "source_type": args[2],
                "source_external_id": args[3],
                "session_id": args[4],
                "conversation_id": args[5],
                "occurred_at": args[6],
                "captured_at": args[7],
                "payload": args[8],
                "metadata": args[9],
                "created_at": args[10],
            }
            return "INSERT 1"
        if "INSERT INTO outbox" in query:
            self.outbox_rows[args[0]] = {
                "id": args[0],
                "user_id": args[1],
                "source_type": args[2],
                "raw_content": args[3],
                "received_at": args[4],
                "status": args[5],
                "retry_count": args[6],
                "source_archive_id": args[7] if len(args) > 8 else None,
                "metadata": args[8] if len(args) > 8 else args[7],
            }
            return "INSERT 1"
        if "UPDATE outbox" in query and "SET status" in query:
            self.outbox_rows[args[0]]["status"] = args[1]
            return "UPDATE 1"
        if "INSERT INTO session_summaries" in query:
            self.session_summaries[args[0]] = {
                "id": args[0],
                "user_id": args[1],
                "source_id": args[2],
                "summary": args[3],
                "tags": args[4],
                "open_items": args[5],
                "key_decisions": args[6],
                "emotional_tone": args[7],
                "occurred_at": args[8],
            }
            return "INSERT 1"
        if "INSERT INTO timeline_events" in query:
            self.timeline_events.append(
                {
                    "id": args[0],
                    "user_id": args[1],
                    "event_type": args[2],
                    "timeline_type": args[3],
                    "title": args[4],
                    "summary": args[5],
                    "occurred_at": args[6],
                    "observed_at": args[7],
                    "source_id": args[8],
                    "related_fact_ids": args[9],
                    "status": args[10],
                    "confidence": args[11],
                }
            )
            return "INSERT 1"
        if "INSERT INTO candidates" in query:
            self.candidates[args[0]] = {
                "id": args[0],
                "user_id": args[1],
                "source_id": args[2],
                "candidate_type": args[3],
                "content": args[4],
                "raw_evidence": args[5],
                "confidence": args[6],
                "needs_confirmation": args[7],
                "status": args[8],
                "reconciliation_instruction": args[9],
                "merge_target_id": args[10],
                "created_at": args[11],
            }
            return "INSERT 1"
        if "UPDATE candidates" in query and "reconciliation_instruction" in query:
            candidate = self.candidates[args[0]]
            candidate["reconciliation_instruction"] = args[1]
            candidate["merge_target_id"] = args[2]
            return "UPDATE 1"
        if "UPDATE candidates" in query and "status = 'confirmed'" in query:
            self.candidates[args[0]]["status"] = "confirmed"
            return "UPDATE 1"
        if "INSERT INTO confirmed_facts" in query:
            self.confirmed_facts[args[0]] = {
                "id": args[0],
                "user_id": args[1],
                "fact_type": args[2],
                "domain": args[3],
                "content": args[4],
                "confidence": args[5],
                "first_seen_at": args[6],
                "last_seen_at": args[7],
                "last_confirmed_at": args[8],
                "source_ids": args[9],
                "status": args[10],
                "user_corrected": args[11],
                "correction_note": args[12],
                "expires_at": args[13],
            }
            return "INSERT 1"
        return "OK"

    async def fetch(self, query: str, *args):
        if "FROM source_archive" in query:
            user_id = args[0]
            rows = [row for row in self.source_archive_rows.values() if row["user_id"] == user_id]
            return sorted(rows, key=lambda row: row["captured_at"], reverse=True)
        if "FROM outbox" in query:
            user_id = args[0]
            rows = [row for row in self.outbox_rows.values() if row["user_id"] == user_id]
            return sorted(rows, key=lambda row: row["received_at"], reverse=True)
        if "FROM timeline_events" in query and len(args) == 1:
            user_id = args[0]
            return [event for event in self.timeline_events if event["user_id"] == user_id]
        if "FROM candidates" in query and "source_id = $1" in query:
            return [candidate for candidate in self.candidates.values() if candidate["source_id"] == args[0]]
        if "FROM confirmed_facts" in query:
            if "LIMIT $2" in query:
                user_id = args[0]
                limit = args[1]
                rows = [fact for fact in self.confirmed_facts.values() if fact["user_id"] == user_id and fact["status"] == "active"]
                return rows[:limit]
            user_id = args[0]
            return [fact for fact in self.confirmed_facts.values() if fact["user_id"] == user_id and fact["status"] == "active"]
        if "FROM session_summaries" in query:
            user_id = args[0]
            rows = [summary for summary in self.session_summaries.values() if summary["user_id"] == user_id]
            return sorted(rows, key=lambda row: row["occurred_at"], reverse=True)
        if "FROM timeline_events" in query:
            user_id = args[0]
            rows = [event for event in self.timeline_events if event["user_id"] == user_id]
            return rows
        if "FROM candidates" in query:
            user_id = args[0]
            return [candidate for candidate in self.candidates.values() if candidate["user_id"] == user_id and candidate["status"] == "pending"]
        return []

    async def fetchone(self, query: str, *args):
        if "FROM outbox" in query:
            return self.outbox_rows.get(args[0])
        if "FROM session_summaries" in query and "source_id = $1" in query:
            for row in self.session_summaries.values():
                if row["source_id"] == args[0]:
                    return row
            return None
        if "FROM source_archive" in query and "session_id" in query:
            for row in self.source_archive_rows.values():
                if row["user_id"] == args[0] and row["source_type"] == args[1] and row["session_id"] == args[2]:
                    return row
            return None
        if "FROM source_archive" in query:
            row = self.source_archive_rows.get(args[0])
            if row and row["user_id"] == args[1]:
                return row
        return None

    async def close(self):
        return None


def _override_database(db: FakeDatabase):
    async def _dependency():
        yield db

    return _dependency


def _ashley_transcript() -> list[dict]:
    return [
        {
            "role": "user",
            "content": "Ashley is stressed about her job and I should check in with her.",
            "timestamp": "2026-05-22T10:00:00Z",
        },
        {
            "role": "assistant",
            "content": "I can remember that.",
            "timestamp": "2026-05-22T10:00:10Z",
        },
    ]


async def _ingest_ashley_memory(db: FakeDatabase, monkeypatch) -> None:
    created = await pipeline_runner.create_session_outbox(
        db,
        user_id="user-1",
        session_id="ashley-1",
        messages=_ashley_transcript(),
        source_type="chat",
        metadata={"timezone": "Europe/London"},
    )

    def fake_summary(agent_input):
        return AgentOutput(
            agent="session_summary_agent",
            status="success",
            items=[
                {
                    "summary": "The user said Ashley is stressed about her job and wants to check in with her.",
                    "tags": ["relationship", "personal"],
                    "open_items": [{"item": "Check in with Ashley"}],
                    "key_decisions": [],
                    "emotional_tone": "neutral",
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    def fake_triage(agent_input):
        return AgentOutput(
            agent="triage_agent",
            status="success",
            items=[
                {
                    "has_tasks": False,
                    "has_events": False,
                    "has_facts": True,
                    "has_state_change": False,
                    "has_threads": False,
                    "has_invitations": False,
                    "session_kind": "personal",
                    "emotional_weight": "medium",
                    "emotional_note": None,
                    "tension_signal": None,
                    "ignore_reasons": [],
                    "memory_worthy": True,
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    def fake_fact(agent_input):
        return AgentOutput(
            agent="fact_agent",
            status="success",
            items=[
                {
                    "subject": "Ashley",
                    "fact_type": "relationship",
                    "content": "Ashley is stressed about her job.",
                    "about_user": False,
                    "person_name": "Ashley",
                    "related_people": ["Ashley"],
                    "related_projects": [],
                    "salience": "high",
                    "sensitivity": "medium",
                    "needs_confirmation": False,
                    "raw_evidence": "Ashley is stressed about her job and I should check in with her.",
                    "confidence": 0.9,
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    async def fake_reconcile(database, *, candidates):
        return [
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "CREATE",
                "target_id": None,
                "confidence_delta": 0.0,
                "reason": "new fact",
            }
            for candidate in candidates
        ]

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", fake_summary)
    monkeypatch.setattr("core.pipeline_runner.triage_agent.run", fake_triage)
    monkeypatch.setattr("core.pipeline_runner.fact_agent.run", fake_fact)
    monkeypatch.setattr("core.pipeline_runner.reconciliation.reconcile_candidates", fake_reconcile)

    await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=created["outbox_id"])


async def test_recall_ashley_returns_fact_or_summary(monkeypatch) -> None:
    db = FakeDatabase()
    await _ingest_ashley_memory(db, monkeypatch)

    result = await recall_service.recall(db, user_id="user-1", query="Ashley", limit=5)

    assert result["certainty"] in {"high", "partial"}
    assert result["facts"] or result["summaries"]


def test_post_recall_unmatched_query_returns_low_and_no_hallucinations() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    response = client.post("/v3/recall", json={"user_id": "user-1", "query": "nothingmatcheshere", "limit": 5})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["facts"] == []
    assert body["summaries"] == []
    assert body["timeline"] == []
    assert body["episodes"] == []
    assert body["continuity"] == []
    assert body["items"] == []
    assert body["weak_recall"] is True
    assert body["certainty"] == "low"


def test_post_recall_empty_state_returns_valid_shape() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    response = client.post("/v3/recall", json={"user_id": "user-1", "query": "Ashley"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert {"items", "facts", "summaries", "episodes", "continuity", "timeline", "recall_type", "weak_recall", "weak_recall_reason", "certainty"} <= set(body)
    assert isinstance(body["facts"], list)
    assert isinstance(body["summaries"], list)
    assert isinstance(body["timeline"], list)
    assert isinstance(body["items"], list)
    assert body["certainty"] == "low"


async def test_recall_limit_is_respected() -> None:
    db = FakeDatabase()
    for index in range(7):
        fact_id = uuid4()
        db.confirmed_facts[fact_id] = {
            "id": fact_id,
            "user_id": "user-1",
            "fact_type": "relationship",
            "domain": "people",
            "content": {
                "schema_version": "v1",
                "item_type": "fact",
                "title": f"Ashley {index}",
                "summary": f"Ashley note {index}",
                "salience": "medium",
                "priority": None,
                "urgency": None,
                "importance": "medium",
                "sensitivity": "low",
                "time": {},
                "links": {"people": ["Ashley"], "projects": [], "related_facts": [], "related_threads": []},
                "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
                "evidence": {"raw_evidence": f"Ashley note {index}", "source_turn_refs": []},
                "metadata": {"companion_category": None, "agent_item": {"fact_type": "relationship"}},
            },
            "confidence": 0.9,
            "first_seen_at": datetime(2026, 5, 22, 12, 0),
            "last_seen_at": datetime(2026, 5, 22, 12, 0),
            "last_confirmed_at": datetime(2026, 5, 22, 12, 0),
            "source_ids": [uuid4()],
            "status": "active",
            "user_corrected": False,
            "correction_note": None,
            "expires_at": None,
        }

    result = await recall_service.recall(db, user_id="user-1", query="Ashley", limit=3)

    assert len(result["facts"]) <= 3


async def test_recall_punctuation_matches_name() -> None:
    db = FakeDatabase()
    with pytest.MonkeyPatch.context() as monkeypatch:
        await _ingest_ashley_memory(db, monkeypatch=monkeypatch)

    result = await recall_service.recall(db, user_id="user-1", query="Ashley?", limit=5)

    assert result["facts"]
    assert result["certainty"] == "high"


async def test_recall_typo_matches_name_conservatively() -> None:
    db = FakeDatabase()
    with pytest.MonkeyPatch.context() as monkeypatch:
        await _ingest_ashley_memory(db, monkeypatch=monkeypatch)

    result = await recall_service.recall(db, user_id="user-1", query="Ashly", limit=5)

    assert result["facts"] or result["summaries"]
    assert result["certainty"] in {"partial", "high"}


async def test_recall_transposed_typo_matches_name_conservatively() -> None:
    db = FakeDatabase()
    with pytest.MonkeyPatch.context() as monkeypatch:
        await _ingest_ashley_memory(db, monkeypatch=monkeypatch)

    result = await recall_service.recall(db, user_id="user-1", query="Ahsley", limit=5)

    assert result["facts"] or result["summaries"]
    assert result["certainty"] in {"partial", "high"}


async def test_recall_phrase_matches_session_summary() -> None:
    db = FakeDatabase()
    summary_id = uuid4()
    db.session_summaries[summary_id] = {
        "id": summary_id,
        "user_id": "user-1",
        "source_id": uuid4(),
        "summary": "We talked about God and the universe and what it all means.",
        "tags": ["personal"],
        "open_items": [],
        "key_decisions": [],
        "emotional_tone": "neutral",
        "occurred_at": datetime(2026, 5, 22, 12, 0),
    }

    result = await recall_service.recall(db, user_id="user-1", query="God and the universe", limit=5)

    assert result["summaries"]
    assert result["certainty"] == "partial"


async def test_unrelated_typo_does_not_match_random_memory() -> None:
    db = FakeDatabase()
    fact_id = uuid4()
    db.confirmed_facts[fact_id] = {
        "id": fact_id,
        "user_id": "user-1",
        "fact_type": "relationship",
        "domain": "people",
        "content": {
            "schema_version": "v1",
            "item_type": "fact",
            "title": "Morgan",
            "summary": "Morgan likes cycling on weekends.",
            "salience": "medium",
            "priority": None,
            "urgency": None,
            "importance": "medium",
            "sensitivity": "low",
            "time": {},
            "links": {"people": ["Morgan"], "projects": [], "related_facts": [], "related_threads": []},
            "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
            "evidence": {"raw_evidence": "Morgan likes cycling.", "source_turn_refs": []},
            "metadata": {"companion_category": None, "agent_item": {"fact_type": "relationship"}},
        },
        "confidence": 0.9,
        "first_seen_at": datetime(2026, 5, 22, 12, 0),
        "last_seen_at": datetime(2026, 5, 22, 12, 0),
        "last_confirmed_at": datetime(2026, 5, 22, 12, 0),
        "source_ids": [uuid4()],
        "status": "active",
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }

    result = await recall_service.recall(db, user_id="user-1", query="Zxqly", limit=5)

    assert result["facts"] == []
    assert result["summaries"] == []
    assert result["timeline"] == []
    assert result["certainty"] == "low"


async def test_short_tokens_do_not_fuzzy_match_broadly() -> None:
    db = FakeDatabase()
    with pytest.MonkeyPatch.context() as monkeypatch:
        await _ingest_ashley_memory(db, monkeypatch=monkeypatch)

    result = await recall_service.recall(db, user_id="user-1", query="he", limit=5)

    assert result["certainty"] == "low"
    assert result["facts"] == []
