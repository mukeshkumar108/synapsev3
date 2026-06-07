from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from core import calendar_import, pipeline_runner, recall as recall_service, reconciliation, serving
from core.config import get_settings
from runtime.cortex_client import CortexClient
from runtime.sophie_runtime import SophieRuntime


pytestmark = pytest.mark.anyio


class FakeServingDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: list[dict] = []
        self.timeline_events: list[dict] = []

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            return [fact for fact in self.confirmed_facts if fact["user_id"] == args[0] and fact["status"] == "active"]
        if "FROM timeline_events" in query:
            return [event for event in self.timeline_events if event["user_id"] == args[0]][: args[1]]
        return []


class FakePipelineDatabase:
    def __init__(self) -> None:
        self.outbox_rows: dict[UUID, dict] = {}
        self.source_archive_rows: dict[UUID, dict] = {}

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
        return "OK"

    async def fetchone(self, query: str, *args):
        if "FROM outbox" in query:
            return self.outbox_rows.get(args[0])
        if "FROM session_summaries" in query and "source_id = $1" in query:
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


class FakeRecallDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: list[dict] = []
        self.session_summaries: list[dict] = []
        self.timeline_events: list[dict] = []

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            return [fact for fact in self.confirmed_facts if fact["user_id"] == args[0] and fact["status"] == "active"]
        if "FROM session_summaries" in query:
            return [summary for summary in self.session_summaries if summary["user_id"] == args[0]]
        if "FROM timeline_events" in query:
            return [event for event in self.timeline_events if event["user_id"] == args[0]]
        return []


class FakeCalendarDatabase:
    def __init__(self) -> None:
        self.outbox_rows: dict[UUID, dict] = {}
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []

    async def execute(self, query: str, *args):
        if "INSERT INTO outbox" in query:
            self.outbox_rows[args[0]] = {
                "id": args[0],
                "user_id": args[1],
                "source_type": args[2],
                "raw_content": args[3],
                "received_at": args[4],
                "status": args[5],
                "retry_count": args[6],
                "metadata": args[7],
            }
            return "INSERT 1"
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
        if "UPDATE confirmed_facts" in query:
            fact = self.confirmed_facts[args[0]]
            fact["content"] = args[1]
            fact["confidence"] = args[2]
            fact["last_seen_at"] = args[3]
            fact["last_confirmed_at"] = args[4]
            fact["source_ids"] = args[5]
            fact["status"] = args[6]
            fact["expires_at"] = args[7]
            return "UPDATE 1"
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

    async def fetchone(self, query: str, *args):
        if "FROM confirmed_facts" in query and "external_id" in query:
            user_id, provider, calendar_id, external_id = args
            for fact in self.confirmed_facts.values():
                metadata = fact["content"]["metadata"]
                if (
                    fact["user_id"] == user_id
                    and fact["fact_type"] == "event"
                    and metadata.get("source_type") == "calendar"
                    and metadata.get("external_provider") == provider
                    and metadata.get("external_calendar_id") == calendar_id
                    and metadata.get("external_id") == external_id
                ):
                    return fact
        return None


def _candidate(*, sensitivity: str = "high", companion_category: str | None = None, raw_evidence: str = "User might be afraid of abandonment.") -> dict:
    return {
        "id": uuid4(),
        "user_id": "user-1",
        "source_id": uuid4(),
        "candidate_type": "fact",
        "content": {
            "schema_version": "v1",
            "item_type": "fact",
            "title": "user",
            "summary": "Sensitive memory",
            "salience": "high",
            "priority": None,
            "urgency": None,
            "importance": "high",
            "sensitivity": sensitivity,
            "time": {
                "due_date": None,
                "reminder_at": None,
                "date": None,
                "time": None,
                "duration": None,
                "follow_up_after_hours": None,
                "stale_after_hours": None,
                "expires_at": None,
            },
            "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
            "lifecycle": {"follow_up_after_hours": None, "stale_after_hours": None, "expires_at": None},
            "evidence": {"raw_evidence": raw_evidence, "source_turn_refs": []},
            "metadata": {
                "companion_category": companion_category,
                "agent_item": {
                    "fact_type": "constraint" if companion_category in {"avoid_topic", "sensitivity_boundary"} else "background",
                    "content": raw_evidence,
                    "raw_evidence": raw_evidence,
                    "related_people": [],
                    "related_projects": [],
                    "companion_category": companion_category,
                },
            },
        },
        "raw_evidence": raw_evidence,
        "confidence": 0.92,
        "needs_confirmation": False,
        "status": "pending",
        "reconciliation_instruction": None,
        "merge_target_id": None,
        "created_at": datetime(2026, 5, 22, 12, 0),
    }


def _state_like_fact(*, user_id: str = "user-1", last_seen_at: datetime | None = None) -> dict:
    return {
        "id": uuid4(),
        "user_id": user_id,
        "fact_type": "identity",
        "domain": "state",
        "content": {
            "schema_version": "v1",
            "item_type": "state",
            "title": None,
            "summary": "User felt overwhelmed.",
            "salience": "medium",
            "priority": None,
            "urgency": None,
            "importance": "medium",
            "sensitivity": "medium",
            "time": {"stale_after_hours": 4},
            "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
            "lifecycle": {"expires_at": None, "stale_after_hours": 4, "follow_up_after_hours": None},
            "evidence": {"raw_evidence": "Today has been rough.", "source_turn_refs": []},
            "metadata": {"companion_category": None, "agent_item": {"provisional": True}},
        },
        "confidence": 0.9,
        "first_seen_at": datetime(2026, 5, 20, 8, 0),
        "last_seen_at": last_seen_at or datetime(2026, 5, 20, 8, 0),
        "last_confirmed_at": datetime(2026, 5, 20, 8, 0),
        "source_ids": [uuid4()],
        "status": "active",
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }


def _calendar_payload(*, user_id: str = "user-1", calendar_id: str = "primary", external_id: str = "evt-1") -> dict:
    return {
        "user_id": user_id,
        "source_type": "calendar",
        "external_provider": "google",
        "external_calendar_id": calendar_id,
        "events": [
            {
                "external_id": external_id,
                "title": "Product review",
                "description": None,
                "starts_at": "2026-05-23T10:00:00+01:00",
                "ends_at": "2026-05-23T11:00:00+01:00",
                "timezone": "Europe/London",
                "all_day": False,
                "location": None,
                "participants": [],
                "organizer": None,
                "status": "confirmed",
                "external_updated_at": "2026-05-22T09:00:00+01:00",
                "etag": None,
                "raw": {"id": external_id},
            }
        ],
    }


def test_missing_database_url_fails_clearly(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr("core.config._load_dotenv", lambda _path: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir("/Users/mukeshkumar/play/synapse-v3")

    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        get_settings()

    get_settings.cache_clear()


async def test_high_sensitivity_inferred_memory_is_not_auto_confirmed() -> None:
    candidate = _candidate()

    assert reconciliation.should_auto_confirm(
        candidate,
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    ) is False


async def test_explicit_high_sensitivity_boundary_can_auto_confirm() -> None:
    candidate = _candidate(
        companion_category="avoid_topic",
        raw_evidence="Please don't bring up the fertility stuff unless I mention it first.",
    )

    assert reconciliation.should_auto_confirm(
        candidate,
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    ) is True


async def test_instruction_packet_suppresses_stale_state_like_facts(monkeypatch) -> None:
    db = FakeServingDatabase()
    db.confirmed_facts.append(_state_like_fact())
    captured: dict[str, list[dict]] = {}

    def fake_run(**kwargs):
        captured["confirmed_facts"] = kwargs["confirmed_facts"]
        return {
            "session_instructions": "Brief",
            "relevant_topics": [],
            "worth_attention": [],
            "suggested_focus": "Current conversation",
            "tone_note": "Calm.",
            "avoid": [],
            "stale_warnings": [],
        }

    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_run)

    await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T12:00:00+00:00",
        timezone_name="Europe/London",
    )

    assert captured["confirmed_facts"] == []


def test_runtime_does_not_trigger_recall_for_remember_to_task() -> None:
    runtime = SophieRuntime(cortex_client=CortexClient(request_fn=lambda *args, **kwargs: {}))

    assert runtime.should_trigger_recall("Remember to call Ashley tomorrow.") is False
    assert runtime.should_trigger_recall("Do you remember Ashley?") is True


async def test_pipeline_failure_marks_outbox_failed_and_preserves_raw_content(monkeypatch) -> None:
    db = FakePipelineDatabase()
    created = await pipeline_runner.create_session_outbox(
        db,
        user_id="user-1",
        session_id="session-1",
        messages=[{"role": "user", "content": "I need to call Ashley.", "timestamp": "2026-05-22T10:00:00Z"}],
        source_type="chat",
        metadata={"timezone": "Europe/London"},
    )
    outbox_id = created["outbox_id"]

    def fake_summary(_agent_input):
        raise RuntimeError("summary failed")

    monkeypatch.setattr("core.pipeline_runner.session_summary_agent.run", fake_summary)

    with pytest.raises(RuntimeError, match="summary failed"):
        await pipeline_runner.run_pipeline_for_outbox(db, outbox_id=outbox_id)

    assert db.outbox_rows[outbox_id]["status"] == "failed"
    assert "User: I need to call Ashley." in db.outbox_rows[outbox_id]["raw_content"]


async def test_recall_is_user_isolated_across_facts_summaries_and_timeline() -> None:
    db = FakeRecallDatabase()
    db.confirmed_facts.extend(
        [
            {
                "id": uuid4(),
                "user_id": "user-1",
                "fact_type": "relationship",
                "domain": "people",
                "content": {"summary": "Ashley is stressed.", "title": "Ashley", "metadata": {}, "links": {"people": ["Ashley"]}},
                "confidence": 0.95,
                "status": "active",
                "last_seen_at": datetime(2026, 5, 22, 12, 0),
                "first_seen_at": datetime(2026, 5, 22, 12, 0),
            },
            {
                "id": uuid4(),
                "user_id": "user-2",
                "fact_type": "relationship",
                "domain": "people",
                "content": {"summary": "Ashley is moving.", "title": "Ashley", "metadata": {}, "links": {"people": ["Ashley"]}},
                "confidence": 0.95,
                "status": "active",
                "last_seen_at": datetime(2026, 5, 22, 12, 0),
                "first_seen_at": datetime(2026, 5, 22, 12, 0),
            },
        ]
    )
    db.session_summaries.extend(
        [
            {"id": uuid4(), "user_id": "user-1", "summary": "Ashley and the user talked.", "tags": ["personal"], "open_items": [], "key_decisions": [], "occurred_at": datetime(2026, 5, 22, 10, 0)},
            {"id": uuid4(), "user_id": "user-2", "summary": "Ashley project status.", "tags": ["work"], "open_items": [], "key_decisions": [], "occurred_at": datetime(2026, 5, 22, 10, 0)},
        ]
    )
    db.timeline_events.extend(
        [
            {"id": uuid4(), "user_id": "user-1", "event_type": "relationship_update", "title": "Ashley update", "summary": "Ashley is stressed", "occurred_at": datetime(2026, 5, 22, 10, 0), "observed_at": datetime(2026, 5, 22, 10, 0)},
            {"id": uuid4(), "user_id": "user-2", "event_type": "relationship_update", "title": "Ashley move", "summary": "Ashley is moving", "occurred_at": datetime(2026, 5, 22, 10, 0), "observed_at": datetime(2026, 5, 22, 10, 0)},
        ]
    )

    result = await recall_service.recall(db, user_id="user-1", query="Ashley", limit=5)

    assert all(item["summary"] != "Ashley is moving." for item in result["facts"])
    assert all(item["summary"] != "Ashley project status." for item in result["summaries"])
    assert all(item["title"] != "Ashley move" for item in result["timeline"])


async def test_calendar_import_keeps_same_external_id_isolated_by_user_and_calendar() -> None:
    db = FakeCalendarDatabase()

    await calendar_import.import_calendar_events(db, payload=_calendar_payload(user_id="user-1", calendar_id="primary"), now=datetime(2026, 5, 22, 12, 0))
    await calendar_import.import_calendar_events(db, payload=_calendar_payload(user_id="user-2", calendar_id="primary"), now=datetime(2026, 5, 22, 12, 0))
    await calendar_import.import_calendar_events(db, payload=_calendar_payload(user_id="user-1", calendar_id="work"), now=datetime(2026, 5, 22, 12, 0))

    assert len(db.confirmed_facts) == 3
    tuples = {
        (
            fact["user_id"],
            fact["content"]["metadata"]["external_calendar_id"],
            fact["content"]["metadata"]["external_id"],
        )
        for fact in db.confirmed_facts.values()
    }
    assert ("user-1", "primary", "evt-1") in tuples
    assert ("user-2", "primary", "evt-1") in tuples
    assert ("user-1", "work", "evt-1") in tuples
