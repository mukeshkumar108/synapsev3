from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from core import serving


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.confirmed_facts: list[dict] = []
        self.timeline_events: list[dict] = []
        self.session_summaries: list[dict] = []
        self.outbox_rows: list[dict] = []

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            return [row for row in self.confirmed_facts if row["user_id"] == args[0] and row["status"] == "active"]
        if "FROM timeline_events" in query:
            return [row for row in self.timeline_events if row["user_id"] == args[0]][: args[1]]
        if "FROM session_summaries" in query:
            rows = [row for row in self.session_summaries if row["user_id"] == args[0]]
            rows.sort(key=lambda row: row["occurred_at"], reverse=True)
            return rows[: args[1]]
        if "FROM outbox" in query:
            rows = [
                row for row in self.outbox_rows
                if row["user_id"] == args[0] and row["status"] in {"pending", "processing"}
            ]
            rows.sort(key=lambda row: row["received_at"], reverse=True)
            return rows
        return []


def _summary(user_id: str, text: str, occurred_at: datetime) -> dict:
    return {
        "id": uuid4(),
        "user_id": user_id,
        "source_id": uuid4(),
        "summary": text,
        "tags": ["personal"],
        "open_items": [],
        "key_decisions": [],
        "emotional_tone": "neutral",
        "occurred_at": occurred_at,
    }


def _fact(
    *,
    user_id: str = "user-1",
    fact_type: str,
    domain: str,
    title: str | None,
    summary: str | None,
    status: str = "active",
    last_seen_at: datetime | None = None,
    expires_at=None,
    companion_category: str | None = None,
    links: dict | None = None,
    lifecycle: dict | None = None,
    time: dict | None = None,
    salience: str | None = "medium",
    importance: str | None = "medium",
    urgency: str | None = None,
    sensitivity: str | None = "low",
    provisional: bool = False,
) -> dict:
    return {
        "id": uuid4(),
        "user_id": user_id,
        "fact_type": fact_type,
        "domain": domain,
        "content": {
            "schema_version": "v1",
            "item_type": "state" if fact_type == "state" or domain == "state" or provisional else ("thread" if fact_type == "thread" else "fact"),
            "title": title,
            "summary": summary,
            "salience": salience,
            "priority": None,
            "urgency": urgency,
            "importance": importance,
            "sensitivity": sensitivity,
            "time": time or {},
            "links": links or {"people": [], "projects": [], "related_facts": [], "related_threads": []},
            "lifecycle": lifecycle or {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
            "evidence": {"raw_evidence": summary or title or "", "source_turn_refs": []},
            "metadata": {"companion_category": companion_category, "agent_item": {"provisional": provisional}},
        },
        "confidence": 0.9,
        "first_seen_at": datetime(2026, 5, 20, 12, 0),
        "last_seen_at": last_seen_at or datetime(2026, 5, 22, 12, 0),
        "last_confirmed_at": last_seen_at or datetime(2026, 5, 22, 12, 0),
        "source_ids": [uuid4()],
        "status": status,
        "user_corrected": False,
        "correction_note": None,
        "expires_at": expires_at,
    }


def _packet_stub(**kwargs):
    threads = kwargs["threads"]
    return {
        "session_instructions": "Use the packet privately.",
        "relevant_topics": [thread["content"]["title"] for thread in threads[:1] if thread.get("content", {}).get("title")],
        "worth_attention": [
            {
                "title": thread["content"]["title"],
                "why_it_matters": "Open loop remains active.",
                "suggested_way_to_raise": "Check whether it moved.",
                "sensitivity": thread["content"].get("sensitivity") or "low",
                "source_fact_ids": [str(thread["id"])],
            }
            for thread in threads[:1]
            if thread.get("content", {}).get("title")
        ],
        "suggested_focus": "Current conversation",
        "tone_note": "Neutral and grounded.",
        "avoid": [],
        "stale_warnings": [],
    }


async def test_cold_start_returns_grounded_empty_handover(monkeypatch) -> None:
    db = FakeDatabase()
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    packet = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T09:00:00+01:00",
        timezone_name="Europe/London",
    )

    assert packet["handover_depth"] == "cold_start"
    assert packet["last_session_summary"] is None
    assert packet["today_context"] == []
    assert packet["yesterday_context"] == []
    assert packet["last_interaction_at"] is None


async def test_continuation_and_same_day_handover(monkeypatch) -> None:
    db = FakeDatabase()
    db.session_summaries.append(_summary("user-1", "We were discussing Ashley.", datetime(2026, 5, 22, 8, 45)))
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    continuation = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T09:00:00+01:00",
        timezone_name="Europe/London",
    )
    same_day = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T15:00:00+01:00",
        timezone_name="Europe/London",
    )

    assert continuation["handover_depth"] == "continuation"
    assert continuation["sessions_today_count"] == 1
    assert continuation["is_first_contact_today"] is False
    assert continuation["last_session_summary"]["summary"] == "We were discussing Ashley."
    assert same_day["handover_depth"] == "same_day"
    assert same_day["today_context"][0]["summary"] == "We were discussing Ashley."


async def test_yesterday_and_multi_day_handover(monkeypatch) -> None:
    db = FakeDatabase()
    db.session_summaries.append(_summary("user-1", "Yesterday we discussed Nina.", datetime(2026, 5, 21, 20, 0)))
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    yesterday = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T09:00:00+01:00",
        timezone_name="Europe/London",
    )
    db.session_summaries[0] = _summary("user-1", "Last week we discussed Nina.", datetime(2026, 5, 18, 20, 0))
    multi_day = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T09:00:00+01:00",
        timezone_name="Europe/London",
    )

    assert yesterday["handover_depth"] == "yesterday"
    assert yesterday["yesterday_context"][0]["summary"] == "Yesterday we discussed Nina."
    assert multi_day["handover_depth"] == "multi_day"
    assert multi_day["yesterday_context"] == []


async def test_avoid_topic_only_in_avoid_and_stale_state_not_current(monkeypatch) -> None:
    db = FakeDatabase()
    db.confirmed_facts.extend(
        [
            _fact(
                fact_type="identity",
                domain="profile",
                title="user",
                summary="Avoid fertility topic unless user raises it.",
                companion_category="avoid_topic",
                sensitivity="high",
                links={"people": [], "projects": ["fertility"], "related_facts": [], "related_threads": []},
            ),
            _fact(
                fact_type="state",
                domain="state",
                title=None,
                summary="User felt stressed.",
                time={"stale_after_hours": 4},
                lifecycle={"expires_at": None, "stale_after_hours": 4, "follow_up_after_hours": None},
                last_seen_at=datetime(2026, 5, 20, 8, 0),
                provisional=True,
            ),
        ]
    )

    captured = {}

    def fake_run(**kwargs):
        captured["state"] = kwargs["state"]
        return {
            "session_instructions": "Use packet privately.",
            "relevant_topics": ["fertility topic"],
            "worth_attention": [
                {
                    "title": "Avoid fertility topic unless user raises it.",
                    "why_it_matters": "Sensitive.",
                    "suggested_way_to_raise": "Do not raise it.",
                    "sensitivity": "high",
                    "source_fact_ids": [str(db.confirmed_facts[0]["id"])],
                }
            ],
            "suggested_focus": "Current conversation",
            "tone_note": "Respectful.",
            "avoid": [],
            "stale_warnings": [],
        }

    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_run)
    packet = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T12:00:00+01:00",
        timezone_name="Europe/London",
    )

    assert captured["state"] == []
    assert packet["avoid"]
    assert packet["worth_attention"] == []
    assert packet["relevant_topics"] == []


async def test_freshness_open_loops_entity_hints_and_user_isolation(monkeypatch) -> None:
    db = FakeDatabase()
    db.confirmed_facts.extend(
        [
            _fact(
                user_id="user-1",
                fact_type="thread",
                domain="people",
                title="Waiting on Jordan contract",
                summary="Still waiting on Jordan.",
                salience="high",
                importance="high",
                urgency="high",
                links={"people": ["Jordan"], "projects": ["contract"], "related_facts": [], "related_threads": []},
            ),
            _fact(
                user_id="user-1",
                fact_type="relationship",
                domain="people",
                title="Nina",
                summary="Nina is important to the user.",
                links={"people": ["Nina"], "projects": [], "related_facts": [], "related_threads": []},
            ),
            _fact(
                user_id="user-2",
                fact_type="thread",
                domain="people",
                title="Other user loop",
                summary="Should not leak.",
                links={"people": ["Mallory"], "projects": [], "related_facts": [], "related_threads": []},
            ),
        ]
    )
    db.session_summaries.extend(
        [
            _summary("user-1", "User one summary", datetime(2026, 5, 22, 8, 0)),
            _summary("user-2", "User two summary", datetime(2026, 5, 22, 8, 0)),
        ]
    )
    db.outbox_rows.extend(
        [
            {"id": uuid4(), "user_id": "user-1", "status": "pending", "received_at": datetime(2026, 5, 22, 8, 30)},
            {"id": uuid4(), "user_id": "user-1", "status": "processing", "received_at": datetime(2026, 5, 22, 8, 40)},
            {"id": uuid4(), "user_id": "user-2", "status": "pending", "received_at": datetime(2026, 5, 22, 8, 50)},
        ]
    )
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    packet = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T12:00:00+01:00",
        timezone_name="Europe/London",
    )

    assert packet["freshness"]["catch_up_needed"] is True
    assert packet["freshness"]["pending_outbox_count"] == 1
    assert packet["freshness"]["processing_outbox_count"] == 1
    assert packet["active_open_loops"][0]["title"] == "Waiting on Jordan contract"
    assert any(item["name"] == "Jordan" and item["kind"] == "person" for item in packet["entity_hints"])
    assert any(item["name"] == "Nina" and item["kind"] == "person" for item in packet["entity_hints"])
    assert all(item["summary"] != "User two summary" for item in packet["today_context"])
