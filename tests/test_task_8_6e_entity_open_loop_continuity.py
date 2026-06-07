from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from core import recall as recall_service
from core import reconciliation, serving


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.candidates: dict[UUID, dict] = {}
        self.confirmed_facts: dict[UUID, dict] = {}
        self.timeline_events: list[dict] = []
        self.session_summaries: list[dict] = []
        self.outbox_rows: dict[UUID, dict] = {}
        self.source_archive_rows: dict[UUID, dict] = {}

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
            }
            return "INSERT 1"
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
        if "UPDATE candidates" in query and "reconciliation_instruction" in query:
            self.candidates[args[0]]["reconciliation_instruction"] = args[1]
            self.candidates[args[0]]["merge_target_id"] = args[2]
            return "UPDATE 1"
        if "UPDATE candidates" in query and "status = 'dismissed'" in query:
            self.candidates[args[0]]["status"] = "dismissed"
            return "UPDATE 1"
        if "UPDATE candidates" in query and "status = 'confirmed'" in query:
            self.candidates[args[0]]["status"] = "confirmed"
            return "UPDATE 1"
        if "UPDATE confirmed_facts" in query:
            fact = self.confirmed_facts[args[0]]
            fact["content"] = args[1]
            fact["confidence"] = args[2]
            fact["last_seen_at"] = args[3]
            fact["last_confirmed_at"] = args[4]
            fact["source_ids"] = args[5]
            fact["expires_at"] = args[6]
            return "UPDATE 1"
        return "OK"

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            user_id = args[0]
            rows = [row for row in self.confirmed_facts.values() if row["user_id"] == user_id and row["status"] == "active"]
            if len(args) > 1:
                return rows[: args[1]]
            return rows
        if "FROM candidates" in query:
            user_id = args[0]
            return [row for row in self.candidates.values() if row["user_id"] == user_id and row["status"] == "pending"]
        if "FROM timeline_events" in query:
            user_id = args[0]
            return [row for row in self.timeline_events if row["user_id"] == user_id]
        if "FROM session_summaries" in query:
            rows = [row for row in self.session_summaries if row["user_id"] == args[0]]
            rows.sort(key=lambda row: row["occurred_at"], reverse=True)
            if len(args) > 1:
                return rows[: args[1]]
            return rows
        if "FROM outbox" in query:
            user_id = args[0]
            rows = [row for row in self.outbox_rows.values() if row["user_id"] == user_id]
            rows.sort(key=lambda row: row["received_at"], reverse=True)
            return rows
        if "FROM source_archive" in query:
            user_id = args[0]
            rows = [row for row in self.source_archive_rows.values() if row["user_id"] == user_id]
            rows.sort(key=lambda row: row["captured_at"], reverse=True)
            return rows
        return []

    async def fetchone(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            return self.confirmed_facts.get(args[0])
        return None


def _candidate(
    *,
    user_id: str = "user-1",
    candidate_type: str = "thread",
    title: str = "Waiting on Jordan contract",
    summary: str = "Still waiting on Jordan to send the contract.",
    people: list[str] | None = None,
    projects: list[str] | None = None,
    topics: list[str] | None = None,
    open_loop_status: str | None = None,
    companion_category: str | None = None,
    confidence: float = 0.92,
) -> dict:
    source_id = uuid4()
    content = {
        "schema_version": "v1",
        "item_type": candidate_type,
        "title": title,
        "summary": summary,
        "salience": "high",
        "priority": "high",
        "urgency": "high",
        "importance": "high",
        "sensitivity": "low",
        "time": {
            "due_date": None,
            "reminder_at": None,
            "date": None,
            "time": None,
            "duration": None,
            "follow_up_after_hours": 24,
            "stale_after_hours": 168,
            "expires_at": None,
        },
        "links": {
            "people": people or [],
            "projects": projects or [],
            "topics": topics or [],
            "related_facts": [],
            "related_threads": [],
        },
        "lifecycle": {
            "follow_up_after_hours": 24,
            "stale_after_hours": 168,
            "expires_at": None,
        },
        "evidence": {"raw_evidence": summary, "source_turn_refs": []},
        "metadata": {
            "companion_category": companion_category,
            "open_loop_status": open_loop_status or ("active" if candidate_type == "thread" else None),
            "last_status": "Still unresolved.",
            "follow_up_question": "Any update?",
            "involves": people or projects or [],
            "agent_item": {
                "fact_type": "relationship" if candidate_type == "fact" else None,
                "related_people": people or [],
                "related_projects": projects or [],
                "related_topics": topics or [],
                "open_loop_status": open_loop_status,
                "last_status": "Still unresolved.",
            },
        },
    }
    return {
        "id": uuid4(),
        "user_id": user_id,
        "source_id": source_id,
        "candidate_type": candidate_type,
        "content": content,
        "raw_evidence": summary,
        "confidence": confidence,
        "needs_confirmation": False,
        "status": "pending",
        "reconciliation_instruction": None,
        "merge_target_id": None,
        "created_at": datetime(2026, 5, 22, 12, 0),
    }


def _fact(
    *,
    user_id: str = "user-1",
    fact_type: str = "thread",
    title: str = "Waiting on Jordan contract",
    summary: str = "Still waiting on Jordan to send the contract.",
    people: list[str] | None = None,
    projects: list[str] | None = None,
    topics: list[str] | None = None,
    status: str = "active",
    open_loop_status: str | None = "active",
    companion_category: str | None = None,
    last_seen_at: datetime | None = None,
) -> dict:
    return {
        "id": uuid4(),
        "user_id": user_id,
        "fact_type": fact_type,
        "domain": "people" if people else "workstreams" if projects else "profile",
        "content": {
            "schema_version": "v1",
            "item_type": "thread" if fact_type == "thread" else "fact",
            "title": title,
            "summary": summary,
            "salience": "high",
            "priority": "high",
            "urgency": "high",
            "importance": "high",
            "sensitivity": "low",
            "time": {},
            "links": {
                "people": people or [],
                "projects": projects or [],
                "topics": topics or [],
                "related_facts": [],
                "related_threads": [],
            },
            "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": 24},
            "evidence": {"raw_evidence": summary, "source_turn_refs": []},
            "metadata": {
                "companion_category": companion_category,
                "open_loop_status": open_loop_status,
                "last_status": "Still unresolved." if open_loop_status in {"active", "unresolved", None} else "Resolved.",
                "follow_up_question": "Any update?",
                "agent_item": {"open_loop_status": open_loop_status},
            },
        },
        "confidence": 0.9,
        "first_seen_at": datetime(2026, 5, 20, 12, 0),
        "last_seen_at": last_seen_at or datetime(2026, 5, 22, 12, 0),
        "last_confirmed_at": last_seen_at or datetime(2026, 5, 22, 12, 0),
        "source_ids": [uuid4()],
        "status": status,
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }


def _packet_stub(**kwargs):
    return {
        "session_instructions": "Use packet privately.",
        "relevant_topics": [],
        "worth_attention": [],
        "suggested_focus": "Current conversation",
        "tone_note": "Grounded.",
        "avoid": [],
        "stale_warnings": [],
    }


async def test_candidate_links_people_and_projects_preserved_into_confirmed_fact() -> None:
    db = FakeDatabase()
    candidate = _candidate(candidate_type="task", title="Call Ashley", summary="Call Ashley about Atlas.", people=["Ashley"], projects=["Atlas"], topics=["check-in"])
    db.candidates[candidate["id"]] = candidate

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[{"candidate_id": str(candidate["id"]), "instruction": "CREATE", "target_id": None, "confidence_delta": 0.0, "reason": "new"}],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["content"]["links"]["people"] == ["Ashley"]
    assert fact["content"]["links"]["projects"] == ["Atlas"]
    assert fact["content"]["links"]["topics"] == ["check-in"]


async def test_same_name_people_with_different_context_are_not_blindly_merged(monkeypatch) -> None:
    db = FakeDatabase()
    existing = _fact(fact_type="relationship", title="Ashley", summary="Ashley from family context.", people=["Ashley"], projects=["family"])
    db.confirmed_facts[existing["id"]] = existing
    candidate = _candidate(candidate_type="fact", title="Ashley", summary="Ashley from work context.", people=["Ashley"], projects=["work"])
    db.candidates[candidate["id"]] = candidate

    def fake_run(*, new_candidates, existing_facts):
        return [{"candidate_id": new_candidates[0]["id"], "instruction": "MERGE", "target_id": str(existing_facts[0]["id"]), "confidence_delta": 0.0, "reason": "same name"}]

    monkeypatch.setattr("core.reconciliation.reconciliation_agent.run", fake_run)
    instructions = await reconciliation.reconcile_candidates(db, candidates=[candidate])

    assert instructions[0]["instruction"] == "CREATE"
    assert instructions[0]["target_id"] is None


async def test_ambiguous_same_name_match_remains_unmerged_after_apply(monkeypatch) -> None:
    db = FakeDatabase()
    existing = _fact(fact_type="relationship", title="Ashley", summary="Ashley from family context.", people=["Ashley"], projects=["family"])
    db.confirmed_facts[existing["id"]] = existing
    candidate = _candidate(candidate_type="fact", title="Ashley", summary="Ashley from work context.", people=["Ashley"], projects=["work"])
    db.candidates[candidate["id"]] = candidate

    def fake_run(*, new_candidates, existing_facts):
        return [{"candidate_id": new_candidates[0]["id"], "instruction": "MERGE", "target_id": str(existing_facts[0]["id"]), "confidence_delta": 0.0, "reason": "same name"}]

    monkeypatch.setattr("core.reconciliation.reconciliation_agent.run", fake_run)
    instructions = await reconciliation.reconcile_candidates(db, candidates=[candidate])
    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=instructions,
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert len(db.confirmed_facts) == 2


async def test_startup_packet_surfaces_entity_hints_and_active_open_loops(monkeypatch) -> None:
    db = FakeDatabase()
    loop_fact = _fact(people=["Jordan"], projects=["Atlas"], topics=["contract"], title="Waiting on Jordan contract")
    nina_fact = _fact(fact_type="relationship", title="Nina", summary="Nina matters.", people=["Nina"])
    db.confirmed_facts[loop_fact["id"]] = loop_fact
    db.confirmed_facts[nina_fact["id"]] = nina_fact
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    packet = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T12:00:00+01:00",
        timezone_name="Europe/London",
    )

    assert packet["active_open_loops"]
    assert packet["active_open_loops"][0]["linked_people"] == ["Jordan"]
    assert any(item["name"] == "Jordan" and item["kind"] == "person" for item in packet["entity_hints"])
    assert any(item["name"] == "Atlas" and item["kind"] == "project" for item in packet["entity_hints"])
    assert any(item["name"] == "contract" and item["kind"] == "topic" for item in packet["entity_hints"])


async def test_resolved_dismissed_and_stale_open_loops_do_not_surface_as_active(monkeypatch) -> None:
    db = FakeDatabase()
    active = _fact(title="Active loop", people=["Jordan"])
    resolved = _fact(title="Resolved loop", people=["Jordan"], open_loop_status="resolved")
    dismissed = _fact(title="Dismissed loop", people=["Jordan"], status="dismissed")
    stale = _fact(title="Stale loop", people=["Jordan"], open_loop_status="stale")
    db.confirmed_facts[active["id"]] = active
    db.confirmed_facts[resolved["id"]] = resolved
    db.confirmed_facts[dismissed["id"]] = dismissed
    db.confirmed_facts[stale["id"]] = stale
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    packet = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T12:00:00+01:00",
        timezone_name="Europe/London",
    )

    titles = [item["title"] for item in packet["active_open_loops"]]
    assert "Active loop" in titles
    assert "Resolved loop" not in titles
    assert "Dismissed loop" not in titles
    assert "Stale loop" not in titles


async def test_recall_continuity_lane_returns_active_open_loop_with_entity_metadata() -> None:
    db = FakeDatabase()
    fact = _fact(title="Waiting on Jordan contract", people=["Jordan"], projects=["Atlas"], topics=["contract"])
    db.confirmed_facts[fact["id"]] = fact
    outbox_id = fact["source_ids"][0]
    db.outbox_rows[outbox_id] = {
        "id": outbox_id,
        "user_id": "user-1",
        "source_type": "chat",
        "raw_content": "preview",
        "received_at": datetime(2026, 5, 22, 12, 0),
        "status": "done",
        "retry_count": 0,
        "source_archive_id": None,
        "metadata": {},
    }

    result = await recall_service.recall(db, user_id="user-1", query="what am I waiting on with Jordan", recall_type="hybrid", limit=5)

    continuity = next(item for item in result["items"] if item["type"] == "continuity_note")
    assert continuity["metadata"]["open_loop_status"] == "active"
    assert continuity["metadata"]["linked_people"] == ["Jordan"]
    assert continuity["metadata"]["linked_projects"] == ["Atlas"]


async def test_user_isolation_and_avoid_boundary_do_not_leak(monkeypatch) -> None:
    db = FakeDatabase()
    user_loop = _fact(user_id="user-1", title="User one loop", people=["Avery"], projects=["Apollo"])
    avoid_fact = _fact(user_id="user-1", fact_type="identity", title="boundary", summary="Avoid fertility topic unless user raises it.", projects=["fertility"], companion_category="avoid_topic")
    other_loop = _fact(user_id="user-2", title="Other loop", people=["Mallory"], projects=["Secret"])
    db.confirmed_facts[user_loop["id"]] = user_loop
    db.confirmed_facts[avoid_fact["id"]] = avoid_fact
    db.confirmed_facts[other_loop["id"]] = other_loop
    monkeypatch.setattr("core.serving.surfacing_agent.run", _packet_stub)

    packet = await serving.build_instruction_packet(
        db,
        user_id="user-1",
        current_datetime="2026-05-22T12:00:00+01:00",
        timezone_name="Europe/London",
    )

    assert any(item["name"] == "Avery" for item in packet["entity_hints"])
    assert all(item["name"] != "Mallory" for item in packet["entity_hints"])
    assert all(item["name"] != "fertility" for item in packet["entity_hints"])
    assert all(loop["title"] != "Other loop" for loop in packet["active_open_loops"])
