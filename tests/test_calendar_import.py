from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest

from core import calendar_import


pytestmark = pytest.mark.anyio


class FakeDatabase:
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


def _payload(*, event_overrides: dict | None = None) -> dict:
    event = {
        "external_id": "evt-1",
        "title": "Product review",
        "description": None,
        "starts_at": "2026-05-23T10:00:00+01:00",
        "ends_at": "2026-05-23T11:00:00+01:00",
        "timezone": "Europe/London",
        "all_day": False,
        "location": None,
        "participants": ["sam@example.com"],
        "organizer": "maya@example.com",
        "status": "confirmed",
        "external_updated_at": "2026-05-22T09:00:00+01:00",
        "etag": None,
        "raw": {"id": "evt-1"},
    }
    if event_overrides:
        event.update(event_overrides)
    return {
        "user_id": "user-1",
        "source_type": "calendar",
        "external_provider": "google",
        "external_calendar_id": "primary",
        "events": [event],
    }


async def test_imports_confirmed_calendar_event() -> None:
    db = FakeDatabase()

    result = await calendar_import.import_calendar_events(
        db,
        payload=_payload(),
        now=datetime(2026, 5, 22, 12, 0),
    )

    assert result["created"] == 1
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "event"
    assert fact["domain"] == "events"
    assert fact["content"]["item_type"] == "event"
    assert fact["content"]["title"] == "Product review"


async def test_creates_one_confirmed_fact() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(db, payload=_payload(), now=datetime(2026, 5, 22, 12, 0))

    assert len(db.confirmed_facts) == 1


async def test_writes_one_timeline_event() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(db, payload=_payload(), now=datetime(2026, 5, 22, 12, 0))

    assert len(db.timeline_events) == 1
    assert db.timeline_events[0]["event_type"] == "event_confirmed"
    assert db.timeline_events[0]["timeline_type"] == "calendar"


async def test_duplicate_import_same_external_id_does_not_create_duplicate_fact() -> None:
    db = FakeDatabase()
    payload = _payload()

    await calendar_import.import_calendar_events(db, payload=payload, now=datetime(2026, 5, 22, 12, 0))
    await calendar_import.import_calendar_events(db, payload=payload, now=datetime(2026, 5, 22, 13, 0))

    assert len(db.confirmed_facts) == 1
    fact = next(iter(db.confirmed_facts.values()))
    assert len(fact["source_ids"]) == 2


async def test_changed_title_and_time_updates_existing_fact() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(db, payload=_payload(), now=datetime(2026, 5, 22, 12, 0))
    await calendar_import.import_calendar_events(
        db,
        payload=_payload(
            event_overrides={
                "title": "Updated product review",
                "starts_at": "2026-05-23T12:00:00+01:00",
                "ends_at": "2026-05-23T13:00:00+01:00",
            }
        ),
        now=datetime(2026, 5, 22, 13, 0),
    )

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["content"]["title"] == "Updated product review"
    assert fact["content"]["time"]["starts_at"] == "2026-05-23T12:00:00+01:00"
    assert fact["last_seen_at"] == datetime(2026, 5, 22, 13, 0)


async def test_cancelled_event_is_marked_without_deleting() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(
        db,
        payload=_payload(event_overrides={"status": "cancelled"}),
        now=datetime(2026, 5, 22, 12, 0),
    )

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["status"] == "historical"
    assert fact["content"]["metadata"]["calendar_status"] == "cancelled"
    assert len(db.confirmed_facts) == 1
    assert db.timeline_events[0]["status"] == "historical"


async def test_provider_metadata_is_preserved() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(db, payload=_payload(), now=datetime(2026, 5, 22, 12, 0))

    fact = next(iter(db.confirmed_facts.values()))
    metadata = fact["content"]["metadata"]
    assert metadata["external_provider"] == "google"
    assert metadata["external_calendar_id"] == "primary"
    assert metadata["external_id"] == "evt-1"
    assert metadata["source_type"] == "calendar"


async def test_all_day_event_is_preserved() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(
        db,
        payload=_payload(
            event_overrides={
                "all_day": True,
                "starts_at": "2026-05-24",
                "ends_at": "2026-05-25",
            }
        ),
        now=datetime(2026, 5, 22, 12, 0),
    )

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["content"]["time"]["all_day"] is True
    assert fact["content"]["time"]["starts_at"] == "2026-05-24"


async def test_tentative_event_is_preserved_with_lower_confidence() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(
        db,
        payload=_payload(event_overrides={"status": "tentative"}),
        now=datetime(2026, 5, 22, 12, 0),
    )

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["status"] == "active"
    assert fact["confidence"] == 0.85
    assert fact["content"]["metadata"]["calendar_status"] == "tentative"


async def test_no_schema_changes_required_for_calendar_import() -> None:
    db = FakeDatabase()

    await calendar_import.import_calendar_events(db, payload=_payload(), now=datetime(2026, 5, 22, 12, 0))

    assert len(db.outbox_rows) == 1
    assert len(db.confirmed_facts) == 1
    assert len(db.timeline_events) == 1
