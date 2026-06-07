from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_contract import AgentOutput
from core.api import app, get_database
from core import pipeline_runner
from runtime.cortex_client import CortexClient
from runtime.sophie_runtime import SophieRuntime


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
        if "FROM timeline_events" in query and len(args) == 1:
            user_id = args[0]
            return [event for event in self.timeline_events if event["user_id"] == user_id]
        if "FROM candidates" in query and "source_id = $1" in query:
            return [candidate for candidate in self.candidates.values() if candidate["source_id"] == args[0]]
        if "FROM confirmed_facts" in query:
            user_id = args[0]
            if len(args) > 1:
                limit = args[1]
                rows = [fact for fact in self.confirmed_facts.values() if fact["user_id"] == user_id and fact["status"] == "active"]
                return rows[:limit]
            return [fact for fact in self.confirmed_facts.values() if fact["user_id"] == user_id and fact["status"] == "active"]
        if "FROM timeline_events" in query:
            user_id = args[0]
            rows = [event for event in self.timeline_events if event["user_id"] == user_id]
            if len(args) > 1:
                return rows[: args[1]]
            return rows
        if "FROM session_summaries" in query:
            user_id = args[0]
            rows = [summary for summary in self.session_summaries.values() if summary["user_id"] == user_id]
            return sorted(rows, key=lambda row: row["occurred_at"], reverse=True)
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


class FakeV2Fallback:
    def get_startup_packet(self, user_id: str):
        return {"session_instructions": "fallback brief"}

    def recall(self, user_id: str, query_text: str):
        return {"facts": [], "summaries": [], "timeline": [], "certainty": "low"}

    def ingest_session(self, **payload):
        return {"status": "fallback"}


def _override_database(db: FakeDatabase):
    async def _dependency():
        yield db

    return _dependency


def _client_request_fn(test_client: TestClient):
    def _request(method: str, path: str, *, params=None, json_body=None):
        if method == "GET":
            response = test_client.get(path, params=params)
        else:
            response = test_client.post(path, json=json_body)
        response.raise_for_status()
        return response.json()

    return _request


def _messages():
    return [
        {"role": "user", "content": "Remind me to call Ashley tomorrow.", "timestamp": "2026-05-22T10:00:00Z"},
        {"role": "assistant", "content": "I can help with that.", "timestamp": "2026-05-22T10:00:10Z"},
    ]


def test_session_start_calls_instruction_packet_and_stores_context(monkeypatch) -> None:
    request_log: list[tuple[str, str]] = []

    def request_fn(method, path, *, params=None, json_body=None):
        request_log.append((method, path))
        return {
            "session_instructions": "Lead with the Ashley reminder.",
            "relevant_topics": ["Ashley reminder"],
            "worth_attention": [],
            "suggested_focus": "Ashley",
            "tone_note": "Practical.",
            "avoid": [],
            "stale_warnings": [],
        }

    runtime = SophieRuntime(
        cortex_client=CortexClient(request_fn=request_fn),
        fallback_client=FakeV2Fallback(),
        timezone="Europe/London",
        platform="ios",
    )

    context = runtime.start_session(user_id="user-1", session_id="session-1")

    assert request_log == [("GET", "/v3/sessions/instruction-packet")]
    assert context["instruction_packet"]["session_instructions"] == "Lead with the Ashley reminder."
    assert context["startup_source"] == "v3"


def test_recall_trigger_calls_cortex_and_uses_result() -> None:
    request_log: list[tuple[str, str, dict | None]] = []

    def request_fn(method, path, *, params=None, json_body=None):
        request_log.append((method, path, json_body))
        if path == "/v3/recall":
            return {
                "facts": [{"id": "1", "fact_type": "task", "content": {"title": "Call Ashley"}, "confidence": 0.95, "last_seen_at": "2026-05-22T12:00:00"}],
                "summaries": [],
                "timeline": [],
                "certainty": "high",
            }
        return {
            "session_instructions": "Brief",
            "relevant_topics": [],
            "worth_attention": [],
            "suggested_focus": "focus",
            "tone_note": "tone",
            "avoid": [],
            "stale_warnings": [],
        }

    runtime = SophieRuntime(
        cortex_client=CortexClient(request_fn=request_fn),
        fallback_client=FakeV2Fallback(),
    )
    context = runtime.start_session(user_id="user-1", session_id="session-1")

    result = runtime.handle_recall(context, message_text="Do you remember what I said about Ashley?")

    assert result is not None
    assert result["used_recall"] is True
    assert result["source"] == "v3"
    assert context["last_recall"]["certainty"] == "high"
    assert any(entry[1] == "/v3/recall" for entry in request_log)


def test_session_end_posts_full_transcript_fire_and_forget() -> None:
    captured: list[tuple[tuple, dict]] = []

    def scheduler(func, args, kwargs):
        captured.append((args, kwargs))
        func(**kwargs)

    requests: list[dict] = []

    def request_fn(method, path, *, params=None, json_body=None):
        if path == "/v3/session/ingest":
            requests.append(json_body)
            return {"success": True, "outbox_id": str(uuid4()), "status": "processing"}
        return {
            "session_instructions": "Brief",
            "relevant_topics": [],
            "worth_attention": [],
            "suggested_focus": "focus",
            "tone_note": "tone",
            "avoid": [],
            "stale_warnings": [],
        }

    runtime = SophieRuntime(
        cortex_client=CortexClient(request_fn=request_fn),
        fallback_client=FakeV2Fallback(),
        timezone="Europe/London",
        platform="ios",
        scheduler=scheduler,
    )
    context = runtime.start_session(user_id="user-1", session_id="session-1")

    runtime.close_session(context, messages=_messages())

    assert requests
    assert requests[0]["messages"] == _messages()
    assert requests[0]["metadata"] == {"timezone": "Europe/London", "platform": "ios"}


async def test_full_flow_ingest_then_new_session_uses_v3_packet_and_recall(monkeypatch) -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    scheduled_outbox_ids: list[UUID] = []
    monkeypatch.setattr("core.api.schedule_session_pipeline", lambda outbox_id: scheduled_outbox_ids.append(outbox_id))

    def fake_summary(agent_input):
        return AgentOutput(
            agent="session_summary_agent",
            status="success",
            items=[
                {
                    "summary": "The user asked for a reminder to call Ashley tomorrow.",
                    "tags": ["planning", "personal"],
                    "open_items": [{"item": "Call Ashley tomorrow"}],
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

    def fake_task(agent_input):
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
                    "raw_evidence": "Remind me to call Ashley tomorrow.",
                    "confidence": 0.95,
                    "related_people": ["Ashley"],
                    "related_projects": [],
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
                "reason": "new task",
            }
            for candidate in candidates
        ]

    def fake_surfacing(**kwargs):
        task_titles = [fact["content"]["title"] for fact in kwargs["tasks"]]
        return {
            "session_instructions": f"Remember the open task: {', '.join(task_titles)}." if task_titles else "No active task.",
            "relevant_topics": task_titles,
            "worth_attention": [
                {
                    "title": title,
                    "why_it_matters": "Open task from prior session.",
                    "suggested_way_to_raise": "Mention it if relevant.",
                    "sensitivity": "low",
                    "source_fact_ids": [],
                }
                for title in task_titles[:3]
            ],
            "suggested_focus": task_titles[0] if task_titles else "Current session",
            "tone_note": "Practical.",
            "avoid": [],
            "stale_warnings": [],
        }

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", fake_summary)
    monkeypatch.setattr("core.pipeline_runner.triage_agent.run", fake_triage)
    monkeypatch.setattr("core.pipeline_runner.task_agent.run", fake_task)
    monkeypatch.setattr("core.pipeline_runner.reconciliation.reconcile_candidates", fake_reconcile)
    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_surfacing)

    runtime = SophieRuntime(
        cortex_client=CortexClient(request_fn=_client_request_fn(client)),
        fallback_client=FakeV2Fallback(),
        timezone="Europe/London",
        platform="ios",
        scheduler=lambda func, args, kwargs: func(**kwargs),
    )

    first_context = runtime.start_session(user_id="user-1", session_id="session-1")
    runtime.close_session(first_context, messages=_messages())

    assert scheduled_outbox_ids
    await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=scheduled_outbox_ids[0])

    second_context = runtime.start_session(user_id="user-1", session_id="session-2")
    recall_result = runtime.handle_recall(second_context, message_text="Do you remember Ashley?")

    app.dependency_overrides.clear()
    assert second_context["instruction_packet"]["relevant_topics"] == ["Call Ashley"]
    assert recall_result is not None
    assert recall_result["recall_result"]["certainty"] == "high"
