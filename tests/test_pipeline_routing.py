from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from agent_contract import AgentInput, AgentOutput
from test_pipeline import run_transcript


pytestmark = pytest.mark.anyio


class FakeDatabase:
    def __init__(self) -> None:
        self.candidate_rows: list[dict[str, Any]] = []

    async def execute(self, query: str, *args: Any) -> str:
        if "INSERT INTO candidates" in query:
            self.candidate_rows.append(
                {
                    "id": args[0],
                    "user_id": args[1],
                    "source_id": args[2],
                    "candidate_type": args[3],
                    "fact_type": args[4],
                    "content": args[5],
                    "structured_content": args[6],
                    "raw_evidence": args[7],
                    "confidence": args[8],
                    "needs_confirmation": args[9],
                    "status": args[10],
                }
            )
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        source_id: UUID = args[0]
        return [
            {
                "id": row["id"],
                "candidate_type": row["candidate_type"],
                "raw_evidence": row["raw_evidence"],
                "confidence": row["confidence"],
                "needs_confirmation": row["needs_confirmation"],
                "status": row["status"],
                "content": row["content"],
            }
            for row in self.candidate_rows
            if row["source_id"] == source_id
        ]

    async def close(self) -> None:
        return None


def _summary_output() -> AgentOutput:
    return AgentOutput(
        agent="session_summary_agent",
        status="success",
        items=[
            {
                "summary": "test summary",
                "tags": ["personal"],
                "open_items": [],
                "key_decisions": [],
                "emotional_tone": "neutral",
            }
        ],
        errors=[],
        confidence_notes="ok",
    )


async def test_run_transcript_routes_explicit_communication_preference_to_fact_agent(
    monkeypatch,
) -> None:
    fact_called = False

    def fake_triage(_: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent="triage_agent",
            status="success",
            items=[
                {
                    "has_tasks": False,
                    "has_events": False,
                    "has_facts": True,
                    "has_state_change": False,
                    "has_threads": False,
                    "has_invitations": False,
                    "session_kind": "personal",
                    "emotional_weight": "medium",
                    "emotional_note": "The user is explicitly calibrating support style.",
                    "tension_signal": None,
                    "ignore_reasons": [],
                    "memory_worthy": True,
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    def fake_summary(_: AgentInput) -> AgentOutput:
        return _summary_output()

    def fake_fact(_: AgentInput) -> AgentOutput:
        nonlocal fact_called
        fact_called = True
        return AgentOutput(
            agent="fact_agent",
            status="success",
            items=[
                {
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
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    monkeypatch.setattr("test_pipeline.triage_agent.run", fake_triage)
    monkeypatch.setattr("test_pipeline.session_summary_agent.run", fake_summary)
    monkeypatch.setattr("test_pipeline.fact_agent.run", fake_fact)

    db = FakeDatabase()
    result = await run_transcript(
        db,
        {
            "name": "explicit_communication_preference",
            "source_type": "chat",
            "raw_content": "User: Please don't over-comfort me. Just be direct and give me the next step.\n",
        },
    )

    assert fact_called is True
    assert [output["agent"] for output in result["extraction_outputs"]] == ["fact_agent"]
    assert result["candidate_rows"][0]["candidate_type"] == "fact"
    assert result["candidate_rows"][0]["content"]["item_type"] == "fact"
    assert result["candidate_rows"][0]["content"]["metadata"]["companion_category"] in {
        "communication_preference",
        "encouragement_style",
    }
    assert result["candidate_rows"][0]["content"]["metadata"]["agent_item"]["fact_type"] == "preference"


async def test_run_transcript_routes_explicit_avoid_topic_to_fact_agent(monkeypatch) -> None:
    def fake_triage(_: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent="triage_agent",
            status="success",
            items=[
                {
                    "has_tasks": False,
                    "has_events": False,
                    "has_facts": True,
                    "has_state_change": False,
                    "has_threads": False,
                    "has_invitations": False,
                    "session_kind": "personal",
                    "emotional_weight": "medium",
                    "emotional_note": "The user sets a clear boundary around a sensitive topic.",
                    "tension_signal": None,
                    "ignore_reasons": [],
                    "memory_worthy": True,
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    def fake_summary(_: AgentInput) -> AgentOutput:
        return _summary_output()

    def fake_fact(_: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent="fact_agent",
            status="success",
            items=[
                {
                    "subject": "user",
                    "fact_type": "constraint",
                    "content": "The user does not want fertility topics raised unless they mention them first.",
                    "companion_category": "avoid_topic",
                    "about_user": True,
                    "person_name": None,
                    "related_people": [],
                    "related_projects": ["fertility"],
                    "salience": "high",
                    "sensitivity": "high",
                    "needs_confirmation": False,
                    "raw_evidence": "Please don't bring up the fertility stuff unless I mention it first.",
                    "confidence": 0.99,
                }
            ],
            errors=[],
            confidence_notes="ok",
        )

    monkeypatch.setattr("test_pipeline.triage_agent.run", fake_triage)
    monkeypatch.setattr("test_pipeline.session_summary_agent.run", fake_summary)
    monkeypatch.setattr("test_pipeline.fact_agent.run", fake_fact)

    db = FakeDatabase()
    result = await run_transcript(
        db,
        {
            "name": "explicit_avoid_topic",
            "source_type": "chat",
            "raw_content": "User: Please don't bring up the fertility stuff unless I mention it first.\n",
        },
    )

    assert [output["agent"] for output in result["extraction_outputs"]] == ["fact_agent"]
    assert result["candidate_rows"][0]["candidate_type"] == "fact"
    assert result["candidate_rows"][0]["content"]["item_type"] == "fact"
    assert result["candidate_rows"][0]["content"]["metadata"]["companion_category"] in {
        "avoid_topic",
        "sensitivity_boundary",
    }
    assert result["candidate_rows"][0]["content"]["metadata"]["agent_item"]["fact_type"] == "constraint"
    assert result["candidate_rows"][0]["content"]["sensitivity"] == "high"
