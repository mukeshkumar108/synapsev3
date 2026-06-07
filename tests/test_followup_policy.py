from __future__ import annotations

from datetime import datetime, timedelta

from core import followup_policy


def _packet(
    thread_id: str,
    *,
    title: str,
    summary: str,
    overdue_hours: float,
    last_resurfaced_at: str | None = None,
) -> dict:
    return {
        "thread_id": thread_id,
        "title": title,
        "summary": summary,
        "follow_up_question": "Any update?",
        "due_at": "2026-06-07T10:00:00+00:00",
        "overdue_hours": overdue_hours,
        "thread_type": "care_checkin",
        "actionability": "check_in",
        "next_move": "follow_up",
        "surface_reason": summary,
        "linked_people": ["Sarah"],
        "linked_projects": [],
        "linked_topics": ["health"],
        "source_refs": ["outbox:1"],
        "confidence": 0.9,
        "last_seen_at": "2026-06-07T08:00:00+00:00",
        "last_resurfaced_at": last_resurfaced_at,
    }


def test_policy_suppresses_when_user_was_recently_active() -> None:
    now = datetime(2026, 6, 7, 12, 0)
    result = followup_policy.evaluate_follow_up_candidates(
        [_packet("t1", title="Leg injury", summary="Leg pain follow-up", overdue_hours=1.5)],
        current_datetime=now,
        recent_user_activity_at=now - timedelta(minutes=10),
    )
    assert result["status"] == "suppress"
    assert result["reason"] == "recent_user_activity"
    assert result["candidates"] == []


def test_policy_suppresses_recently_resurfaced_threads() -> None:
    now = datetime(2026, 6, 7, 12, 0)
    result = followup_policy.evaluate_follow_up_candidates(
        [_packet("t1", title="Leg injury", summary="Leg pain follow-up", overdue_hours=2.0, last_resurfaced_at="2026-06-07T10:30:00+00:00")],
        current_datetime=now,
    )
    assert result["status"] == "suppress"
    assert result["suppressed"] == [{"thread_id": "t1", "reason": "recent_resurfacing"}]


def test_policy_rolls_over_excess_candidates_after_shortlist() -> None:
    now = datetime(2026, 6, 7, 12, 0)
    result = followup_policy.evaluate_follow_up_candidates(
        [
            _packet("t1", title="Leg injury", summary="Leg pain follow-up", overdue_hours=5.0),
            _packet("t2", title="Sarah flu", summary="Niece recovery follow-up", overdue_hours=30.0),
            _packet("t3", title="Contract", summary="Waiting on Jordan reply", overdue_hours=8.0),
            _packet("t4", title="Dinner", summary="Meal planning loop", overdue_hours=3.0),
        ],
        current_datetime=now,
    )
    assert result["status"] == "candidate_review"
    assert len(result["candidates"]) == 3
    assert any(item["reason"] == "rollover_capacity" for item in result["deferred"])


def test_policy_defers_freshly_due_items() -> None:
    now = datetime(2026, 6, 7, 12, 0)
    result = followup_policy.evaluate_follow_up_candidates(
        [_packet("t1", title="Leg injury", summary="Leg pain follow-up", overdue_hours=0.1)],
        current_datetime=now,
    )
    assert result["status"] == "defer"
    assert result["reason"] == "nothing_mature_enough"
