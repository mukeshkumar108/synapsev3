from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from core.api import app, get_database


class FakeDatabase:
    def __init__(self) -> None:
        self.outbox_rows: dict[UUID, dict] = {}
        self.source_archive_rows: dict[UUID, dict] = {}
        self.confirmed_facts: dict[UUID, dict] = {}
        self.candidates: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []
        self.session_summaries: list[dict] = []

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            user_id = args[0]
            rows = [row for row in self.confirmed_facts.values() if row["user_id"] == user_id]
            if "fact_type = ANY" in query:
                rows = [row for row in rows if row["fact_type"] in set(args[1])]
            if "status = 'active'" in query:
                rows = [row for row in rows if row["status"] == "active"]
            return rows
        if "FROM candidates" in query:
            user_id = args[0]
            rows = [row for row in self.candidates.values() if row["user_id"] == user_id]
            if "candidate_type = ANY" in query:
                rows = [row for row in rows if row["candidate_type"] in set(args[1])]
            if "status = 'pending'" in query:
                rows = [row for row in rows if row["status"] == "pending"]
            return rows
        if "FROM timeline_events" in query:
            user_id = args[0]
            if len(args) > 1:
                return [row for row in self.timeline_events if row["user_id"] == user_id][: args[1]]
            return [row for row in self.timeline_events if row["user_id"] == user_id]
        if "FROM session_summaries" in query:
            user_id = args[0]
            rows = [row for row in self.session_summaries if row["user_id"] == user_id]
            rows.sort(key=lambda row: row["occurred_at"], reverse=True)
            if len(args) > 1:
                return rows[: args[1]]
            return rows
        if "FROM outbox" in query:
            user_id = args[0]
            rows = [row for row in self.outbox_rows.values() if row["user_id"] == user_id]
            rows.sort(key=lambda row: row["received_at"], reverse=True)
            return rows
        if "FROM source_archive" in query:
            return [row for row in self.source_archive_rows.values() if row["user_id"] == args[0]]
        return []

    async def fetchone(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            row = self.confirmed_facts.get(args[0])
            if row and row["user_id"] == args[1]:
                return row
        if "FROM candidates" in query:
            row = self.candidates.get(args[0])
            if row and row["user_id"] == args[1]:
                return row
        return None

    async def close(self):
        return None


def _override_database(db: FakeDatabase):
    async def _dependency():
        yield db

    return _dependency


def _client(db: FakeDatabase) -> TestClient:
    app.dependency_overrides[get_database] = _override_database(db)
    return TestClient(app)


def _packet_stub(**kwargs):
    return {
        "session_instructions": "Use packet privately.",
        "relevant_topics": [],
        "worth_attention": [],
        "suggested_focus": "Current conversation",
        "tone_note": "Grounded.",
        "avoid": [],
        "stale_warnings": [],
    }


def test_create_list_complete_and_dismiss_action(monkeypatch) -> None:
    db = FakeDatabase()
    client = _client(db)

    create = client.post(
        "/v3/actions",
        json={
            "user_id": "user-1",
            "title": "Call Ashley",
            "summary": "Call Ashley tomorrow.",
            "due_at": "2026-05-23T09:00:00Z",
            "priority": "high",
            "links": {"people": ["Ashley"], "projects": ["check-in"]},
            "source": "sophie_runtime",
            "requires_confirmation": False,
        },
    )
    assert create.status_code == 200
    created = create.json()
    assert created["status"] == "active"
    assert created["links"]["people"] == ["Ashley"]

    listed = client.get("/v3/actions", params={"user_id": "user-1", "status": "active"})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["title"] == "Call Ashley"

    completed = client.patch(
        f"/v3/actions/{created['id']}",
        json={"user_id": "user-1", "status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    second = client.post(
        "/v3/actions",
        json={
            "user_id": "user-1",
            "title": "Send update",
            "summary": "Send project update.",
            "due_at": None,
            "priority": "medium",
            "links": {"projects": ["Atlas"]},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    )
    second_id = second.json()["id"]
    dismissed = client.patch(
        f"/v3/actions/{second_id}",
        json={"user_id": "user-1", "status": "dismissed"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert len(db.timeline_events) >= 4
    app.dependency_overrides.clear()


def test_user_isolation_for_action_list_and_update() -> None:
    db = FakeDatabase()
    client = _client(db)
    response = client.post(
        "/v3/actions",
        json={
            "user_id": "user-1",
            "title": "Private action",
            "summary": "Do not leak.",
            "due_at": None,
            "priority": "low",
            "links": {},
            "source": "sophie_runtime",
            "requires_confirmation": False,
        },
    )
    item_id = response.json()["id"]

    other_list = client.get("/v3/actions", params={"user_id": "user-2"})
    assert other_list.status_code == 200
    assert other_list.json()["items"] == []

    other_patch = client.patch(
        f"/v3/actions/{item_id}",
        json={"user_id": "user-2", "status": "dismissed"},
    )
    assert other_patch.status_code == 404
    app.dependency_overrides.clear()


def test_create_and_update_event_candidate_without_external_sync() -> None:
    db = FakeDatabase()
    client = _client(db)

    create = client.post(
        "/v3/events",
        json={
            "user_id": "user-1",
            "title": "Dentist appointment",
            "summary": "Dentist on Friday.",
            "due_at": "2026-05-24T14:00:00Z",
            "priority": "medium",
            "links": {"projects": ["health"]},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    )
    assert create.status_code == 200
    event = create.json()
    assert event["record_kind"] == "candidate"
    assert event["not_synced_external"] is True
    assert event["requires_confirmation"] is True

    confirmed = client.patch(
        f"/v3/events/{event['id']}",
        json={"user_id": "user-1", "status": "confirmed"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["record_kind"] == "confirmed_fact"
    assert confirmed.json()["not_synced_external"] is True

    second = client.post(
        "/v3/events",
        json={
            "user_id": "user-1",
            "title": "Maybe lunch",
            "summary": "Possible lunch plan.",
            "due_at": "2026-05-25T12:00:00Z",
            "priority": "low",
            "links": {"people": ["Nina"]},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    )
    dismissed = client.patch(
        f"/v3/events/{second.json()['id']}",
        json={"user_id": "user-1", "status": "dismissed"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    app.dependency_overrides.clear()


def test_get_events_returns_items_for_correct_user_and_empty_when_none_exist() -> None:
    db = FakeDatabase()
    client = _client(db)

    empty = client.get("/v3/events", params={"user_id": "user-1"})
    assert empty.status_code == 200
    assert empty.json()["items"] == []

    created = client.post(
        "/v3/events",
        json={
            "user_id": "user-1",
            "title": "Dentist appointment",
            "summary": "Dentist on Friday.",
            "due_at": "2026-05-24T14:00:00Z",
            "priority": "medium",
            "links": {"projects": ["health"]},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    )
    assert created.status_code == 200

    listed = client.get("/v3/events", params={"user_id": "user-1"})
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["title"] == "Dentist appointment"
    app.dependency_overrides.clear()


def test_get_events_respects_status_filter() -> None:
    db = FakeDatabase()
    client = _client(db)

    pending = client.post(
        "/v3/events",
        json={
            "user_id": "user-1",
            "title": "Pending event",
            "summary": "Needs confirmation.",
            "due_at": "2026-05-24T14:00:00Z",
            "priority": "medium",
            "links": {},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    ).json()
    confirmed = client.post(
        "/v3/events",
        json={
            "user_id": "user-1",
            "title": "Confirm me",
            "summary": "Should become a fact.",
            "due_at": "2026-05-25T09:00:00Z",
            "priority": "high",
            "links": {},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    ).json()
    client.patch(
        f"/v3/events/{confirmed['id']}",
        json={"user_id": "user-1", "status": "confirmed"},
    )
    dismissed = client.post(
        "/v3/events",
        json={
            "user_id": "user-1",
            "title": "Dismiss me",
            "summary": "Should be dismissed.",
            "due_at": "2026-05-26T09:00:00Z",
            "priority": "low",
            "links": {},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    ).json()
    client.patch(
        f"/v3/events/{dismissed['id']}",
        json={"user_id": "user-1", "status": "dismissed"},
    )

    active = client.get("/v3/events", params={"user_id": "user-1", "status": "active"})
    confirmed_only = client.get("/v3/events", params={"user_id": "user-1", "status": "confirmed"})
    dismissed_only = client.get("/v3/events", params={"user_id": "user-1", "status": "dismissed"})

    assert active.status_code == 200
    assert confirmed_only.status_code == 200
    assert dismissed_only.status_code == 200
    assert any(item["title"] == "Pending event" for item in active.json()["items"])
    assert all(item["record_kind"] == "confirmed_fact" for item in confirmed_only.json()["items"])
    assert any(item["title"] == "Confirm me" for item in confirmed_only.json()["items"])
    assert any(item["title"] == "Dismiss me" for item in dismissed_only.json()["items"])
    app.dependency_overrides.clear()


def test_get_events_respects_user_isolation() -> None:
    db = FakeDatabase()
    client = _client(db)

    client.post(
        "/v3/events",
        json={
            "user_id": "user-1",
            "title": "User one event",
            "summary": "Visible only to user one.",
            "due_at": "2026-05-24T14:00:00Z",
            "priority": "medium",
            "links": {},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    )
    client.post(
        "/v3/events",
        json={
            "user_id": "user-2",
            "title": "User two event",
            "summary": "Visible only to user two.",
            "due_at": "2026-05-24T15:00:00Z",
            "priority": "medium",
            "links": {},
            "source": "sophie_runtime",
            "requires_confirmation": True,
        },
    )

    user_one = client.get("/v3/events", params={"user_id": "user-1"})
    user_two = client.get("/v3/events", params={"user_id": "user-2"})

    assert user_one.status_code == 200
    assert user_two.status_code == 200
    assert [item["title"] for item in user_one.json()["items"]] == ["User one event"]
    assert [item["title"] for item in user_two.json()["items"]] == ["User two event"]
    app.dependency_overrides.clear()


def test_memory_controls_affect_startup_and_preserve_source_archive(monkeypatch) -> None:
    db = FakeDatabase()
    db.source_archive_rows[uuid4()] = {
        "id": uuid4(),
        "user_id": "user-1",
        "source_type": "sophie_session",
        "payload": {"raw_content": "original"},
        "metadata": {},
        "captured_at": datetime(2026, 5, 22, 12, 0),
        "created_at": datetime(2026, 5, 22, 12, 0),
        "source_external_id": None,
        "session_id": None,
        "conversation_id": None,
        "occurred_at": None,
    }
    client = _client(db)
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    action = client.post(
        "/v3/actions",
        json={
            "user_id": "user-1",
            "title": "Wait on Jordan",
            "summary": "Waiting on Jordan to respond.",
            "due_at": None,
            "priority": "high",
            "links": {"people": ["Jordan"], "projects": ["contract"]},
            "source": "sophie_runtime",
            "requires_confirmation": False,
        },
    ).json()

    # Force the action into an open loop thread-like target for resolve_loop coverage.
    fact = db.confirmed_facts[UUID(action["id"])]
    fact["fact_type"] = "thread"
    fact["content"]["item_type"] = "thread"
    fact["content"]["metadata"]["open_loop_status"] = "active"

    avoid = client.post(
        "/v3/memory-controls",
        json={
            "user_id": "user-1",
            "action": "avoid_topic",
            "target_id": None,
            "target_type": "fact",
            "note": "Avoid fertility topic unless user raises it.",
        },
    )
    assert avoid.status_code == 200

    packet = client.get("/v3/sessions/instruction-packet", params={"user_id": "user-1"})
    assert packet.status_code == 200
    body = packet.json()
    assert any("fertility" in item.lower() for item in body["avoid"])
    assert all(hint["name"] != "Avoid fertility topic unless user raises it." for hint in body["entity_hints"])

    resolved = client.post(
        "/v3/memory-controls",
        json={
            "user_id": "user-1",
            "action": "resolve_loop",
            "target_id": action["id"],
            "target_type": "thread",
            "note": "Jordan responded.",
        },
    )
    assert resolved.status_code == 200
    packet_after = client.get("/v3/sessions/instruction-packet", params={"user_id": "user-1"})
    assert all(loop["title"] != "Wait on Jordan" for loop in packet_after.json()["active_open_loops"])

    dismissed = client.post(
        "/v3/memory-controls",
        json={
            "user_id": "user-1",
            "action": "forget",
            "target_id": action["id"],
            "target_type": "action",
            "note": "Forget this.",
        },
    )
    assert dismissed.status_code == 200
    assert len(db.source_archive_rows) == 1
    assert len(db.timeline_events) >= 4
    app.dependency_overrides.clear()
