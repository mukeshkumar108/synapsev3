from __future__ import annotations

from agent_contract import AgentInput
from agents import session_summary_agent, triage_agent


class MockLLMClient:
    def __init__(self, response):
        self.response = response

    def generate_json(self, **_: object):
        return self.response


def _agent_input(raw_content: str) -> AgentInput:
    return AgentInput(
        user_id="test-user",
        source_type="chat",
        raw_content=raw_content,
        context={},
    )


def test_triage_agent_output_shape_task_event_heavy() -> None:
    output = triage_agent.run(
        _agent_input("I need to send the deck tomorrow and I have a 3pm review on Thursday."),
        llm_client=MockLLMClient(
            {
                "has_tasks": True,
                "has_events": True,
                "has_facts": False,
                "has_state_change": False,
                "has_threads": False,
                "has_invitations": True,
                "session_kind": "mixed",
                "emotional_weight": "medium",
                "emotional_note": "The user sounds busy but not distressed.",
                "tension_signal": None,
                "ignore_reasons": [],
                "memory_worthy": True,
            }
        ),
    )

    assert output.agent == "triage_agent"
    assert output.status == "success"
    assert output.errors == []
    assert isinstance(output.items, list)
    assert len(output.items) == 1
    assert set(output.items[0]) == {
        "has_tasks",
        "has_events",
        "has_facts",
        "has_state_change",
        "has_threads",
        "has_invitations",
        "session_kind",
        "emotional_weight",
        "emotional_note",
        "tension_signal",
        "ignore_reasons",
        "memory_worthy",
    }
    assert output.items[0]["session_kind"] == "mixed"
    assert output.items[0]["has_invitations"] is True


def test_triage_agent_output_shape_relationship_thread() -> None:
    output = triage_agent.run(
        _agent_input("I am still upset with Nina and it feels unresolved."),
        llm_client=MockLLMClient(
            {
                "has_tasks": False,
                "has_events": False,
                "has_facts": False,
                "has_state_change": True,
                "has_threads": True,
                "has_invitations": False,
                "session_kind": "personal",
                "emotional_weight": "high",
                "emotional_note": "The user is clearly upset and preoccupied by the conflict.",
                "tension_signal": "The conflict with Nina remains unresolved ahead of their next talk.",
                "ignore_reasons": [],
                "memory_worthy": True,
            }
        ),
    )

    item = output.items[0]
    assert item["has_state_change"] is True
    assert item["has_threads"] is True
    assert item["emotional_weight"] == "high"
    assert item["session_kind"] == "personal"
    assert item["tension_signal"] is not None
    assert "summary" not in item
    assert "tasks" not in item


def test_triage_agent_output_shape_low_memory_chat() -> None:
    output = triage_agent.run(
        _agent_input("I got coffee and watched a silly clip. Nothing major."),
        llm_client=MockLLMClient(
            {
                "has_tasks": False,
                "has_events": False,
                "has_facts": False,
                "has_state_change": False,
                "has_threads": False,
                "has_invitations": False,
                "session_kind": "transient",
                "emotional_weight": "low",
                "emotional_note": None,
                "tension_signal": None,
                "ignore_reasons": ["Casual low-stakes check-in with no future relevance."],
                "memory_worthy": False,
            }
        ),
    )

    item = output.items[0]
    assert item["memory_worthy"] is False
    assert item["has_tasks"] is False
    assert item["has_events"] is False
    assert item["has_state_change"] is False
    assert item["session_kind"] == "transient"
    assert item["ignore_reasons"]


def test_triage_agent_reminder_only_has_tasks_not_threads() -> None:
    output = triage_agent.run(
        _agent_input("Remind me to send Leo the draft on Monday."),
        llm_client=MockLLMClient(
            {
                "has_tasks": True,
                "has_events": False,
                "has_facts": False,
                "has_state_change": False,
                "has_threads": False,
                "has_invitations": False,
                "session_kind": "transient",
                "emotional_weight": "low",
                "emotional_note": None,
                "tension_signal": None,
                "ignore_reasons": [],
                "memory_worthy": True,
            }
        ),
    )
    item = output.items[0]
    assert item["has_tasks"] is True
    assert item["has_threads"] is False


def test_triage_agent_casual_reset_does_not_false_route() -> None:
    output = triage_agent.run(
        _agent_input(
            "I just took a quick walk, got coffee, and cleared my head before getting back to work. Nothing important."
        ),
        llm_client=MockLLMClient(
            {
                "has_tasks": False,
                "has_events": False,
                "has_facts": False,
                "has_state_change": False,
                "has_threads": False,
                "has_invitations": False,
                "session_kind": "transient",
                "emotional_weight": "low",
                "emotional_note": None,
                "tension_signal": None,
                "ignore_reasons": [
                    "Passing reset chat with no durable state change or follow-up value."
                ],
                "memory_worthy": False,
            }
        ),
    )

    item = output.items[0]
    assert item["memory_worthy"] is False
    assert item["has_state_change"] is False
    assert item["has_threads"] is False
    assert item["has_tasks"] is False
    assert item["has_events"] is False
    assert item["ignore_reasons"]


def test_triage_agent_explicit_communication_preference_routes_to_facts() -> None:
    output = triage_agent.run(
        _agent_input("Please don't over-comfort me. Just be direct and give me the next step."),
        llm_client=MockLLMClient(
            {
                "has_tasks": False,
                "has_events": False,
                "has_facts": True,
                "has_state_change": False,
                "has_threads": False,
                "has_invitations": False,
                "session_kind": "personal",
                "emotional_weight": "medium",
                "emotional_note": "The user is explicitly calibrating how they want support delivered.",
                "tension_signal": None,
                "ignore_reasons": [],
                "memory_worthy": True,
            }
        ),
    )

    item = output.items[0]
    assert item["has_facts"] is True
    assert item["memory_worthy"] is True
    assert item["has_state_change"] is False


def test_triage_agent_explicit_avoid_topic_routes_to_facts() -> None:
    output = triage_agent.run(
        _agent_input("Please don't bring up the fertility stuff unless I mention it first."),
        llm_client=MockLLMClient(
            {
                "has_tasks": False,
                "has_events": False,
                "has_facts": True,
                "has_state_change": False,
                "has_threads": False,
                "has_invitations": False,
                "session_kind": "personal",
                "emotional_weight": "medium",
                "emotional_note": "The user sets a clear topic boundary around a sensitive subject.",
                "tension_signal": None,
                "ignore_reasons": [],
                "memory_worthy": True,
            }
        ),
    )

    item = output.items[0]
    assert item["has_facts"] is True
    assert item["memory_worthy"] is True


def test_triage_agent_casual_emotional_state_does_not_route_to_facts() -> None:
    output = triage_agent.run(
        _agent_input("I'm tired today and need a break."),
        llm_client=MockLLMClient(
            {
                "has_tasks": False,
                "has_events": False,
                "has_facts": False,
                "has_state_change": True,
                "has_threads": False,
                "has_invitations": False,
                "session_kind": "transient",
                "emotional_weight": "low",
                "emotional_note": "The user sounds tired and wants a break today.",
                "tension_signal": None,
                "ignore_reasons": [],
                "memory_worthy": True,
            }
        ),
    )

    item = output.items[0]
    assert item["has_state_change"] is True
    assert item["has_facts"] is False


def test_session_summary_output_shape_relationship_thread() -> None:
    output = session_summary_agent.run(
        _agent_input("I am still upset with Nina and the friendship feels unresolved."),
        llm_client=MockLLMClient(
            {
                "summary": "The user described an unresolved conflict with Nina and said they are still replaying the argument. They want to repair the friendship but also feel dismissed and need to be understood before the next conversation.",
                "tags": ["relationship", "conflict", "stress"],
                "open_items": [{"item": "Talk with Nina this weekend"}],
                "key_decisions": [{"decision": "Approach the next conversation honestly"}],
                "emotional_tone": "anxious",
            }
        ),
    )

    assert output.agent == "session_summary_agent"
    assert output.status == "success"
    assert output.errors == []
    assert isinstance(output.items, list)
    assert len(output.items) == 1
    item = output.items[0]
    assert set(item) == {"summary", "tags", "open_items", "key_decisions", "emotional_tone"}
    assert len(item["summary"].split()) < 120
    assert set(item["tags"]).issubset(session_summary_agent.ALLOWED_TAGS)
    assert item["emotional_tone"] in session_summary_agent.ALLOWED_TONES
    assert "has_tasks" not in item
    assert "has_events" not in item


def test_session_summary_output_shape_task_event_heavy() -> None:
    output = session_summary_agent.run(
        _agent_input("I need to send Maya the proposal and confirm dinner with Alex."),
        llm_client=MockLLMClient(
            {
                "summary": "The user talked through a busy stretch of commitments, including sending Maya a proposal, preparing for a dentist appointment, and confirming dinner plans with Alex while managing a scheduled review later in the week.",
                "tags": ["planning", "work", "personal"],
                "open_items": [{"item": "Confirm dinner with Alex"}],
                "key_decisions": [{"decision": "Send the revised proposal tomorrow morning"}],
                "emotional_tone": "stressed",
            }
        ),
    )

    item = output.items[0]
    assert "title" not in item
    assert "due_date" not in item
    assert isinstance(item["open_items"], list)
    assert isinstance(item["key_decisions"], list)


def test_session_summary_output_shape_low_memory_chat() -> None:
    output = session_summary_agent.run(
        _agent_input("I had coffee and watched a silly cooking clip. Nothing major."),
        llm_client=MockLLMClient(
            {
                "summary": "The user described a quiet, low-stakes break with coffee, a short walk, and a light video before returning to the afternoon. Nothing significant or unresolved came up in the exchange.",
                "tags": ["personal"],
                "open_items": [],
                "key_decisions": [],
                "emotional_tone": "neutral",
            }
        ),
    )

    item = output.items[0]
    assert item["open_items"] == []
    assert item["key_decisions"] == []
    assert item["emotional_tone"] == "neutral"


def test_session_summary_normalizes_string_lists_without_cross_domain_fields() -> None:
    output = session_summary_agent.run(
        _agent_input("We said we would revisit this next week, but nothing is settled yet."),
        llm_client=MockLLMClient(
            {
                "summary": "The user described an unresolved issue that they expect to revisit next week, with no final resolution reached in this exchange.",
                "tags": ["planning", "personal"],
                "open_items": ["Revisit the unresolved issue next week"],
                "key_decisions": [],
                "emotional_tone": "neutral",
            }
        ),
    )

    item = output.items[0]
    assert item["open_items"] == [{"item": "Revisit the unresolved issue next week"}]
    assert "due_date" not in item
    assert "candidate_type" not in item


def test_agents_surface_errors() -> None:
    bad_triage = triage_agent.run(
        _agent_input("Anything"),
        llm_client=MockLLMClient({"has_tasks": "yes"}),
    )
    bad_summary = session_summary_agent.run(
        _agent_input("Anything"),
        llm_client=MockLLMClient({"summary": "", "tags": []}),
    )

    assert bad_triage.status == "error"
    assert bad_triage.items == []
    assert bad_triage.errors
    assert bad_summary.status == "error"
    assert bad_summary.items == []
    assert bad_summary.errors
