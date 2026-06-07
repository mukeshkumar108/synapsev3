from __future__ import annotations

from agents import followup_agent


class MockLLMClient:
    def __init__(self, response):
        self.response = response

    def generate_json(self, **_: object):
        return self.response


def _candidate(thread_id: str, title: str) -> dict:
    return {
        "thread_id": thread_id,
        "title": title,
        "summary": f"{title} summary",
        "follow_up_question": f"{title} update?",
        "due_at": "2026-06-07T10:00:00+00:00",
        "overdue_hours": 2.0,
        "thread_type": "care_checkin",
        "actionability": "check_in",
        "next_move": "follow_up",
        "surface_reason": f"{title} is still unresolved.",
        "linked_people": [],
        "linked_projects": [],
        "linked_topics": [],
        "source_refs": [],
        "confidence": 0.9,
        "last_seen_at": "2026-06-07T08:00:00+00:00",
        "last_resurfaced_at": None,
    }


def test_followup_agent_validates_send_now_single_item() -> None:
    result = followup_agent.run(
        candidates=[_candidate("t1", "Leg injury")],
        current_datetime="2026-06-07T12:00:00+00:00",
        timezone="Europe/London",
        recent_user_activity=None,
        llm_client=MockLLMClient(
            {
                "decision": "send_now",
                "selected_thread_ids": ["t1"],
                "rationale": "A health check-in is overdue and worth asking gently now.",
                "message": "Checking in: how is your leg feeling now?",
                "defer_hours": None,
                "bundle_strategy": "single",
                "sensitivity": "medium",
            }
        ),
    )
    assert result["decision"] == "send_now"
    assert result["selected_thread_ids"] == ["t1"]


def test_followup_agent_validates_bundle_decision() -> None:
    result = followup_agent.run(
        candidates=[_candidate("t1", "Leg injury"), _candidate("t2", "Sarah flu")],
        current_datetime="2026-06-07T12:00:00+00:00",
        timezone="Europe/London",
        recent_user_activity=None,
        llm_client=MockLLMClient(
            {
                "decision": "send_now",
                "selected_thread_ids": ["t1", "t2"],
                "rationale": "Both items are care-related and can be asked in one brief check-in.",
                "message": "Quick check-in: how is your leg now, and how is Sarah doing this week?",
                "defer_hours": None,
                "bundle_strategy": "bundle",
                "sensitivity": "medium",
            }
        ),
    )
    assert result["bundle_strategy"] == "bundle"
    assert len(result["selected_thread_ids"]) == 2
