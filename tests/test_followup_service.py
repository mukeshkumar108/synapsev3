from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core import followup_service


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []


def _seed_thread(
    db: FakeDatabase,
    *,
    title: str,
    summary: str,
    hours: int,
    last_seen_at: datetime,
    snoozed_until: str | None = None,
    follow_up_needed: bool = True,
    status: str = "active",
) -> UUID:
    thread_id = uuid4()
    source_id = uuid4()
    metadata = {
        "item_status": "active",
        "open_loop_status": "active",
        "follow_up_question": f"{title} update?",
        "surface_reason": f"{title} is still unresolved.",
        "next_move": "follow_up",
    }
    if snoozed_until is not None:
        metadata["snoozed_until"] = snoozed_until
    db.confirmed_facts[thread_id] = {
        "id": thread_id,
        "user_id": "user-1",
        "fact_type": "thread",
        "domain": "people",
        "content": {
            "schema_version": "v1",
            "item_type": "thread",
            "title": title,
            "summary": summary,
            "priority": "high",
            "links": {"people": ["Sarah"], "projects": [], "topics": ["health"], "related_facts": [], "related_threads": []},
            "evidence": {"raw_evidence": summary, "source_turn_refs": []},
            "metadata": metadata,
            "lifecycle": {"follow_up_after_hours": hours, "stale_after_hours": None, "expires_at": None},
            "time": {"follow_up_after_hours": hours},
        },
        "structured_content": {
            "kind": "thread",
            "thread": {
                "follow_up_needed": follow_up_needed,
                "open_loop_status": "active",
                "next_move": "follow_up",
                "surface_reason": f"{title} is still unresolved.",
                "last_resurfaced_at": None,
                "snoozed_until": snoozed_until,
            },
        },
        "confidence": 0.92,
        "first_seen_at": last_seen_at,
        "last_seen_at": last_seen_at,
        "last_confirmed_at": last_seen_at,
        "source_ids": [source_id],
        "source_type": "chat",
        "primary_source_id": source_id,
        "who_said_it": "user",
        "original_text": summary,
        "channel": "chat",
        "conversation_id": "conv-1",
        "created_from": {"writer": "test"},
        "provenance": {"source_id": str(source_id), "source_ids": [str(source_id)], "source_type": "chat", "who_said_it": "user", "original_text": summary, "channel": "chat", "conversation_id": "conv-1", "created_from": {"writer": "test"}},
        "status": status,
        "starts_at": None,
        "ends_at": None,
        "due_at": None,
        "remind_at": None,
        "timezone": None,
        "recurrence_rule": None,
        "completed_at": None,
        "cancelled_at": None,
        "priority": "high",
        "follow_up_needed": follow_up_needed,
        "thread_type": "care_checkin",
        "actionability": "check_in",
        "next_move": "follow_up",
        "last_progressed_at": None,
        "last_resurfaced_at": None,
        "snoozed_until": None if snoozed_until is None else datetime.fromisoformat(snoozed_until.replace("Z", "+00:00")).replace(tzinfo=None),
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }
    return thread_id


async def test_due_follow_up_packets_select_only_due_threads() -> None:
    db = FakeDatabase()
    now = datetime(2026, 6, 7, 12, 0)
    _seed_thread(
        db,
        title="Leg injury",
        summary="My leg really hurts after I tripped.",
        hours=2,
        last_seen_at=now - timedelta(hours=3),
    )
    _seed_thread(
        db,
        title="Sarah flu",
        summary="My niece Sarah is home with the flu.",
        hours=168,
        last_seen_at=now - timedelta(days=8),
    )
    _seed_thread(
        db,
        title="Not due yet",
        summary="Waiting on an update tomorrow.",
        hours=24,
        last_seen_at=now - timedelta(hours=4),
    )
    _seed_thread(
        db,
        title="Snoozed loop",
        summary="This should stay hidden for now.",
        hours=2,
        last_seen_at=now - timedelta(hours=3),
        snoozed_until="2099-06-07T20:00:00+00:00",
    )

    packets = await followup_service.due_follow_up_packets(db, user_id="user-1", now=now)

    assert [packet["title"] for packet in packets] == ["Sarah flu", "Leg injury"]
    assert packets[0]["follow_up_question"] == "Sarah flu update?"
    assert packets[1]["linked_people"] == ["Sarah"]
    assert packets[0]["overdue_hours"] >= 24.0
    assert packets[1]["overdue_hours"] >= 1.0


async def test_mark_thread_resurfaced_updates_thread_and_prevents_immediate_repeat() -> None:
    db = FakeDatabase()
    now = datetime(2026, 6, 7, 12, 0)
    thread_id = _seed_thread(
        db,
        title="Leg injury",
        summary="My leg really hurts after I tripped.",
        hours=2,
        last_seen_at=now - timedelta(hours=3),
    )

    due_before = await followup_service.due_follow_up_packets(db, user_id="user-1", now=now)
    assert [packet["title"] for packet in due_before] == ["Leg injury"]

    updated = await followup_service.mark_thread_resurfaced(
        db,
        user_id="user-1",
        item_id=thread_id,
        surfaced_at=now,
        surface_reason="Checking back in on the leg pain.",
    )

    assert updated["last_resurfaced_at"] == now
    assert updated["content"]["metadata"]["last_resurfaced_at"] == "2026-06-07T12:00:00+00:00"
    assert updated["content"]["metadata"]["surface_reason"] == "Checking back in on the leg pain."
    assert db.timeline_events[-1]["event_type"] == "thread_progressed"

    due_after = await followup_service.due_follow_up_packets(db, user_id="user-1", now=now)
    assert due_after == []


async def test_thread_follow_up_due_ignores_non_active_threads() -> None:
    db = FakeDatabase()
    now = datetime(2026, 6, 7, 12, 0)
    active_id = _seed_thread(
        db,
        title="Sarah flu",
        summary="My niece Sarah is home with the flu.",
        hours=48,
        last_seen_at=now - timedelta(days=3),
    )
    dismissed_id = _seed_thread(
        db,
        title="Dismissed loop",
        summary="No need to surface this.",
        hours=2,
        last_seen_at=now - timedelta(hours=3),
        status="dismissed",
    )
    db.confirmed_facts[dismissed_id]["content"]["metadata"]["open_loop_status"] = "dismissed"
    db.confirmed_facts[active_id]["follow_up_needed"] = False

    rows = await followup_service.due_follow_up_rows(db, user_id="user-1", now=now)

    assert rows == []
