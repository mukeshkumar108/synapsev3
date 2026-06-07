from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from core import decay


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            limit = args[0]
            rows = [fact for fact in self.confirmed_facts.values() if fact["status"] == "active"]
            return rows[:limit]
        return []

    async def execute(self, query: str, *args):
        if "UPDATE confirmed_facts" in query and "status = 'stale'" in query:
            self.confirmed_facts[args[0]]["status"] = "stale"
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


def _fact(
    *,
    fact_type: str = "state",
    domain: str = "state",
    item_type: str = "state",
    salience: str = "medium",
    status: str = "active",
    last_seen_at: datetime | None = None,
    last_confirmed_at: datetime | None = None,
    first_seen_at: datetime | None = None,
    stale_after_hours: int | None = None,
    expires_at: str | datetime | None = None,
    provisional: bool = True,
    companion_category: str | None = None,
) -> dict:
    lifecycle = {
        "follow_up_after_hours": None,
        "stale_after_hours": stale_after_hours,
        "expires_at": expires_at if isinstance(expires_at, str) else None,
    }
    time_block = {
        "due_date": None,
        "reminder_at": None,
        "date": None,
        "time": None,
        "duration": None,
        "follow_up_after_hours": None,
        "stale_after_hours": stale_after_hours,
        "expires_at": expires_at if isinstance(expires_at, str) else None,
    }
    return {
        "id": uuid4(),
        "user_id": "user-1",
        "fact_type": fact_type,
        "domain": domain,
        "content": {
            "schema_version": "v1",
            "item_type": item_type,
            "title": "Current state",
            "summary": "User feels stressed.",
            "salience": salience,
            "priority": None,
            "urgency": None,
            "importance": salience,
            "sensitivity": "medium",
            "time": time_block,
            "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
            "lifecycle": lifecycle,
            "evidence": {"raw_evidence": "I am stressed.", "source_turn_refs": []},
            "metadata": {
                "companion_category": companion_category,
                "agent_item": {"provisional": provisional},
            },
        },
        "confidence": 0.9,
        "first_seen_at": first_seen_at or datetime(2026, 5, 20, 12, 0),
        "last_seen_at": last_seen_at or datetime(2026, 5, 20, 12, 0),
        "last_confirmed_at": last_confirmed_at or datetime(2026, 5, 20, 12, 0),
        "source_ids": [uuid4()],
        "status": status,
        "user_corrected": False,
        "correction_note": None,
        "expires_at": expires_at if isinstance(expires_at, datetime) else None,
    }


async def test_active_state_older_than_stale_after_hours_becomes_stale() -> None:
    db = FakeDatabase()
    fact = _fact(last_seen_at=datetime(2026, 5, 20, 10, 0), stale_after_hours=24)
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=False)

    assert len(results) == 1
    assert db.confirmed_facts[fact["id"]]["status"] == "stale"


async def test_active_recent_state_does_not_become_stale() -> None:
    db = FakeDatabase()
    fact = _fact(last_seen_at=datetime(2026, 5, 22, 2, 0), stale_after_hours=24)
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=False)

    assert results == []
    assert db.confirmed_facts[fact["id"]]["status"] == "active"


async def test_explicit_expires_at_in_past_becomes_stale() -> None:
    db = FakeDatabase()
    fact = _fact(expires_at="2026-05-21T12:00:00Z", stale_after_hours=None)
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=False)

    assert len(results) == 1
    assert results[0]["reason"] == "expires_at passed"
    assert db.confirmed_facts[fact["id"]]["status"] == "stale"


async def test_low_salience_state_uses_shorter_default_window() -> None:
    db = FakeDatabase()
    fact = _fact(salience="low", last_seen_at=datetime(2026, 5, 21, 11, 0), stale_after_hours=None)
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=True)

    assert len(results) == 1


async def test_high_salience_state_uses_longer_default_window() -> None:
    db = FakeDatabase()
    fact = _fact(salience="high", last_seen_at=datetime(2026, 5, 20, 13, 0), stale_after_hours=None)
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=True)

    assert results == []


async def test_avoid_topic_is_not_decayed() -> None:
    db = FakeDatabase()
    fact = _fact(
        fact_type="state",
        domain="state",
        item_type="state",
        companion_category="avoid_topic",
        last_seen_at=datetime(2026, 5, 19, 12, 0),
        stale_after_hours=24,
    )
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=False)

    assert results == []
    assert db.confirmed_facts[fact["id"]]["status"] == "active"


async def test_communication_preference_is_not_decayed() -> None:
    db = FakeDatabase()
    fact = _fact(
        fact_type="preference",
        domain="profile",
        item_type="fact",
        provisional=False,
        companion_category="communication_preference",
        last_seen_at=datetime(2026, 5, 19, 12, 0),
        stale_after_hours=24,
    )
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=False)

    assert results == []
    assert db.confirmed_facts[fact["id"]]["status"] == "active"


async def test_durable_non_state_fact_is_not_decayed() -> None:
    db = FakeDatabase()
    fact = _fact(
        fact_type="relationship",
        domain="people",
        item_type="fact",
        provisional=False,
        companion_category="relationship_context",
        last_seen_at=datetime(2026, 5, 19, 12, 0),
        stale_after_hours=24,
    )
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=False)

    assert results == []
    assert db.confirmed_facts[fact["id"]]["status"] == "active"


async def test_stale_transition_writes_timeline_event() -> None:
    db = FakeDatabase()
    fact = _fact(last_seen_at=datetime(2026, 5, 20, 10, 0), stale_after_hours=24)
    db.confirmed_facts[fact["id"]] = fact

    await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=False)

    assert len(db.timeline_events) == 1
    assert db.timeline_events[0]["event_type"] == "state_change"
    assert db.timeline_events[0]["timeline_type"] == "system"
    assert db.timeline_events[0]["related_fact_ids"] == [fact["id"]]


async def test_dry_run_returns_would_decay_without_writing() -> None:
    db = FakeDatabase()
    fact = _fact(last_seen_at=datetime(2026, 5, 20, 10, 0), stale_after_hours=24)
    db.confirmed_facts[fact["id"]] = fact

    results = await decay.decay_state_memories(db, now=datetime(2026, 5, 22, 12, 0), dry_run=True)

    assert len(results) == 1
    assert db.confirmed_facts[fact["id"]]["status"] == "active"
    assert db.timeline_events == []
