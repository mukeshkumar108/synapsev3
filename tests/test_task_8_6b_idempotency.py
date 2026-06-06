from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from agent_contract import AgentOutput
from core import pipeline_runner


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
                "source_archive_id": args[7],
                "metadata": args[8],
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
                "fact_type": args[4],
                "content": args[5],
                "structured_content": args[6],
                "raw_evidence": args[7],
                "confidence": args[8],
                "needs_confirmation": args[9],
                "status": args[10],
                "reconciliation_instruction": args[11],
                "merge_target_id": args[12],
                "created_at": args[13],
            }
            return "INSERT 1"
        if "UPDATE candidates" in query and "reconciliation_instruction" in query:
            self.candidates[args[0]]["reconciliation_instruction"] = args[1]
            self.candidates[args[0]]["merge_target_id"] = args[2]
            return "UPDATE 1"
        if "UPDATE candidates" in query and "status = 'confirmed'" in query:
            self.candidates[args[0]]["status"] = "confirmed"
            return "UPDATE 1"
        if "UPDATE candidates" in query and "status = 'dismissed'" in query:
            self.candidates[args[0]]["status"] = "dismissed"
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
                "structured_content": args[14],
                "source_type": args[15],
                "primary_source_id": args[16],
                "who_said_it": args[17],
                "original_text": args[18],
                "channel": args[19],
                "conversation_id": args[20],
                "created_from": args[21],
                "provenance": args[22],
                "starts_at": args[23],
                "ends_at": args[24],
                "due_at": args[25],
                "remind_at": args[26],
                "timezone": args[27],
                "recurrence_rule": args[28],
                "completed_at": args[29],
                "cancelled_at": args[30],
                "priority": args[31],
                "follow_up_needed": args[32],
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
        if "UPDATE confirmed_facts" in query:
            fact = self.confirmed_facts[args[0]]
            fact["content"] = args[1]
            fact["structured_content"] = args[2]
            fact["confidence"] = args[3]
            fact["last_seen_at"] = args[4]
            fact["last_confirmed_at"] = args[5]
            fact["source_ids"] = args[6]
            fact["expires_at"] = args[10]
            fact["source_type"] = args[11]
            fact["primary_source_id"] = args[12]
            fact["who_said_it"] = args[13]
            fact["original_text"] = args[14]
            fact["channel"] = args[15]
            fact["conversation_id"] = args[16]
            fact["created_from"] = args[17]
            fact["provenance"] = args[18]
            fact["starts_at"] = args[19]
            fact["ends_at"] = args[20]
            fact["due_at"] = args[21]
            fact["remind_at"] = args[22]
            fact["timezone"] = args[23]
            fact["recurrence_rule"] = args[24]
            fact["completed_at"] = args[25]
            fact["cancelled_at"] = args[26]
            fact["priority"] = args[27]
            fact["follow_up_needed"] = args[28]
            return "UPDATE 1"
        return "OK"

    async def fetch(self, query: str, *args):
        if "FROM candidates" in query and "source_id = $1" in query:
            return [row for row in self.candidates.values() if row["source_id"] == args[0]]
        if "FROM candidates" in query:
            return [row for row in self.candidates.values() if row["user_id"] == args[0] and row["status"] == "pending"]
        if "FROM confirmed_facts" in query:
            rows = [row for row in self.confirmed_facts.values() if row["user_id"] == args[0] and row["status"] == "active"]
            if len(args) > 1:
                return rows[: args[1]]
            return rows
        if "FROM timeline_events" in query:
            return [row for row in self.timeline_events if row["user_id"] == args[0]]
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
        if "FROM confirmed_facts" in query:
            return self.confirmed_facts.get(args[0])
        return None

    async def close(self):
        return None


def _messages(content: str = "I need to call Ashley tomorrow.") -> list[dict]:
    return [
        {"role": "user", "content": content, "timestamp": "2026-05-22T10:00:00Z"},
        {"role": "assistant", "content": "Okay.", "timestamp": "2026-05-22T10:00:05Z"},
    ]


def _fake_summary(_agent_input):
    return AgentOutput(
        agent="session_summary_agent",
        status="success",
        items=[{"summary": "The user needs to call Ashley tomorrow.", "tags": ["planning", "personal"], "open_items": [{"item": "Call Ashley tomorrow"}], "key_decisions": [], "emotional_tone": "neutral"}],
        errors=[],
        confidence_notes="ok",
    )


def _fake_triage(_agent_input):
    return AgentOutput(
        agent="triage_agent",
        status="success",
        items=[{"has_tasks": True, "has_events": False, "has_facts": False, "has_state_change": False, "has_threads": False, "has_invitations": False, "session_kind": "personal", "emotional_weight": "low", "emotional_note": None, "tension_signal": None, "ignore_reasons": [], "memory_worthy": True}],
        errors=[],
        confidence_notes="ok",
    )


def _fake_task(_agent_input):
    return AgentOutput(
        agent="task_agent",
        status="success",
        items=[{"title": "Call Ashley", "description": None, "due_date": None, "reminder_at": None, "priority": "high", "urgency": "high", "is_habit": False, "recurrence": None, "waiting_on": None, "needs_confirmation": False, "salience": "high", "raw_evidence": "I need to call Ashley tomorrow.", "confidence": 0.95, "related_people": ["Ashley"], "related_projects": []}],
        errors=[],
        confidence_notes="ok",
    )


async def _fake_reconcile(_database, *, candidates):
    return [{"candidate_id": str(candidate["id"]), "instruction": "CREATE", "target_id": None, "confidence_delta": 0.0, "reason": "new task"} for candidate in candidates]


async def test_rerunning_same_outbox_does_not_duplicate_memory(monkeypatch) -> None:
    db = FakeDatabase()
    created = await pipeline_runner.create_session_outbox(db, user_id="user-1", session_id="session-1", messages=_messages(), source_type="chat", metadata={"timezone": "Europe/London"})

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", _fake_summary)
    monkeypatch.setattr("core.pipeline_runner.triage_agent.run", _fake_triage)
    monkeypatch.setattr("core.pipeline_runner.task_agent.run", _fake_task)
    monkeypatch.setattr("core.pipeline_runner.reconciliation.reconcile_candidates", _fake_reconcile)

    first = await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=created["outbox_id"])
    first_counts = (len(db.session_summaries), len(db.candidates), len(db.confirmed_facts), len(db.timeline_events))
    second = await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=created["outbox_id"])
    second_counts = (len(db.session_summaries), len(db.candidates), len(db.confirmed_facts), len(db.timeline_events))

    assert first["status"] == "done"
    assert second["status"] == "done"
    assert first_counts == second_counts == (1, 1, 1, 2)


async def test_failed_run_preserves_source_archive_and_retry_recovers_without_duplicates(monkeypatch) -> None:
    db = FakeDatabase()
    created = await pipeline_runner.create_session_outbox(db, user_id="user-1", session_id="session-1", messages=_messages(), source_type="chat", metadata={"timezone": "Europe/London"})
    archive_id = created["source_archive_id"]
    original_payload = db.source_archive_rows[archive_id]["payload"]

    def failing_summary(_agent_input):
        raise RuntimeError("boom")

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", failing_summary)
    with pytest.raises(RuntimeError, match="boom"):
        await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=created["outbox_id"])

    assert db.outbox_rows[created["outbox_id"]]["status"] == "failed"
    assert db.source_archive_rows[archive_id]["payload"] == original_payload

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", _fake_summary)
    monkeypatch.setattr("core.pipeline_runner.triage_agent.run", _fake_triage)
    monkeypatch.setattr("core.pipeline_runner.task_agent.run", _fake_task)
    monkeypatch.setattr("core.pipeline_runner.reconciliation.reconcile_candidates", _fake_reconcile)

    retry = await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=created["outbox_id"])

    assert retry["status"] == "done"
    assert len(db.session_summaries) == 1
    assert len(db.candidates) == 1
    assert len(db.confirmed_facts) == 1
    assert len(db.timeline_events) == 2


async def test_similar_content_different_sessions_and_same_session_id_different_users_do_not_collide(monkeypatch) -> None:
    db = FakeDatabase()
    first = await pipeline_runner.create_session_outbox(db, user_id="user-1", session_id="session-1", messages=_messages("I need to call Ashley tomorrow."), source_type="chat", metadata={"timezone": "Europe/London"})
    second = await pipeline_runner.create_session_outbox(db, user_id="user-1", session_id="session-2", messages=_messages("I need to call Ashley tomorrow."), source_type="chat", metadata={"timezone": "Europe/London"})
    third = await pipeline_runner.create_session_outbox(db, user_id="user-2", session_id="session-1", messages=_messages("I need to call Ashley tomorrow."), source_type="chat", metadata={"timezone": "Europe/London"})

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", _fake_summary)
    monkeypatch.setattr("core.pipeline_runner.triage_agent.run", _fake_triage)
    monkeypatch.setattr("core.pipeline_runner.task_agent.run", _fake_task)
    monkeypatch.setattr("core.pipeline_runner.reconciliation.reconcile_candidates", _fake_reconcile)

    await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=first["outbox_id"])
    await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=second["outbox_id"])
    await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=third["outbox_id"])

    assert len(db.source_archive_rows) == 3
    assert len(db.outbox_rows) == 3
    assert len(db.confirmed_facts) == 3
    assert {row["user_id"] for row in db.confirmed_facts.values()} == {"user-1", "user-2"}
