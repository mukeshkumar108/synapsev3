from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from agent_contract import AgentOutput
from core import pipeline_runner, source_archive
from core.api import app, get_database


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.source_archive_rows: dict[UUID, dict] = {}
        self.outbox_rows: dict[UUID, dict] = {}
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
            self.candidates[args[0]]["reconciliation_instruction"] = args[1]
            self.candidates[args[0]]["merge_target_id"] = args[2]
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
        return "OK"

    async def fetch(self, query: str, *args):
        if "FROM timeline_events" in query and len(args) == 1:
            return [row for row in self.timeline_events if row["user_id"] == args[0]]
        if "FROM candidates" in query and "source_id = $1" in query:
            return [row for row in self.candidates.values() if row["source_id"] == args[0]]
        if "FROM candidates" in query:
            return [row for row in self.candidates.values() if row["user_id"] == args[0] and row["status"] == "pending"]
        if "FROM confirmed_facts" in query:
            rows = [row for row in self.confirmed_facts.values() if row["user_id"] == args[0] and row["status"] == "active"]
            if len(args) > 1:
                return rows[: args[1]]
            return rows
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
        return None

    async def close(self):
        return None


def _override_database(db: FakeDatabase):
    async def _dependency():
        yield db

    return _dependency


def _session_payload() -> dict:
    return {
        "user_id": "user-1",
        "session_id": "session-1",
        "source_type": "chat",
        "metadata": {"timezone": "Europe/London", "platform": "ios"},
        "messages": [
            {"role": "user", "content": "I need to call Ashley tomorrow.", "timestamp": "2026-05-22T10:00:00Z"},
            {"role": "assistant", "content": "Okay.", "timestamp": "2026-05-22T10:00:05Z"},
        ],
    }


def test_session_ingest_creates_source_archive_and_outbox_reference(monkeypatch) -> None:
    db = FakeDatabase()
    scheduled: list[UUID] = []
    monkeypatch.setattr("core.api.schedule_session_pipeline", lambda outbox_id: scheduled.append(outbox_id))
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    response = client.post("/v3/session/ingest", json=_session_payload())

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(db.source_archive_rows) == 1
    assert len(db.outbox_rows) == 1
    archive_row = next(iter(db.source_archive_rows.values()))
    outbox_row = next(iter(db.outbox_rows.values()))
    assert outbox_row["source_archive_id"] == archive_row["id"]
    assert outbox_row["metadata"]["source_archive_id"] == str(archive_row["id"])
    assert archive_row["payload"]["messages"][0]["content"] == "I need to call Ashley tomorrow."
    assert "[Turn 0] User: I need to call Ashley tomorrow." in archive_row["payload"]["raw_content"]

    assert outbox_row["raw_content"] != archive_row["payload"]["raw_content"]
    assert scheduled == [UUID(response.json()["outbox_id"])]


async def test_pipeline_loads_transcript_from_source_archive(monkeypatch) -> None:
    db = FakeDatabase()
    created = await pipeline_runner.create_session_outbox(
        db,
        user_id="user-1",
        session_id="session-1",
        messages=_session_payload()["messages"],
        source_type="chat",
        metadata={"timezone": "Europe/London"},
    )
    db.outbox_rows[created["outbox_id"]]["raw_content"] = None

    def fake_summary(agent_input):
        assert "Ashley tomorrow" in agent_input.raw_content
        return AgentOutput(
            agent="session_summary_agent",
            status="success",
            items=[
                {
                    "summary": "The user needs to call Ashley tomorrow.",
                    "tags": ["planning", "personal"],
                    "open_items": [{"item": "Call Ashley tomorrow"}],
                    "key_decisions": [],
                    "emotional_tone": "neutral",
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    def fake_triage(_agent_input):
        return AgentOutput(
            agent="triage_agent",
            status="success",
            items=[
                {
                    "has_tasks": True,
                    "has_events": False,
                    "has_facts": False,
                    "has_state_change": False,
                    "has_threads": False,
                    "has_invitations": False,
                    "session_kind": "personal",
                    "emotional_weight": "low",
                    "emotional_note": None,
                    "tension_signal": None,
                    "ignore_reasons": [],
                    "memory_worthy": True,
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    def fake_task(_agent_input):
        return AgentOutput(
            agent="task_agent",
            status="success",
            items=[
                {
                    "title": "Call Ashley",
                    "description": None,
                    "due_date": None,
                    "reminder_at": None,
                    "priority": "high",
                    "urgency": "high",
                    "is_habit": False,
                    "recurrence": None,
                    "waiting_on": None,
                    "needs_confirmation": False,
                    "salience": "high",
                    "raw_evidence": "I need to call Ashley tomorrow.",
                    "confidence": 0.95,
                    "related_people": ["Ashley"],
                    "related_projects": [],
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    async def fake_reconcile(_database, *, candidates):
        return [
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "CREATE",
                "target_id": None,
                "confidence_delta": 0.0,
                "reason": "new task",
            }
            for candidate in candidates
        ]

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", fake_summary)
    monkeypatch.setattr("core.pipeline_runner.triage_agent.run", fake_triage)
    monkeypatch.setattr("core.pipeline_runner.task_agent.run", fake_task)
    monkeypatch.setattr("core.pipeline_runner.reconciliation.reconcile_candidates", fake_reconcile)

    result = await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=created["outbox_id"])

    assert result["status"] == "done"
    assert len(db.confirmed_facts) == 1


async def test_done_and_failed_pipeline_preserve_source_archive(monkeypatch) -> None:
    db = FakeDatabase()
    created = await pipeline_runner.create_session_outbox(
        db,
        user_id="user-1",
        session_id="session-1",
        messages=_session_payload()["messages"],
        source_type="chat",
        metadata={"timezone": "Europe/London"},
    )
    archive_id = created["source_archive_id"]
    before_payload = db.source_archive_rows[archive_id]["payload"]

    def fake_summary(_agent_input):
        raise RuntimeError("boom")

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", fake_summary)
    with pytest.raises(RuntimeError, match="boom"):
        await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=created["outbox_id"])

    assert db.outbox_rows[created["outbox_id"]]["status"] == "failed"
    assert db.source_archive_rows[archive_id]["payload"] == before_payload


async def test_duplicate_ingest_reuses_source_archive() -> None:
    db = FakeDatabase()

    first = await pipeline_runner.create_session_outbox(
        db,
        user_id="user-1",
        session_id="session-1",
        messages=_session_payload()["messages"],
        source_type="chat",
        metadata={"timezone": "Europe/London"},
    )
    second = await pipeline_runner.create_session_outbox(
        db,
        user_id="user-1",
        session_id="session-1",
        messages=_session_payload()["messages"],
        source_type="chat",
        metadata={"timezone": "Europe/London"},
    )

    assert len(db.source_archive_rows) == 1
    assert db.outbox_rows[first["outbox_id"]]["source_archive_id"] == db.outbox_rows[second["outbox_id"]]["source_archive_id"]


async def test_user_isolation_and_generic_payload_shapes() -> None:
    db = FakeDatabase()
    email_row = await source_archive.create_source_archive(
        db,
        user_id="user-1",
        source_type="email",
        source_external_id="email-1",
        payload={"subject": "Hello", "body": "World"},
        metadata={"provider": "gmail"},
    )
    calendar_row = await source_archive.create_source_archive(
        db,
        user_id="user-1",
        source_type="calendar",
        source_external_id="evt-1",
        payload={"title": "Meeting", "starts_at": "2026-05-23T10:00:00+01:00"},
        metadata={"provider": "google"},
    )
    batch_row = await source_archive.create_source_archive(
        db,
        user_id="user-1",
        source_type="message_batch",
        payload={"messages": [{"from": "A", "text": "Hi"}]},
        metadata={"channel": "sms"},
    )

    assert await source_archive.get_source_archive_for_user(db, source_archive_id=email_row["id"], user_id="user-2") is None
    assert (await source_archive.get_source_archive_for_user(db, source_archive_id=email_row["id"], user_id="user-1"))["payload"]["subject"] == "Hello"
    assert db.source_archive_rows[calendar_row["id"]]["payload"]["title"] == "Meeting"
    assert db.source_archive_rows[batch_row["id"]]["payload"]["messages"][0]["text"] == "Hi"
