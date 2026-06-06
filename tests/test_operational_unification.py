from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from agent_contract import AgentOutput
from core.candidates import candidate_records_from_outputs
from core.items import (
    due_tasks,
    habit_completion_status,
    open_threads,
    pending_reminders,
    record_habit_completion,
    resolve_thread,
    todays_schedule,
    update_action,
)
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
                "structured_content": args[14],
                "source_type": args[15],
                "primary_source_id": args[16],
                "who_said_it": args[17],
                "original_text": args[18],
                "channel": args[19],
                "conversation_id": args[20],
                "created_from": args[21],
                "provenance": args[22],
                "starts_at": args[23],
                "ends_at": args[24],
                "due_at": args[25],
                "remind_at": args[26],
                "timezone": args[27],
                "recurrence_rule": args[28],
                "completed_at": args[29],
                "cancelled_at": args[30],
                "priority": args[31],
                "follow_up_needed": args[32],
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
            row = self.confirmed_facts[args[0]]
            row["content"] = args[1]
            if len(args) > 2:
                row["structured_content"] = args[2]
            return "UPDATE 1"
        return "OK"

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            user_id = args[0]
            return [row for row in self.confirmed_facts.values() if row["user_id"] == user_id and row["status"] == "active"]
        if "FROM candidates" in query:
            user_id = args[0]
            return [row for row in self.candidates.values() if row["user_id"] == user_id and row["status"] == "pending"]
        if "FROM timeline_events" in query:
            user_id = args[0]
            return [row for row in self.timeline_events if row["user_id"] == user_id]
        return []

    async def fetchone(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            return self.confirmed_facts.get(args[0])
        return None


def _candidate_from_output(
    *,
    source_id: UUID | None = None,
    source_type: str,
    who_said_it: str = "user",
    conversation_id: str | None = None,
    original_text: str,
    output: AgentOutput,
) -> dict:
    records = candidate_records_from_outputs(
        user_id="user-1",
        source_id=source_id or uuid4(),
        outputs=[output],
        created_at=datetime(2026, 6, 6, 9, 0),
        source_context={
            "source_type": source_type,
            "who_said_it": who_said_it,
            "channel": source_type,
            "conversation_id": conversation_id,
            "original_text": original_text,
            "created_from": {"pipeline": "test"},
        },
    )
    return records[0]


async def _reconcile_create(db: FakeDatabase, candidate: dict) -> None:
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
                "reason": "test create",
            }
        ],
        now=datetime(2026, 6, 6, 9, 0),
    )


def _task_output(item: dict) -> AgentOutput:
    return AgentOutput(agent="task_agent", status="success", items=[item], errors=[], confidence_notes="ok")


def _event_output(item: dict) -> AgentOutput:
    return AgentOutput(agent="event_agent", status="success", items=[item], errors=[], confidence_notes="ok")


def _thread_output(item: dict) -> AgentOutput:
    return AgentOutput(agent="thread_agent", status="success", items=[item], errors=[], confidence_notes="ok")


async def test_sophie_explicit_reminder_confirms_and_queries() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="sophie_chat",
        original_text="remind me tomorrow at 9 to call the dentist",
        output=_task_output(
            {
                "title": "Call the dentist",
                "description": "Call the dentist",
                "due_date": None,
                "reminder_at": "2026-06-07T09:00:00+01:00",
                "priority": "high",
                "urgency": "high",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "high",
                "raw_evidence": "remind me tomorrow at 9 to call the dentist",
                "confidence": 0.98,
                "related_people": [],
                "related_projects": [],
            }
        ),
    )
    await _reconcile_create(db, candidate)

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["structured_content"]["kind"] == "reminder"
    assert fact["remind_at"] is not None
    reminders = await pending_reminders(db, user_id="user-1")
    assert reminders["items"][0]["title"] == "Call the dentist"


async def test_sophie_explicit_task_confirms_and_due_query_uses_source_type() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="sophie_chat",
        original_text="add a task to send Ashley the proposal tonight",
        output=_task_output(
            {
                "title": "Send Ashley the proposal",
                "description": "Send Ashley the proposal tonight",
                "due_date": "2026-06-06T20:00:00+01:00",
                "reminder_at": None,
                "priority": "high",
                "urgency": "high",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "high",
                "raw_evidence": "add a task to send Ashley the proposal tonight",
                "confidence": 0.98,
                "related_people": ["Ashley"],
                "related_projects": ["proposal"],
            }
        ),
    )
    await _reconcile_create(db, candidate)

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "task"
    assert fact["due_at"] is not None
    assert fact["source_type"] == "sophie_chat"
    tasks = await due_tasks(db, user_id="user-1", now="2026-06-06T21:00:00+01:00")
    assert tasks["items"][0]["title"] == "Send Ashley the proposal"


async def test_sophie_inferred_task_stays_candidate_with_confidence_and_original_text() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="sophie_chat",
        original_text="I probably need to send Ashley the proposal tonight",
        output=_task_output(
            {
                "title": "Send Ashley the proposal",
                "description": "Likely should send Ashley the proposal tonight",
                "due_date": "2026-06-06T20:00:00+01:00",
                "reminder_at": None,
                "priority": "medium",
                "urgency": "medium",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": True,
                "salience": "medium",
                "raw_evidence": "I probably need to send Ashley the proposal tonight",
                "confidence": 0.72,
                "related_people": ["Ashley"],
                "related_projects": ["proposal"],
            }
        ),
    )
    await _reconcile_create(db, candidate)

    assert db.candidates[candidate["id"]]["status"] == "pending"
    assert db.confirmed_facts == {}
    assert db.candidates[candidate["id"]]["confidence"] == 0.72
    assert db.candidates[candidate["id"]]["original_text"] == "I probably need to send Ashley the proposal tonight"


async def test_calendar_event_confirms_and_appears_in_schedule() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="sophie_chat",
        original_text="I have a call with Peter next Thursday at 2",
        output=_event_output(
            {
                "title": "Call with Peter",
                "date": "2026-06-11",
                "time": "2026-06-11T14:00:00+01:00",
                "starts_at": "2026-06-11T14:00:00+01:00",
                "ends_at": "2026-06-11T15:00:00+01:00",
                "duration": None,
                "location": None,
                "attendees": ["Peter"],
                "is_invitation": False,
                "needs_confirmation": False,
                "is_past": False,
                "urgency": "medium",
                "salience": "medium",
                "sensitivity": "low",
                "related_people": ["Peter"],
                "related_projects": [],
                "raw_evidence": "I have a call with Peter next Thursday at 2",
                "confidence": 0.95,
            }
        ),
    )
    await _reconcile_create(db, candidate)

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["starts_at"] is not None
    schedule = await todays_schedule(db, user_id="user-1", day="2026-06-11")
    assert schedule["items"][0]["title"] == "Call with Peter"


async def test_whatsapp_task_candidate_preserves_provenance() -> None:
    candidate = _candidate_from_output(
        source_type="whatsapp",
        who_said_it="Ashley",
        conversation_id="wa-thread-7",
        original_text="Can you send me the revised proposal tonight?",
        output=_task_output(
            {
                "title": "Send revised proposal",
                "description": "Ashley asked for the revised proposal tonight",
                "due_date": "2026-06-06T20:00:00+01:00",
                "reminder_at": None,
                "priority": "high",
                "urgency": "high",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": True,
                "salience": "high",
                "raw_evidence": "Can you send me the revised proposal tonight?",
                "confidence": 0.88,
                "related_people": ["Ashley"],
                "related_projects": ["proposal"],
            }
        ),
    )

    assert candidate["source_type"] == "whatsapp"
    assert candidate["who_said_it"] == "Ashley"
    assert candidate["conversation_id"] == "wa-thread-7"
    assert candidate["original_text"] == "Can you send me the revised proposal tonight?"


async def test_habit_creation_and_completion_status() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="sophie_chat",
        original_text="track 10k steps daily as a habit",
        output=_task_output(
            {
                "title": "10k steps",
                "description": "Track 10k steps daily as a habit",
                "due_date": None,
                "reminder_at": None,
                "priority": "medium",
                "urgency": "medium",
                "is_habit": True,
                "recurrence": "daily",
                "cadence": "daily",
                "target_value": 10000,
                "target_unit": "steps",
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "medium",
                "raw_evidence": "track 10k steps daily as a habit",
                "confidence": 0.97,
                "related_people": [],
                "related_projects": [],
            }
        ),
    )
    await _reconcile_create(db, candidate)

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "habit"
    assert fact["status"] == "active"
    assert fact["structured_content"]["habit"]["cadence"] == "daily"

    await record_habit_completion(
        db,
        user_id="user-1",
        item_id=fact["id"],
        completed_at="2026-06-06T18:00:00+01:00",
    )
    assert db.timeline_events[-1]["event_type"] == "habit_completed"
    status = await habit_completion_status(db, user_id="user-1", day="2026-06-06")
    assert status["items"][0]["completion_status"] == "habit_completed"


async def test_open_thread_represents_loop_and_can_be_resolved() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="sophie_chat",
        original_text="we still need to decide how V3 handles reminders",
        output=_thread_output(
            {
                "title": "V3 reminder handling decision",
                "summary": "We still need to decide how V3 handles reminders.",
                "related_people": [],
                "related_projects": ["V3 reminders"],
                "related_topics": ["reminders"],
                "related_facts": [],
                "related_threads": [],
                "follow_up_after_hours": 24,
                "open_loop_status": "active",
                "needs_confirmation": False,
                "raw_evidence": "we still need to decide how V3 handles reminders",
                "confidence": 0.91,
            }
        ),
    )
    await _reconcile_create(db, candidate)

    fact = next(iter(db.confirmed_facts.values()))
    assert fact["fact_type"] == "thread"
    assert fact["follow_up_needed"] is True
    open_loop_items = await open_threads(db, user_id="user-1")
    assert open_loop_items["items"][0]["title"] == "V3 reminder handling decision"

    await resolve_thread(db, user_id="user-1", item_id=fact["id"])
    assert db.timeline_events[-1]["event_type"] == "thread_resolved"


async def test_task_completion_writes_task_completed_event() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="sophie_chat",
        original_text="add a task to send Ashley the proposal tonight",
        output=_task_output(
            {
                "title": "Send Ashley the proposal",
                "description": "Send Ashley the proposal tonight",
                "due_date": "2026-06-06T20:00:00+01:00",
                "reminder_at": None,
                "priority": "high",
                "urgency": "high",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "high",
                "raw_evidence": "add a task to send Ashley the proposal tonight",
                "confidence": 0.98,
                "related_people": ["Ashley"],
                "related_projects": ["proposal"],
            }
        ),
    )
    await _reconcile_create(db, candidate)
    fact = next(iter(db.confirmed_facts.values()))

    await update_action(
        db,
        item_id=fact["id"],
        user_id="user-1",
        status="completed",
        title=None,
        summary=None,
        due_at=None,
        priority=None,
    )
    assert fact["status"] == "historical"
    assert db.timeline_events[-1]["event_type"] == "task_completed"


async def test_provenance_survives_candidate_and_confirmed_fact() -> None:
    db = FakeDatabase()
    candidate = _candidate_from_output(
        source_type="whatsapp",
        who_said_it="Peter",
        conversation_id="wa-thread-11",
        original_text="I have a call with Peter next Thursday at 2",
        output=_event_output(
            {
                "title": "Call with Peter",
                "date": "2026-06-11",
                "time": "2026-06-11T14:00:00+01:00",
                "starts_at": "2026-06-11T14:00:00+01:00",
                "ends_at": "2026-06-11T15:00:00+01:00",
                "duration": None,
                "location": None,
                "attendees": ["Peter"],
                "is_invitation": False,
                "needs_confirmation": False,
                "is_past": False,
                "urgency": "medium",
                "salience": "medium",
                "sensitivity": "low",
                "related_people": ["Peter"],
                "related_projects": [],
                "raw_evidence": "I have a call with Peter next Thursday at 2",
                "confidence": 0.95,
            }
        ),
    )

    assert candidate["source_type"] == "whatsapp"
    assert candidate["who_said_it"] == "Peter"
    assert candidate["original_text"] == "I have a call with Peter next Thursday at 2"
    assert candidate["created_from"]["pipeline"] == "test"

    await _reconcile_create(db, candidate)
    fact = next(iter(db.confirmed_facts.values()))
    assert fact["source_type"] == "whatsapp"
    assert fact["who_said_it"] == "Peter"
    assert fact["original_text"] == "I have a call with Peter next Thursday at 2"
    assert fact["created_from"]["pipeline"] == "test"


async def test_operational_flow_smoke_end_to_end() -> None:
    db = FakeDatabase()

    reminder = _candidate_from_output(
        source_type="sophie_chat",
        original_text="remind me tomorrow at 9 to call the dentist",
        output=_task_output(
            {
                "title": "Call the dentist",
                "description": "Call the dentist",
                "due_date": None,
                "reminder_at": "2026-06-07T09:00:00+01:00",
                "priority": "high",
                "urgency": "high",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "high",
                "raw_evidence": "remind me tomorrow at 9 to call the dentist",
                "confidence": 0.98,
                "related_people": [],
                "related_projects": [],
            }
        ),
    )
    await _reconcile_create(db, reminder)

    task = _candidate_from_output(
        source_type="sophie_chat",
        original_text="add a task to send Ashley the proposal tonight",
        output=_task_output(
            {
                "title": "Send Ashley the proposal",
                "description": "Send Ashley the proposal tonight",
                "due_date": "2026-06-06T20:00:00+01:00",
                "reminder_at": None,
                "priority": "high",
                "urgency": "high",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "high",
                "raw_evidence": "add a task to send Ashley the proposal tonight",
                "confidence": 0.98,
                "related_people": ["Ashley"],
                "related_projects": ["proposal"],
            }
        ),
    )
    await _reconcile_create(db, task)

    whatsapp = _candidate_from_output(
        source_type="whatsapp",
        who_said_it="Ashley",
        conversation_id="wa-thread-88",
        original_text="Please remind me to send the revised proposal tonight",
        output=_task_output(
            {
                "title": "Send revised proposal",
                "description": "Ashley wants the revised proposal tonight",
                "due_date": None,
                "reminder_at": "2026-06-06T19:00:00+01:00",
                "priority": "high",
                "urgency": "high",
                "is_habit": False,
                "recurrence": None,
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "high",
                "raw_evidence": "Please remind me to send the revised proposal tonight",
                "confidence": 0.93,
                "related_people": ["Ashley"],
                "related_projects": ["proposal"],
            }
        ),
    )
    await _reconcile_create(db, whatsapp)

    habit = _candidate_from_output(
        source_type="sophie_chat",
        original_text="track 10k steps daily as a habit",
        output=_task_output(
            {
                "title": "10k steps",
                "description": "Track 10k steps daily as a habit",
                "due_date": None,
                "reminder_at": None,
                "priority": "medium",
                "urgency": "medium",
                "is_habit": True,
                "recurrence": "daily",
                "cadence": "daily",
                "target_value": 10000,
                "target_unit": "steps",
                "waiting_on": None,
                "needs_confirmation": False,
                "salience": "medium",
                "raw_evidence": "track 10k steps daily as a habit",
                "confidence": 0.97,
                "related_people": [],
                "related_projects": [],
            }
        ),
    )
    await _reconcile_create(db, habit)

    thread = _candidate_from_output(
        source_type="sophie_chat",
        original_text="we still need to decide how V3 handles reminders",
        output=_thread_output(
            {
                "title": "V3 reminder handling decision",
                "summary": "We still need to decide how V3 handles reminders.",
                "related_people": [],
                "related_projects": ["V3 reminders"],
                "related_topics": ["reminders"],
                "related_facts": [],
                "related_threads": [],
                "follow_up_after_hours": 24,
                "open_loop_status": "active",
                "needs_confirmation": False,
                "raw_evidence": "we still need to decide how V3 handles reminders",
                "confidence": 0.91,
            }
        ),
    )
    await _reconcile_create(db, thread)

    facts = list(db.confirmed_facts.values())
    habit_fact = next(fact for fact in facts if fact["fact_type"] == "habit")
    await record_habit_completion(
        db,
        user_id="user-1",
        item_id=habit_fact["id"],
        completed_at="2026-06-06T18:00:00+01:00",
    )

    reminder_items = await pending_reminders(db, user_id="user-1")
    due_task_items = await due_tasks(db, user_id="user-1", now="2026-06-06T21:00:00+01:00")
    habit_items = await habit_completion_status(db, user_id="user-1", day="2026-06-06")
    thread_items = await open_threads(db, user_id="user-1")

    assert len(reminder_items["items"]) == 2
    assert any(item["provenance"]["source_type"] == "whatsapp" for item in reminder_items["items"])
    assert due_task_items["items"][0]["title"] == "Send Ashley the proposal"
    assert habit_items["items"][0]["completion_status"] == "habit_completed"
    assert thread_items["items"][0]["metadata"]["follow_up_needed"] is True
