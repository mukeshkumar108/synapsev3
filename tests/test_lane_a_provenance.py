from __future__ import annotations

import pytest
import asyncpg
from uuid import uuid4
from datetime import datetime, timezone

from agent_contract import AgentInput, Participant, TranscriptTurn
from agents import fact_agent, reconciliation_agent
from core.db import Database
from core import reconciliation
from core import pipeline_runner
from core.config import get_settings

class MockLLMClient:
    def __init__(self, response):
        self.response = response

    def generate_json(self, **_: object):
        return self.response

def _agent_input(raw_content: str, participants=None, interaction_mode="real_life") -> AgentInput:
    if participants is None:
        participants = [
            Participant(id="user", name="User", role="user"),
            Participant(id="sophie", name="Sophie", role="assistant")
        ]
    return AgentInput(
        user_id="test-user",
        source_type="chat",
        raw_content=raw_content,
        interaction_mode=interaction_mode,
        participants=participants,
        context={"current_date": "2026-05-22"},
    )


async def _require_db() -> None:
    try:
        conn = await asyncpg.connect(get_settings().get_database_url())
    except Exception as exc:
        pytest.skip(f"Postgres not available for DB-backed provenance test: {exc}")
    else:
        await conn.close()

def test_fact_agent_v2_provenance_direct_user_claim() -> None:
    raw_content = "[Turn 0] User: I have a peanut allergy."
    output = fact_agent.run(
        _agent_input(raw_content),
        llm_client=MockLLMClient({
            "items": [
                {
                    "subject": "user",
                    "fact_type": "background",
                    "content": "User has a peanut allergy.",
                    "companion_category": None,
                    "about_user": True,
                    "person_name": None,
                    "related_people": [],
                    "related_projects": [],
                    "salience": "high",
                    "sensitivity": "high",
                    "needs_confirmation": False,
                    "claimed_by_entity_id": "user",
                    "subject_entity_id": "user",
                    "claim_type": "direct",
                    "evidence_turn_index": 0,
                    "raw_evidence": "I have a peanut allergy.",
                    "confidence": 0.99
                }
            ]
        })
    )
    assert output.status == "success"
    item = output.items[0]
    assert item["claimed_by_entity_id"] == "user"
    assert item["subject_entity_id"] == "user"
    assert item["claim_type"] == "direct"

def test_fact_agent_v2_provenance_reported_speech() -> None:
    raw_content = "[Turn 0] User: Nina says the car is broken."
    output = fact_agent.run(
        _agent_input(raw_content),
        llm_client=MockLLMClient({
            "items": [
                {
                    "subject": "Nina",
                    "fact_type": "trait",
                    "content": "The car is broken.",
                    "companion_category": None,
                    "about_user": False,
                    "person_name": "Nina",
                    "related_people": ["Nina"],
                    "related_projects": ["car"],
                    "salience": "medium",
                    "sensitivity": "low",
                    "needs_confirmation": True,
                    "claimed_by_entity_id": "user",
                    "subject_entity_id": "nina-uuid",
                    "claim_type": "reported",
                    "evidence_turn_index": 0,
                    "raw_evidence": "Nina says the car is broken.",
                    "confidence": 0.90
                }
            ]
        })
    )
    assert output.status == "success"
    item = output.items[0]
    assert item["claimed_by_entity_id"] == "user"
    assert item["subject_entity_id"] == "nina-uuid"
    assert item["claim_type"] == "reported"

def test_fact_agent_v2_provenance_assistant_interpretation_real_life() -> None:
    raw_content = "[Turn 0] Sophie: You seem tired. [Turn 1] User: Maybe a little."
    output = fact_agent.run(
        _agent_input(raw_content),
        llm_client=MockLLMClient({
            "items": [
                {
                    "subject": "user",
                    "fact_type": "trait",
                    "content": "User seems tired.",
                    "companion_category": None,
                    "about_user": True,
                    "person_name": None,
                    "related_people": [],
                    "related_projects": [],
                    "salience": "medium",
                    "sensitivity": "low",
                    "needs_confirmation": True,
                    "claimed_by_entity_id": "sophie",
                    "subject_entity_id": "user",
                    "claim_type": "interpretation",
                    "evidence_turn_index": 0,
                    "raw_evidence": "You seem tired.",
                    "confidence": 0.85
                }
            ]
        })
    )
    assert output.status == "success"
    item = output.items[0]
    assert item["claimed_by_entity_id"] == "sophie"
    assert item["claim_type"] == "interpretation"

@pytest.mark.anyio
async def test_reconciliation_upgrades_interpretation_on_user_confirmation() -> None:
    await _require_db()
    db = Database()
    try:
        user_id = "test-user-" + str(uuid4())
        source_id = uuid4()
        
        # 1. Create an existing 'interpretation' fact
        fact_id = uuid4()
        await db.execute("""
            INSERT INTO confirmed_facts (
                id, user_id, fact_type, domain, content, confidence,
                first_seen_at, last_seen_at, last_confirmed_at, source_ids,
                status, claim_type, subject_entity_id, claimed_by_entity_id
            ) VALUES ($1, $2, 'identity', 'profile', $3::jsonb, 0.8,
                now(), now(), now(), $4, 'active', 'interpretation', 'user', 'sophie')
        """, fact_id, user_id, {"summary": "User seems tired"}, [source_id])
        
        # 2. New candidate: User confirms it
        candidate_id = uuid4()
        candidate = {
            "id": candidate_id,
            "user_id": user_id,
            "source_id": uuid4(),
            "candidate_type": "fact",
            "content": {
                "schema_version": "v1",
                "item_type": "fact",
                "summary": "User is tired",
                "evidence": {"raw_evidence": "Yeah, I am tired."}
            },
            "raw_evidence": "Yeah, I am tired.",
            "confidence": 0.95,
            "needs_confirmation": False,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "claimed_by_entity_id": "user",
            "subject_entity_id": "user",
            "claim_type": "direct",
            "interaction_mode": "real_life"
        }
        
        instructions = [
            {
                "candidate_id": str(candidate_id),
                "instruction": "UPDATE",
                "target_id": str(fact_id),
                "confidence_delta": 0.1,
                "reason": "User confirmed assistant interpretation."
            }
        ]
        
        await reconciliation.apply_reconciliation_results(
            db,
            candidates=[candidate],
            instructions=instructions,
            now=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        
        # 3. Verify fact was upgraded to 'direct'
        row = await db.fetchone("SELECT * FROM confirmed_facts WHERE id = $1", fact_id)
        assert row["claim_type"] == "direct"
        assert row["confidence"] > 0.8
        
    finally:
        await db.close()

@pytest.mark.anyio
async def test_reconciliation_preserves_contested_claims() -> None:
    await _require_db()
    db = Database()
    try:
        user_id = "test-user-" + str(uuid4())
        
        # 1. Existing fact from Speaker A (Ashley)
        fact_a_id = uuid4()
        await db.execute("""
            INSERT INTO confirmed_facts (
                id, user_id, fact_type, domain, content, confidence,
                first_seen_at, last_seen_at, last_confirmed_at,
                status, claim_type, subject_entity_id, claimed_by_entity_id
            ) VALUES ($1, $2, 'event', 'events', $3::jsonb, 0.9,
                now(), now(), now(), 'active', 'direct', 'meeting-123', 'ashley')
        """, fact_a_id, user_id, {"title": "Meeting at 2pm"})
        
        # 2. New candidate from Speaker B (John) contradicting Speaker A
        candidate_b_id = uuid4()
        candidate_b = {
            "id": candidate_b_id,
            "user_id": user_id,
            "source_id": uuid4(),
            "candidate_type": "fact",
            "content": {
                "schema_version": "v1",
                "item_type": "fact",
                "summary": "Meeting is at 3pm",
                "evidence": {"raw_evidence": "No, it is 3."}
            },
            "raw_evidence": "No, it is 3.",
            "confidence": 0.9,
            "needs_confirmation": False,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "claimed_by_entity_id": "john",
            "subject_entity_id": "meeting-123",
            "claim_type": "direct"
        }
        
        instructions = [
            {
                "candidate_id": str(candidate_b_id),
                "instruction": "CREATE",
                "target_id": None,
                "confidence_delta": 0.0,
                "reason": "Contested claim between Ashley and John."
            }
        ]
        
        await reconciliation.apply_reconciliation_results(
            db,
            candidates=[candidate_b],
            instructions=instructions,
            now=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        
        # 3. Verify both exist
        count = await db.fetchval("SELECT count(*) FROM confirmed_facts WHERE user_id = $1", user_id)
        assert count == 2
        
    finally:
        await db.close()

def test_pipeline_runner_formats_with_turn_markers() -> None:
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"}
    ]
    formatted = pipeline_runner.format_session_transcript(messages)
    assert "[Turn 0] User: Hello" in formatted
    assert "[Turn 1] Sophie: Hi there" in formatted
