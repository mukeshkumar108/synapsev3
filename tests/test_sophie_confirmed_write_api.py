from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

from core.api import app, get_database


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []

    async def execute(self, query: str, *args):
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
        if "UPDATE confirmed_facts" in query:
            row = self.confirmed_facts[args[0]]
            row["content"] = args[1]
            row["structured_content"] = args[2]
            row["confidence"] = args[3]
            row["last_seen_at"] = args[4]
            row["last_confirmed_at"] = args[5]
            row["source_ids"] = args[6]
            row["status"] = args[7]
            row["user_corrected"] = args[8]
            row["correction_note"] = args[9]
            row["expires_at"] = args[10]
            row["source_type"] = args[11]
            row["primary_source_id"] = args[12]
            row["who_said_it"] = args[13]
            row["original_text"] = args[14]
            row["channel"] = args[15]
            row["conversation_id"] = args[16]
            row["created_from"] = args[17]
            row["provenance"] = args[18]
            row["starts_at"] = args[19]
            row["ends_at"] = args[20]
            row["due_at"] = args[21]
            row["remind_at"] = args[22]
            row["timezone"] = args[23]
            row["recurrence_rule"] = args[24]
            row["completed_at"] = args[25]
            row["cancelled_at"] = args[26]
            row["priority"] = args[27]
            row["follow_up_needed"] = args[28]
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

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            user_id = args[0]
            rows = [row for row in self.confirmed_facts.values() if row["user_id"] == user_id]
            if "created_from->>'writer'" in query:
                idempotency_key = args[1]
                return [
                    row
                    for row in rows
                    if (row.get("created_from") or {}).get("writer") == "sophie_confirmed_action"
                    and (row.get("created_from") or {}).get("idempotency_key") == idempotency_key
                ][:1]
            return rows
        return []

    async def fetchone(self, query: str, *args):
        if "FROM confirmed_facts" in query and "created_from->>'writer'" in query:
            rows = await self.fetch(query, *args)
            return rows[0] if rows else None
        if "FROM confirmed_facts" in query:
            row = self.confirmed_facts.get(args[0])
            if row and row["user_id"] == args[1]:
                return row
        return None

    async def close(self):
        return None


def _override_database(db: FakeDatabase):
    async def _dependency():
        yield db

    return _dependency


def test_sophie_confirmed_action_create_and_idempotency() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    payload = {
        "tenantId": "tenant-1",
        "userId": "user-1",
        "kind": "reminder",
        "title": "Call dentist",
        "notes": "Call dentist tomorrow morning",
        "dueAt": None,
        "remindAt": "2026-06-07T09:00:00+01:00",
        "timezone": "Europe/London",
        "sourceType": "sophie_chat",
        "provenanceSummary": "Confirmed by user in Sophie UI",
        "confidence": 0.99,
        "sourceRef": "sophie:turn:123",
        "idempotencyKey": "idem-reminder-1",
    }

    first = client.post("/v3/actions", json=payload)
    second = client.post("/v3/actions", json=payload)
    app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(db.confirmed_facts) == 1
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "reminder"
    assert fact["remind_at"] is not None
    assert fact["source_type"] == "sophie_chat"
    assert fact["created_from"]["writer"] == "sophie_confirmed_action"
    assert db.timeline_events[0]["event_type"] == "reminder_created"
    assert first.json()["kind"] == "reminder"
    assert first.json()["remindAt"] is not None


def test_sophie_confirmed_event_create_and_cancel() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    create_payload = {
        "tenantId": "tenant-1",
        "userId": "user-1",
        "title": "Call with Peter",
        "notes": "Product review",
        "startsAt": "2026-06-11T14:00:00+01:00",
        "endsAt": "2026-06-11T15:00:00+01:00",
        "timezone": "Europe/London",
        "location": "Zoom",
        "participants": ["Peter"],
        "sourceType": "sophie_chat",
        "provenanceSummary": "Confirmed event from Sophie UI",
        "confidence": 0.97,
        "sourceRef": "sophie:event:456",
        "idempotencyKey": "idem-event-1",
    }
    create_response = client.post("/v3/events", json=create_payload)
    event_id = create_response.json()["id"]
    cancel_response = client.post(
        f"/v3/events/{event_id}/cancel",
        json={"userId": "user-1", "idempotencyKey": "idem-event-cancel-1", "sourceType": "sophie_chat"},
    )
    app.dependency_overrides.clear()

    assert create_response.status_code == 200
    assert cancel_response.status_code == 200
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "event"
    assert fact["starts_at"] is not None
    assert fact["ends_at"] is not None
    assert fact["status"] == "dismissed"
    assert [event["event_type"] for event in db.timeline_events] == ["event_created", "event_cancelled"]


def test_sophie_confirmed_task_patch_complete_and_delete() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    create_payload = {
        "tenantId": "tenant-1",
        "userId": "user-1",
        "kind": "todo",
        "title": "Send proposal",
        "notes": "Send Ashley the proposal tonight",
        "dueAt": "2026-06-06T20:00:00+01:00",
        "timezone": "Europe/London",
        "sourceType": "sophie_chat",
        "provenanceSummary": "Confirmed task from Sophie UI",
        "confidence": 0.98,
        "sourceRef": "sophie:task:789",
        "idempotencyKey": "idem-task-1",
    }
    create_response = client.post("/v3/actions", json=create_payload)
    task_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/v3/actions/{task_id}",
        json={
            "userId": "user-1",
            "title": "Send Ashley the proposal",
            "notes": "Sent it",
            "sourceType": "sophie_chat",
            "idempotencyKey": "idem-task-complete-1",
            "status": "completed",
        },
    )

    delete_response = client.request(
        "DELETE",
        f"/v3/actions/{task_id}",
        json={"userId": "user-1", "idempotencyKey": "idem-task-delete-1"},
    )
    app.dependency_overrides.clear()

    assert create_response.status_code == 200
    assert patch_response.status_code == 200
    assert delete_response.status_code == 200
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "task"
    assert fact["due_at"] is not None
    assert fact["created_from"]["writer"] == "sophie_confirmed_action"
    assert "provenance_summary" in fact["created_from"]
    assert [event["event_type"] for event in db.timeline_events] == ["task_created", "task_completed", "task_archived"]
