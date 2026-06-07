from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core import followup_runtime


pytestmark = pytest.mark.anyio


class MockLLMClient:
    def __init__(self, response):
        self.response = response

    def generate_json(self, **_: object):
        return self.response


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []
        self.session_summaries: list[dict] = []
        self.outbox_rows: list[dict] = []


def _seed_thread(
    db: FakeDatabase,
    *,
    title: str,
    summary: str,
    last_seen_at: datetime,
    hours: int = 2,
) -> None:
    thread_id = uuid4()
    source_id = uuid4()
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
            "metadata": {
                "item_status": "active",
                "open_loop_status": "active",
                "follow_up_question": f"{title} update?",
                "surface_reason": f"{title} is still unresolved.",
                "next_move": "follow_up",
            },
            "lifecycle": {"follow_up_after_hours": hours, "stale_after_hours": None, "expires_at": None},
            "time": {"follow_up_after_hours": hours},
        },
        "structured_content": {"kind": "thread", "thread": {"follow_up_needed": True, "open_loop_status": "active"}},
        "confidence": 0.95,
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
        "thread_type": "care_checkin",
        "actionability": "check_in",
        "next_move": "follow_up",
        "last_progressed_at": None,
        "last_resurfaced_at": None,
        "snoozed_until": None,
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }


async def test_runtime_suppresses_if_user_was_recently_active() -> None:
    db = FakeDatabase()
    now = datetime(2026, 6, 7, 12, 0)
    _seed_thread(db, title="Leg injury", summary="My leg hurts.", last_seen_at=now - timedelta(hours=3))
    db.session_summaries.append({"user_id": "user-1", "occurred_at": now - timedelta(minutes=5)})

    plan = await followup_runtime.plan_follow_up(db, user_id="user-1", current_datetime=now, timezone_name="Europe/London")

    assert plan["decision"] == "suppress"
    assert plan["agent_decision"] is None
    assert plan["reason"] == "recent_user_activity"


async def test_runtime_uses_agent_for_single_best_follow_up() -> None:
    db = FakeDatabase()
    now = datetime(2026, 6, 7, 12, 0)
    _seed_thread(db, title="Leg injury", summary="My leg hurts.", last_seen_at=now - timedelta(hours=3))
    _seed_thread(db, title="Sarah flu", summary="My niece Sarah has the flu.", last_seen_at=now - timedelta(days=8), hours=168)

    plan = await followup_runtime.plan_follow_up(
        db,
        user_id="user-1",
        current_datetime=now,
        timezone_name="Europe/London",
        llm_client=MockLLMClient(
            {
                "decision": "send_now",
                "selected_thread_ids": [next(iter(db.confirmed_facts.keys())).__str__()],
                "rationale": "The symptom follow-up is the most time-sensitive.",
                "message": "Checking in: how is your leg feeling now?",
                "defer_hours": None,
                "bundle_strategy": "single",
                "sensitivity": "medium",
            }
        ),
    )

    assert plan["decision"] == "send_now"
    assert plan["agent_decision"] is not None
    assert plan["message"] == "Checking in: how is your leg feeling now?"


async def test_runtime_respects_daily_proactive_capacity_before_agent() -> None:
    db = FakeDatabase()
    now = datetime(2026, 6, 7, 12, 0)
    _seed_thread(db, title="Leg injury", summary="My leg hurts.", last_seen_at=now - timedelta(hours=3))
    db.timeline_events.extend(
        [
            {"user_id": "user-1", "event_type": "thread_progressed", "timeline_type": "system", "occurred_at": now - timedelta(hours=2)},
            {"user_id": "user-1", "event_type": "thread_progressed", "timeline_type": "system", "occurred_at": now - timedelta(hours=1)},
        ]
    )

    plan = await followup_runtime.plan_follow_up(db, user_id="user-1", current_datetime=now, timezone_name="Europe/London")

    assert plan["decision"] == "suppress"
    assert plan["reason"] == "daily_limit_reached"
    assert plan["agent_decision"] is None
