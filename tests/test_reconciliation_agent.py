from __future__ import annotations

import pytest

from agents import reconciliation_agent


class MockLLMClient:
    def __init__(self, response):
        self.response = response

    def generate_json(self, **_: object):
        return self.response


def _candidate(candidate_id: str) -> dict:
    return {
        "id": candidate_id,
        "candidate_type": "fact",
        "content": {"item_type": "fact"},
        "raw_evidence": "User is vegetarian.",
        "confidence": 0.9,
        "needs_confirmation": False,
        "status": "pending",
        "created_at": "2026-05-22T10:00:00",
        "source_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "user-1",
    }


def _fact(fact_id: str) -> dict:
    return {
        "id": fact_id,
        "fact_type": "identity",
        "domain": "profile",
        "content": {"item_type": "fact"},
        "confidence": 0.9,
        "status": "active",
        "source_ids": [],
        "user_id": "user-1",
    }


def test_reconciliation_agent_validates_successful_output() -> None:
    items = reconciliation_agent.run(
        new_candidates=[_candidate("c1")],
        existing_facts=[_fact("f1")],
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "candidate_id": "c1",
                        "instruction": "CREATE",
                        "target_id": None,
                        "confidence_delta": 0.1,
                        "reason": "This looks like a new durable fact.",
                    }
                ]
            }
        ),
    )
    assert items[0]["instruction"] == "CREATE"


def test_reconciliation_agent_rejects_invalid_target_id() -> None:
    with pytest.raises(ValueError, match="target_id"):
        reconciliation_agent.run(
            new_candidates=[_candidate("c1")],
            existing_facts=[_fact("f1")],
            llm_client=MockLLMClient(
                {
                    "items": [
                        {
                            "candidate_id": "c1",
                            "instruction": "MERGE",
                            "target_id": "missing",
                            "confidence_delta": 0.1,
                            "reason": "bad target",
                        }
                    ]
                }
            ),
        )


def test_reconciliation_agent_rejects_invalid_instruction() -> None:
    with pytest.raises(ValueError, match="instruction is invalid"):
        reconciliation_agent.run(
            new_candidates=[_candidate("c1")],
            existing_facts=[],
            llm_client=MockLLMClient(
                {
                    "items": [
                        {
                            "candidate_id": "c1",
                            "instruction": "PROMOTE",
                            "target_id": None,
                            "confidence_delta": 0.1,
                            "reason": "bad instruction",
                        }
                    ]
                }
            ),
        )


def test_reconciliation_agent_rejects_unknown_candidate_id() -> None:
    with pytest.raises(ValueError, match="candidate_id"):
        reconciliation_agent.run(
            new_candidates=[_candidate("c1")],
            existing_facts=[],
            llm_client=MockLLMClient(
                {
                    "items": [
                        {
                            "candidate_id": "c2",
                            "instruction": "CREATE",
                            "target_id": None,
                            "confidence_delta": 0.1,
                            "reason": "unknown candidate",
                        }
                    ]
                }
            ),
        )
