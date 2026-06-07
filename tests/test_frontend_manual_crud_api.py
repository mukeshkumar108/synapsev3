from __future__ import annotations

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
                writer = args[1]
                key = args[2]
                rows = [
                    row for row in rows
                    if (row.get("created_from") or {}).get("writer") == writer
                    and (row.get("created_from") or {}).get("idempotency_key") == key
                ]
                return rows[:1]
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


def test_task_manual_crud_and_idempotency() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    create_payload = {
        "tenantId": "tenant-1",
        "userId": "user-1",
        "title": "Send proposal",
        "notes": "Send Ashley the proposal tonight",
        "dueAt": "2026-06-06T20:00:00+01:00",
        "timezone": "Europe/London",
        "priority": "high",
        "createdFrom": "tasks_tab",
        "idempotencyKey": "task-create-1",
    }
    create_1 = client.post("/v3/tasks", json=create_payload)
    create_2 = client.post("/v3/tasks", json=create_payload)
    task_id = create_1.json()["id"]
    detail = client.get(f"/v3/tasks/{task_id}", params={"userId": "user-1"})
    listing = client.get("/v3/tasks", params={"userId": "user-1"})
    update = client.patch(
        f"/v3/tasks/{task_id}",
        json={
            "userId": "user-1",
            "notes": "Updated note",
            "priority": "medium",
            "createdFrom": "tasks_tab",
            "idempotencyKey": "task-update-1",
        },
    )
    complete = client.post(
        f"/v3/tasks/{task_id}/complete",
        json={"userId": "user-1", "createdFrom": "tasks_tab", "idempotencyKey": "task-complete-1"},
    )
    archive = client.post(
        f"/v3/tasks/{task_id}/archive",
        json={"userId": "user-1", "createdFrom": "tasks_tab", "idempotencyKey": "task-archive-1"},
    )
    delete = client.request(
        "DELETE",
        f"/v3/tasks/{task_id}",
        json={"userId": "user-1", "createdFrom": "tasks_tab", "idempotencyKey": "task-delete-1"},
    )
    app.dependency_overrides.clear()

    assert create_1.status_code == 200
    assert create_2.status_code == 200
    assert len(db.confirmed_facts) == 1
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "task"
    assert fact["source_type"] == "frontend_manual"
    assert fact["who_said_it"] == "user"
    assert fact["created_from"]["screen"] == "tasks_tab"
    assert detail.json()["title"] == "Send proposal"
    assert len(listing.json()["items"]) == 1
    assert update.status_code == 200
    assert complete.status_code == 200
    assert archive.status_code == 200
    assert delete.status_code == 200
    assert [event["event_type"] for event in db.timeline_events] == [
        "task_created",
        "task_updated",
        "task_completed",
        "task_archived",
        "task_archived",
    ]


def test_task_completion_keeps_manual_status_and_columns_in_sync() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    create = client.post(
        "/v3/tasks",
        json={
            "tenantId": "tenant-1",
            "userId": "user-1",
            "title": "Ship spec",
            "notes": "Finalize and send",
            "dueAt": "2026-06-10T20:00:00+01:00",
            "timezone": "Europe/London",
            "priority": "high",
            "createdFrom": "tasks_tab",
            "idempotencyKey": "task-sync-create-1",
        },
    )
    task_id = create.json()["id"]
    complete = client.post(
        f"/v3/tasks/{task_id}/complete",
        json={
            "userId": "user-1",
            "createdFrom": "tasks_tab",
            "idempotencyKey": "task-sync-complete-1",
            "completedAt": "2026-06-10T21:15:00+01:00",
        },
    )
    app.dependency_overrides.clear()

    assert complete.status_code == 200
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["status"] == "historical"
    assert fact["content"]["metadata"]["item_status"] == "completed"
    assert fact["completed_at"] is not None
    assert fact["due_at"] is not None
    assert fact["priority"] == "high"
    assert fact["created_from"]["last_mutation_idempotency_key"] == "task-sync-complete-1"


def test_reminder_manual_crud() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    create = client.post(
        "/v3/reminders",
        json={
            "tenantId": "tenant-1",
            "userId": "user-1",
            "title": "Call dentist",
            "notes": "Tomorrow morning",
            "remindAt": "2026-06-07T09:00:00+01:00",
            "timezone": "Europe/London",
            "createdFrom": "reminders_tab",
            "idempotencyKey": "reminder-create-1",
        },
    )
    reminder_id = create.json()["id"]
    detail = client.get(f"/v3/reminders/{reminder_id}", params={"userId": "user-1"})
    listing = client.get("/v3/reminders", params={"userId": "user-1"})
    update = client.patch(
        f"/v3/reminders/{reminder_id}",
        json={
            "userId": "user-1",
            "notes": "Updated reminder note",
            "createdFrom": "reminders_tab",
            "idempotencyKey": "reminder-update-1",
        },
    )
    dismiss = client.post(
        f"/v3/reminders/{reminder_id}/dismiss",
        json={"userId": "user-1", "createdFrom": "reminders_tab", "idempotencyKey": "reminder-dismiss-1"},
    )
    archive = client.post(
        f"/v3/reminders/{reminder_id}/archive",
        json={"userId": "user-1", "createdFrom": "reminders_tab", "idempotencyKey": "reminder-archive-1"},
    )
    delete = client.request(
        "DELETE",
        f"/v3/reminders/{reminder_id}",
        json={"userId": "user-1", "createdFrom": "reminders_tab", "idempotencyKey": "reminder-delete-1"},
    )
    app.dependency_overrides.clear()

    assert create.status_code == 200
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "reminder"
    assert fact["remind_at"] is not None
    assert fact["created_from"]["screen"] == "reminders_tab"
    assert detail.json()["kind"] == "reminder"
    assert len(listing.json()["items"]) == 1
    assert update.status_code == 200
    assert dismiss.status_code == 200
    assert archive.status_code == 200
    assert delete.status_code == 200
    assert [event["event_type"] for event in db.timeline_events] == [
        "reminder_created",
        "reminder_updated",
        "reminder_dismissed",
        "reminder_archived",
        "reminder_archived",
    ]


def test_reminder_dismissal_keeps_manual_status_and_columns_in_sync() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    create = client.post(
        "/v3/reminders",
        json={
            "tenantId": "tenant-1",
            "userId": "user-1",
            "title": "Pay rent",
            "notes": "Morning reminder",
            "remindAt": "2026-06-08T09:00:00+01:00",
            "timezone": "Europe/London",
            "priority": "medium",
            "createdFrom": "reminders_tab",
            "idempotencyKey": "reminder-sync-create-1",
        },
    )
    reminder_id = create.json()["id"]
    dismiss = client.post(
        f"/v3/reminders/{reminder_id}/dismiss",
        json={
            "userId": "user-1",
            "createdFrom": "reminders_tab",
            "idempotencyKey": "reminder-sync-dismiss-1",
        },
    )
    app.dependency_overrides.clear()

    assert dismiss.status_code == 200
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["status"] == "dismissed"
    assert fact["content"]["metadata"]["item_status"] == "dismissed"
    assert fact["cancelled_at"] is not None
    assert fact["remind_at"] is not None
    assert fact["priority"] == "medium"
    assert fact["created_from"]["last_mutation_idempotency_key"] == "reminder-sync-dismiss-1"


def test_event_detail_delete_and_habit_manual_crud() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    event_create = client.post(
        "/v3/events",
        json={
            "tenantId": "tenant-1",
            "userId": "user-1",
            "title": "Call with Peter",
            "notes": "Review",
            "startsAt": "2026-06-11T14:00:00+01:00",
            "endsAt": "2026-06-11T15:00:00+01:00",
            "timezone": "Europe/London",
            "sourceType": "sophie_chat",
            "sourceRef": "event:1",
            "idempotencyKey": "event-create-1",
        },
    )
    event_id = event_create.json()["id"]
    event_detail = client.get(f"/v3/events/{event_id}", params={"userId": "user-1"})
    event_delete = client.request(
        "DELETE",
        f"/v3/events/{event_id}",
        json={"userId": "user-1", "createdFrom": "onboarding", "idempotencyKey": "event-delete-1"},
    )

    habit_create = client.post(
        "/v3/habits",
        json={
            "tenantId": "tenant-1",
            "userId": "user-1",
            "title": "10k steps",
            "notes": "Walk daily",
            "timezone": "Europe/London",
            "cadence": "daily",
            "createdFrom": "onboarding",
            "idempotencyKey": "habit-create-1",
        },
    )
    habit_id = habit_create.json()["id"]
    habit_list = client.get("/v3/habits", params={"userId": "user-1"})
    habit_detail = client.get(f"/v3/habits/{habit_id}", params={"userId": "user-1"})
    habit_update = client.patch(
        f"/v3/habits/{habit_id}",
        json={"userId": "user-1", "notes": "Updated habit", "cadence": "daily", "createdFrom": "habits_tab", "idempotencyKey": "habit-update-1"},
    )
    habit_complete = client.patch(
        f"/v3/habits/{habit_id}/complete",
        json={"userId": "user-1", "completedAt": "2026-06-06T18:00:00+01:00", "createdFrom": "habits_tab", "idempotencyKey": "habit-complete-1"},
    )
    habit_archive = client.post(
        f"/v3/habits/{habit_id}/archive",
        json={"userId": "user-1", "createdFrom": "habits_tab", "idempotencyKey": "habit-archive-1"},
    )
    habit_delete = client.request(
        "DELETE",
        f"/v3/habits/{habit_id}",
        json={"userId": "user-1", "createdFrom": "habits_tab", "idempotencyKey": "habit-delete-1"},
    )
    app.dependency_overrides.clear()

    assert event_create.status_code == 200
    assert event_detail.status_code == 200
    assert event_delete.status_code == 200
    assert habit_create.status_code == 200
    assert habit_list.status_code == 200
    assert habit_detail.status_code == 200
    assert habit_update.status_code == 200
    assert habit_complete.status_code == 200
    assert habit_archive.status_code == 200
    assert habit_delete.status_code == 200
    event_types = [event["event_type"] for event in db.timeline_events]
    assert "event_created" in event_types
    assert "event_cancelled" in event_types
    assert "habit_created" in event_types
    assert "habit_updated" in event_types
    assert "habit_completed" in event_types
    assert "habit_archived" in event_types


def test_habit_completion_keeps_cadence_and_completion_columns_in_sync() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)

    create = client.post(
        "/v3/habits",
        json={
            "tenantId": "tenant-1",
            "userId": "user-1",
            "title": "Journal",
            "notes": "Write nightly",
            "timezone": "Europe/London",
            "cadence": "daily",
            "priority": "low",
            "createdFrom": "habits_tab",
            "idempotencyKey": "habit-sync-create-1",
        },
    )
    habit_id = create.json()["id"]
    complete = client.patch(
        f"/v3/habits/{habit_id}/complete",
        json={
            "userId": "user-1",
            "completedAt": "2026-06-06T22:00:00+01:00",
            "createdFrom": "habits_tab",
            "idempotencyKey": "habit-sync-complete-1",
        },
    )
    app.dependency_overrides.clear()

    assert complete.status_code == 200
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["completed_at"] is not None
    assert fact["recurrence_rule"] == "daily"
    assert fact["content"]["time"]["recurrence_rule"] == "daily"
    assert fact["created_from"]["last_mutation_idempotency_key"] == "habit-sync-complete-1"
