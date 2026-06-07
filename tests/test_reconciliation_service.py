from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from core import reconciliation


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.candidates: dict[UUID, dict] = {}
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
            candidate = self.candidates[args[0]]
            candidate["reconciliation_instruction"] = args[1]
            candidate["merge_target_id"] = args[2]
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
            rows = [fact for fact in self.confirmed_facts.values() if fact["user_id"] == user_id and fact["status"] == "active"]
            if len(args) > 1:
                return rows[: args[1]]
            return rows
        if "FROM candidates" in query:
            user_id = args[0]
            return [candidate for candidate in self.candidates.values() if candidate["user_id"] == user_id and candidate["status"] == "pending"]
        return []

    async def fetchone(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            return self.confirmed_facts.get(args[0])
        return None


def _candidate(
    *,
    candidate_type: str = "fact",
    confidence: float = 0.9,
    needs_confirmation: bool = False,
    sensitivity: str | None = "low",
    companion_category: str | None = None,
    raw_evidence: str = "User is vegetarian.",
    created_at: datetime | None = None,
    time_overrides: dict | None = None,
) -> dict:
    candidate_id = uuid4()
    source_id = uuid4()
    content = {
        "schema_version": "v1",
        "item_type": candidate_type,
        "title": "user" if candidate_type == "fact" else "Item",
        "summary": "Summary",
        "salience": "high",
        "priority": None,
        "urgency": None,
        "importance": "high",
        "sensitivity": sensitivity,
        "time": {
            "due_date": None,
            "reminder_at": None,
            "date": None,
            "time": None,
            "duration": None,
            "follow_up_after_hours": None,
            "stale_after_hours": None,
            "expires_at": None,
            **(time_overrides or {}),
        },
        "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
        "lifecycle": {"follow_up_after_hours": None, "stale_after_hours": None, "expires_at": None},
        "evidence": {"raw_evidence": raw_evidence, "source_turn_refs": []},
        "metadata": {
            "companion_category": companion_category,
            "agent_item": {
                "fact_type": "preference" if candidate_type == "fact" else None,
                "content": "User is vegetarian.",
                "raw_evidence": raw_evidence,
                "is_past": False,
                "related_people": [],
                "related_projects": [],
                "companion_category": companion_category,
            },
        },
    }
    if candidate_type == "state":
        content["metadata"]["agent_item"]["current_focus"] = "Feeling stressed"
    if candidate_type == "thread":
        content["metadata"]["agent_item"]["related_projects"] = ["project"]
    return {
        "id": candidate_id,
        "user_id": "user-1",
        "source_id": source_id,
        "candidate_type": candidate_type,
        "content": content,
        "raw_evidence": raw_evidence,
        "confidence": confidence,
        "needs_confirmation": needs_confirmation,
        "status": "pending",
        "reconciliation_instruction": None,
        "merge_target_id": None,
        "created_at": created_at or datetime(2026, 5, 22, 12, 0),
    }


def _confirmed_fact(*, fact_type: str = "preference", domain: str = "profile") -> dict:
    fact_id = uuid4()
    return {
        "id": fact_id,
        "user_id": "user-1",
        "fact_type": fact_type,
        "domain": domain,
        "content": {
            "schema_version": "v1",
            "item_type": "fact",
            "summary": "Existing fact",
            "metadata": {"companion_category": None, "agent_item": {"fact_type": fact_type}},
            "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
            "evidence": {"raw_evidence": "existing", "source_turn_refs": []},
            "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
            "time": {},
            "sensitivity": "low",
        },
        "confidence": 0.8,
        "first_seen_at": datetime(2026, 5, 20, 12, 0),
        "last_seen_at": datetime(2026, 5, 20, 12, 0),
        "last_confirmed_at": datetime(2026, 5, 20, 12, 0),
        "source_ids": [uuid4()],
        "status": "active",
        "user_corrected": False,
        "correction_note": None,
        "expires_at": None,
    }


async def test_create_confirms_candidate_and_writes_timeline() -> None:
    db = FakeDatabase()
    candidate = _candidate()
    db.candidates[candidate["id"]] = candidate

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "CREATE",
                "target_id": None,
                "confidence_delta": 0.0,
                "reason": "new fact",
            }
        ],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert db.candidates[candidate["id"]]["status"] == "confirmed"
    assert len(db.confirmed_facts) == 1
    assert len(db.timeline_events) == 1


async def test_dismiss_marks_candidate_dismissed_without_confirmed_fact() -> None:
    db = FakeDatabase()
    candidate = _candidate()
    db.candidates[candidate["id"]] = candidate

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "DISMISS",
                "target_id": None,
                "confidence_delta": -0.2,
                "reason": "duplicate noise",
            }
        ],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert db.candidates[candidate["id"]]["status"] == "dismissed"
    assert not db.confirmed_facts
    assert not db.timeline_events


async def test_merge_updates_existing_fact_without_duplicate_creation() -> None:
    db = FakeDatabase()
    candidate = _candidate()
    db.candidates[candidate["id"]] = candidate
    fact = _confirmed_fact()
    db.confirmed_facts[fact["id"]] = fact

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "MERGE",
                "target_id": str(fact["id"]),
                "confidence_delta": 0.1,
                "reason": "same durable preference",
            }
        ],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert len(db.confirmed_facts) == 1
    assert candidate["source_id"] in db.confirmed_facts[fact["id"]]["source_ids"]
    assert db.confirmed_facts[fact["id"]]["last_seen_at"] == datetime(2026, 5, 22, 12, 0)
    assert len(db.timeline_events) == 1


async def test_update_replaces_content_and_writes_timeline() -> None:
    db = FakeDatabase()
    candidate = _candidate(raw_evidence="Updated evidence")
    candidate["content"]["summary"] = "Updated summary"
    db.candidates[candidate["id"]] = candidate
    fact = _confirmed_fact()
    db.confirmed_facts[fact["id"]] = fact

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "UPDATE",
                "target_id": str(fact["id"]),
                "confidence_delta": 0.05,
                "reason": "newer evidence",
            }
        ],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert db.confirmed_facts[fact["id"]]["content"]["summary"] == "Updated summary"
    assert candidate["source_id"] in db.confirmed_facts[fact["id"]]["source_ids"]
    assert len(db.timeline_events) == 1


async def test_needs_confirmation_does_not_auto_confirm() -> None:
    db = FakeDatabase()
    candidate = _candidate(needs_confirmation=True)
    db.candidates[candidate["id"]] = candidate

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "CREATE",
                "target_id": None,
                "confidence_delta": 0.0,
                "reason": "candidate needs confirmation",
            }
        ],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert db.candidates[candidate["id"]]["status"] == "pending"
    assert not db.confirmed_facts


async def test_explicit_high_sensitivity_boundary_can_auto_confirm() -> None:
    db = FakeDatabase()
    candidate = _candidate(
        sensitivity="high",
        companion_category="avoid_topic",
        raw_evidence="Please don't bring up the fertility stuff unless I mention it first.",
    )
    candidate["content"]["metadata"]["agent_item"]["fact_type"] = "constraint"
    candidate["content"]["summary"] = "User prefers not to discuss fertility topics unless they bring it up first."
    db.candidates[candidate["id"]] = candidate

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "CREATE",
                "target_id": None,
                "confidence_delta": 0.0,
                "reason": "explicit high sensitivity boundary",
            }
        ],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert db.candidates[candidate["id"]]["status"] == "confirmed"
    assert len(db.confirmed_facts) == 1


async def test_suspicious_temporal_candidate_does_not_auto_confirm() -> None:
    db = FakeDatabase()
    candidate = _candidate(
        candidate_type="task",
        time_overrides={"due_date": "2024-04-28T12:00:00Z"},
        raw_evidence="I need to send the revised proposal tomorrow morning.",
    )
    candidate["content"]["metadata"]["agent_item"]["title"] = "Send revised proposal"
    db.candidates[candidate["id"]] = candidate

    await reconciliation.apply_reconciliation_results(
        db,
        candidates=[candidate],
        instructions=[
            {
                "candidate_id": str(candidate["id"]),
                "instruction": "CREATE",
                "target_id": None,
                "confidence_delta": 0.0,
                "reason": "looks valid but date is suspicious",
            }
        ],
        now=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert db.candidates[candidate["id"]]["status"] == "pending"
    assert not db.confirmed_facts


async def test_fetch_active_confirmed_facts_limits_results() -> None:
    db = FakeDatabase()
    for _ in range(12):
        fact = _confirmed_fact()
        db.confirmed_facts[fact["id"]] = fact
    rows = await reconciliation.fetch_active_confirmed_facts(db, user_id="user-1", limit=10)
    assert len(rows) == 10
