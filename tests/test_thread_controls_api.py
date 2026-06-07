from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from core.api import app, get_database


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []
        self.fact_links: dict[UUID, dict] = {}
        self.source_archive_rows: dict[UUID, dict] = {}
        self.outbox_rows: dict[UUID, dict] = {}

    async def execute(self, query: str, *args):
        return "OK"

    async def fetch(self, query: str, *args):
        return []

    async def fetchone(self, query: str, *args):
        return None

    async def close(self):
        return None


def _override_database(db: FakeDatabase):
    async def _dependency():
        yield db

    return _dependency


def _seed_thread(
    db: FakeDatabase,
    *,
    title: str = "Waiting on Jordan contract",
    summary: str = "Still waiting on Jordan to send the contract.",
    source_id: UUID | None = None,
) -> UUID:
    thread_id = uuid4()
    source_uuid = source_id or uuid4()
    now = datetime(2026, 6, 7, 9, 0)
    db.confirmed_facts[thread_id] = {
        "id": thread_id,
        "user_id": "user-1",
        "fact_type": "thread",
        "domain": "workstreams",
        "content": {
            "schema_version": "v1",
            "item_type": "thread",
            "title": title,
            "summary": summary,
            "priority": "high",
            "links": {"people": ["Jordan"], "projects": ["contract"], "topics": [], "related_facts": [], "related_threads": []},
            "evidence": {"raw_evidence": summary, "source_turn_refs": []},
            "metadata": {
                "item_status": "active",
                "open_loop_status": "active",
                "thread_type": "followup_thread",
                "actionability": "externally_blocked",
                "next_move": "follow_up",
                "waiting_on": "Jordan",
                "surface_reason": "Jordan has not replied yet.",
                "resolution_condition": "Jordan sends the contract.",
                "thread_evidence": {"repeated_mentions": 2},
            },
        },
        "structured_content": {
            "kind": "thread",
            "title": title,
            "summary": summary,
            "status": "active",
            "priority": "high",
            "temporal": {
                "starts_at": None,
                "ends_at": None,
                "due_at": None,
                "remind_at": None,
                "timezone": None,
                "recurrence_rule": None,
            },
            "thread": {
                "follow_up_needed": True,
                "thread_type": "followup_thread",
                "actionability": "externally_blocked",
                "next_move": "follow_up",
                "waiting_on": "Jordan",
                "open_loop_status": "active",
                "suggested_actions": [],
                "blocked_by": "Jordan",
                "resolution_condition": "Jordan sends the contract.",
                "resolution_summary": None,
                "surface_reason": "Jordan has not replied yet.",
                "evidence": {"repeated_mentions": 2},
                "capability_assessment": {"requested_action": "follow_up", "capability_status": "supported"},
                "last_progressed_at": None,
                "last_resurfaced_at": None,
                "snoozed_until": None,
            },
            "links": {"people": ["Jordan"], "projects": ["contract"], "topics": [], "related_facts": [], "related_threads": []},
            "provenance": {"source_id": str(source_uuid), "source_ids": [str(source_uuid)], "source_type": "sophie_chat", "who_said_it": "user", "original_text": summary, "channel": "sophie_chat", "conversation_id": "thread-1", "created_from": {"pipeline": "test"}},
        },
        "confidence": 0.92,
        "first_seen_at": now,
        "last_seen_at": now,
        "last_confirmed_at": now,
        "source_ids": [source_uuid],
        "source_type": "sophie_chat",
        "primary_source_id": source_uuid,
        "who_said_it": "user",
        "original_text": summary,
        "channel": "sophie_chat",
        "conversation_id": "thread-1",
        "created_from": {"pipeline": "test"},
        "provenance": {"source_id": str(source_uuid), "source_ids": [str(source_uuid)], "source_type": "sophie_chat", "who_said_it": "user", "original_text": summary, "channel": "sophie_chat", "conversation_id": "thread-1", "created_from": {"pipeline": "test"}},
        "status": "active",
        "starts_at": None,
        "ends_at": None,
        "due_at": None,
        "remind_at": None,
        "timezone": None,
        "recurrence_rule": None,
        "completed_at": None,
        "cancelled_at": None,
        "priority": "high",
        "follow_up_needed": True,
        "thread_type": "followup_thread",
        "actionability": "externally_blocked",
        "next_move": "follow_up",
        "last_progressed_at": None,
        "last_resurfaced_at": None,
        "snoozed_until": None,
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }
    return thread_id


def test_dismissed_thread_no_longer_surfaces() -> None:
    db = FakeDatabase()
    thread_id = _seed_thread(db)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    before = client.get("/v3/ops/threads/open", params={"user_id": "user-1"})
    dismiss = client.post(
        f"/v3/threads/{thread_id}/dismiss",
        json={"userId": "user-1", "createdFrom": "thread_surfacing", "idempotencyKey": "thread-dismiss-1"},
    )
    after = client.get("/v3/ops/threads/open", params={"user_id": "user-1"})
    app.dependency_overrides.clear()

    assert before.status_code == 200
    assert len(before.json()["items"]) == 1
    assert dismiss.status_code == 200
    assert after.json()["items"] == []
    assert db.timeline_events[-1]["event_type"] == "thread_dismissed"


def test_snoozed_thread_hides_until_expiry() -> None:
    db = FakeDatabase()
    thread_id = _seed_thread(db)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    snooze = client.post(
        f"/v3/threads/{thread_id}/snooze",
        json={
            "userId": "user-1",
            "createdFrom": "thread_surfacing",
            "idempotencyKey": "thread-snooze-1",
            "snoozedUntil": "2099-06-07T10:00:00+00:00",
        },
    )
    hidden = client.get("/v3/ops/threads/open", params={"user_id": "user-1"})
    db.confirmed_facts[thread_id]["snoozed_until"] = datetime(2000, 1, 1, 0, 0)
    db.confirmed_facts[thread_id]["content"]["metadata"]["snoozed_until"] = "2000-01-01T00:00:00+00:00"
    visible = client.get("/v3/ops/threads/open", params={"user_id": "user-1"})
    app.dependency_overrides.clear()

    assert snooze.status_code == 200
    assert hidden.json()["items"] == []
    assert len(visible.json()["items"]) == 1
    assert db.timeline_events[-1]["event_type"] == "thread_snoozed"


def test_thread_snooze_mutation_is_idempotent_and_updates_operational_columns() -> None:
    db = FakeDatabase()
    thread_id = _seed_thread(db)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    payload = {
        "userId": "user-1",
        "createdFrom": "thread_surfacing",
        "idempotencyKey": "thread-snooze-sync-1",
        "snoozedUntil": "2099-06-07T10:00:00+00:00",
    }

    first = client.post(f"/v3/threads/{thread_id}/snooze", json=payload)
    second = client.post(f"/v3/threads/{thread_id}/snooze", json=payload)
    app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    thread = db.confirmed_facts[thread_id]
    assert thread["snoozed_until"] is not None
    assert thread["last_resurfaced_at"] is not None
    assert thread["follow_up_needed"] is True
    assert thread["content"]["metadata"]["open_loop_status"] == "active"
    assert len(db.timeline_events) == 1
    assert db.timeline_events[0]["event_type"] == "thread_snoozed"


def test_convert_thread_to_task_creates_linked_task() -> None:
    db = FakeDatabase()
    thread_id = _seed_thread(db)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    response = client.post(
        f"/v3/threads/{thread_id}/convert-to-task",
        json={
            "userId": "user-1",
            "createdFrom": "thread_surfacing",
            "idempotencyKey": "thread-task-1",
            "title": "Email Jordan for the contract",
            "notes": "Prompt Jordan for the contract",
            "dueAt": "2026-06-08T12:00:00+01:00",
            "timezone": "Europe/London",
        },
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["item"]["kind"] == "task"
    assert len(db.confirmed_facts) == 2
    assert len(db.fact_links) == 1
    link = next(iter(db.fact_links.values()))
    assert link["from_fact_id"] == thread_id
    linked_fact = db.confirmed_facts[link["to_fact_id"]]
    assert linked_fact["fact_type"] == "task"
    assert [event["event_type"] for event in db.timeline_events] == ["task_created", "thread_progressed"]
    assert db.confirmed_facts[thread_id]["next_move"] == "wait"
    assert db.confirmed_facts[thread_id]["last_progressed_at"] is not None


def test_convert_thread_to_reminder_and_explanation_surfaces_links_and_reasons() -> None:
    db = FakeDatabase()
    source_uuid = uuid4()
    thread_id = _seed_thread(db, source_id=source_uuid)
    linked_fact_id = uuid4()
    db.confirmed_facts[linked_fact_id] = {
        **db.confirmed_facts[thread_id],
        "id": linked_fact_id,
        "fact_type": "task",
        "content": {
            **db.confirmed_facts[thread_id]["content"],
            "item_type": "task",
            "title": "Review contract",
            "summary": "Check the updated contract",
            "metadata": {"item_status": "active"},
        },
        "structured_content": {
            **db.confirmed_facts[thread_id]["structured_content"],
            "kind": "task",
            "thread": None,
        },
        "follow_up_needed": False,
        "thread_type": None,
        "actionability": None,
        "next_move": None,
    }
    event_id = uuid4()
    db.timeline_events.append(
        {
            "id": event_id,
            "user_id": "user-1",
            "event_type": "event_created",
            "timeline_type": "calendar",
            "title": "Contract call",
            "summary": "Scheduled call",
            "occurred_at": datetime(2026, 6, 7, 10, 0),
            "observed_at": datetime(2026, 6, 7, 10, 0),
            "source_id": source_uuid,
            "related_fact_ids": [thread_id],
            "status": "current",
            "confidence": 0.9,
        }
    )
    archive_id = uuid4()
    db.source_archive_rows[archive_id] = {"id": archive_id, "user_id": "user-1", "source_type": "whatsapp", "source_external_id": "wa-1"}
    outbox_id = uuid4()
    db.outbox_rows[outbox_id] = {"id": outbox_id, "user_id": "user-1", "source_type": "chat", "raw_content": "Still waiting on Jordan"}
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    convert = client.post(
        f"/v3/threads/{thread_id}/convert-to-reminder",
        json={
            "userId": "user-1",
            "createdFrom": "thread_surfacing",
            "idempotencyKey": "thread-reminder-1",
            "title": "Check in with Jordan",
            "notes": "Follow up tomorrow",
            "remindAt": "2026-06-08T09:00:00+01:00",
            "timezone": "Europe/London",
        },
    )
    links = client.patch(
        f"/v3/threads/{thread_id}/links",
        json={
            "userId": "user-1",
            "createdFrom": "thread_surfacing",
            "idempotencyKey": "thread-links-1",
            "linkType": "relates_to",
            "add": {
                "factIds": [str(linked_fact_id)],
                "timelineEventIds": [str(event_id)],
                "sourceArchiveIds": [str(archive_id)],
                "outboxIds": [str(outbox_id)],
            },
            "remove": {},
        },
    )
    explanation = client.get(f"/v3/threads/{thread_id}/explanation", params={"userId": "user-1"})
    app.dependency_overrides.clear()

    assert convert.status_code == 200
    assert links.status_code == 200
    assert explanation.status_code == 200
    payload = explanation.json()
    assert payload["thread_type"] == "followup_thread"
    assert payload["actionability"] == "externally_blocked"
    assert payload["next_move"] == "wait"
    assert payload["source_refs"] == [f"outbox:{source_uuid}"]
    assert any(item["kind"] == "task" for item in payload["linked_facts"])
    assert any(item["eventType"] == "event_created" for item in payload["linked_events"])
    assert len(payload["linked_sources"]) == 2
    assert payload["why_open"] == "Jordan sends the contract."
    assert len(db.fact_links) == 5
    assert [event["event_type"] for event in db.timeline_events][-3:] == [
        "reminder_created",
        "thread_progressed",
        "thread_link_updated",
    ]


def test_resolve_thread_still_works() -> None:
    db = FakeDatabase()
    thread_id = _seed_thread(db)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    resolve = client.patch(f"/v3/threads/{thread_id}/resolve", params={"user_id": "user-1"})
    open_threads = client.get("/v3/ops/threads/open", params={"user_id": "user-1"})
    app.dependency_overrides.clear()

    assert resolve.status_code == 200
    assert resolve.json()["status"] == "completed"
    assert open_threads.json()["items"] == []
    assert db.timeline_events[-1]["event_type"] == "thread_resolved"
