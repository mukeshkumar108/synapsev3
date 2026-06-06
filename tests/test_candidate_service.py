from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from agent_contract import AgentOutput
from core.candidates import build_candidate_record, candidate_records_from_outputs


def test_build_candidate_record_maps_invitation_type() -> None:
    record = build_candidate_record(
        user_id="user-1",
        source_id=uuid4(),
        agent_name="event_agent",
        item={
            "title": "Dinner with Alex",
            "date": "2026-05-26",
            "time": "2026-05-26T19:00:00",
            "duration": None,
            "location": "Shoreditch",
            "attendees": ["Alex"],
            "is_invitation": True,
            "needs_confirmation": False,
            "is_past": False,
            "urgency": "medium",
            "salience": "medium",
            "sensitivity": "low",
            "related_people": ["Alex"],
            "related_projects": [],
            "raw_evidence": "Alex invited me to dinner next Tuesday at 7pm in Shoreditch.",
            "confidence": 0.92,
            "companion_category": None,
        },
        created_at=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert record["candidate_type"] == "invitation"
    assert record["status"] == "pending"
    assert record["needs_confirmation"] is False
    assert record["content"]["schema_version"] == "v1"
    assert record["content"]["item_type"] == "invitation"
    assert record["content"]["evidence"]["raw_evidence"] == (
        "Alex invited me to dinner next Tuesday at 7pm in Shoreditch."
    )
    assert record["content"]["links"]["people"] == ["Alex"]
    assert record["content"]["lifecycle"]["follow_up_after_hours"] is None
    assert record["content"]["metadata"]["companion_category"] is None
    assert record["content"]["metadata"]["agent_item"]["title"] == "Dinner with Alex"


def test_candidate_records_from_outputs_skips_failed_agents() -> None:
    source_id = uuid4()
    records = candidate_records_from_outputs(
        user_id="user-1",
        source_id=source_id,
        outputs=[
            AgentOutput(
                agent="task_agent",
                status="success",
                items=[
                    {
                        "title": "Call insurance",
                        "description": None,
                        "due_date": None,
                        "reminder_at": "2026-05-23T08:00:00",
                        "priority": "high",
                        "urgency": "high",
                        "is_habit": False,
                        "recurrence": None,
                        "waiting_on": None,
                        "needs_confirmation": False,
                        "salience": "high",
                        "raw_evidence": "Remind me at 8am to call insurance",
                        "confidence": 0.96,
                        "related_people": [],
                        "related_projects": [],
                        "companion_category": None,
                    }
                ],
                errors=[],
                confidence_notes="ok",
            ),
            AgentOutput(
                agent="fact_agent",
                status="error",
                items=[],
                errors=["bad"],
                confidence_notes="bad",
            ),
        ],
    )

    assert len(records) == 1
    assert records[0]["candidate_type"] == "reminder"
    assert records[0]["source_id"] == source_id
    assert records[0]["content"]["schema_version"] == "v1"
    assert records[0]["content"]["item_type"] == "task"
    assert records[0]["structured_content"]["kind"] == "reminder"
    assert records[0]["content"]["evidence"]["raw_evidence"] == "Remind me at 8am to call insurance"
    assert records[0]["content"]["links"]["people"] == []
    assert records[0]["content"]["metadata"]["companion_category"] is None
    assert records[0]["content"]["metadata"]["agent_item"]["title"] == "Call insurance"


def test_candidate_record_preserves_companion_category_metadata() -> None:
    record = build_candidate_record(
        user_id="user-1",
        source_id=uuid4(),
        agent_name="fact_agent",
        item={
            "subject": "user",
            "fact_type": "preference",
            "content": "The user prefers direct, practical support over heavy comforting.",
            "companion_category": "communication_preference",
            "about_user": True,
            "person_name": None,
            "related_people": [],
            "related_projects": [],
            "salience": "high",
            "sensitivity": "medium",
            "needs_confirmation": False,
            "raw_evidence": "Please don't over-comfort me. Just be direct and give me the next step.",
            "confidence": 0.98,
        },
        created_at=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert record["candidate_type"] == "fact"
    assert record["content"]["metadata"]["companion_category"] == "communication_preference"
    assert record["content"]["metadata"]["agent_item"]["companion_category"] == "communication_preference"
