from __future__ import annotations

from agent_contract import AgentInput
from agents import event_agent, fact_agent, state_agent, task_agent, thread_agent


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
        context={"current_date": "2026-05-22"},
    )


def test_task_agent_extracts_only_task_domain() -> None:
    output = task_agent.run(
        _agent_input("Remind me at 8am to call insurance and I am waiting on Jordan for the contract."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "title": "Call insurance company",
                        "description": "User wants a reminder before starting the day.",
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
                    },
                    {
                        "title": "Follow up on contract from Jordan",
                        "description": "Waiting on Jordan to send the contract.",
                        "due_date": None,
                        "reminder_at": None,
                        "priority": "medium",
                        "urgency": "medium",
                        "is_habit": False,
                        "recurrence": None,
                        "waiting_on": "Jordan",
                        "needs_confirmation": False,
                        "salience": "medium",
                        "raw_evidence": "I am still waiting on Jordan to send the contract.",
                        "confidence": 0.91,
                        "related_people": ["Jordan"],
                        "related_projects": ["contract"],
                    },
                ]
            }
        ),
    )

    assert output.status == "success"
    assert len(output.items) == 2
    assert "date" not in output.items[0]
    assert "attendees" not in output.items[0]


def test_task_agent_does_not_duplicate_calendar_event_as_task() -> None:
    output = task_agent.run(
        _agent_input("I have a product review with Sam on Thursday at 3pm."),
        llm_client=MockLLMClient({"items": []}),
    )
    assert output.status == "success"
    assert output.items == []


def test_simple_future_task_is_not_a_thread() -> None:
    output = thread_agent.run(
        _agent_input("I need to send the proposal tomorrow."),
        llm_client=MockLLMClient({"items": []}),
    )
    assert output.status == "success"
    assert output.items == []


def test_event_agent_extracts_only_event_domain() -> None:
    output = event_agent.run(
        _agent_input("Alex invited me to dinner next Tuesday at 7pm in Shoreditch."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
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
                        "confidence": 0.95,
                    }
                ]
            }
        ),
    )

    item = output.items[0]
    assert output.status == "success"
    assert item["is_invitation"] is True
    assert "priority" not in item
    assert "fact_type" not in item


def test_event_agent_does_not_duplicate_reminder_as_event() -> None:
    output = event_agent.run(
        _agent_input("Remind me to send Leo the draft on Monday."),
        llm_client=MockLLMClient({"items": []}),
    )
    assert output.status == "success"
    assert output.items == []


def test_event_only_transcript_is_not_a_thread() -> None:
    output = thread_agent.run(
        _agent_input("I have a product review with Sam on Thursday at 3pm."),
        llm_client=MockLLMClient({"items": []}),
    )
    assert output.status == "success"
    assert output.items == []


def test_fact_agent_extracts_only_durable_fact_domain() -> None:
    output = fact_agent.run(
        _agent_input("I am vegetarian and my sister Nina lives in Bristol."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "subject": "user",
                        "fact_type": "preference",
                        "content": "The user is vegetarian.",
                        "companion_category": None,
                        "about_user": True,
                        "person_name": None,
                        "related_people": [],
                        "related_projects": [],
                        "salience": "high",
                        "sensitivity": "low",
                        "needs_confirmation": False,
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "user",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "I am vegetarian",
                        "confidence": 0.98,
                    },
                    {
                        "subject": "Nina",
                        "fact_type": "relationship",
                        "content": "Nina is the user's sister and lives in Bristol.",
                        "companion_category": None,
                        "about_user": False,
                        "person_name": "Nina",
                        "related_people": ["Nina"],
                        "related_projects": [],
                        "salience": "medium",
                        "sensitivity": "low",
                        "needs_confirmation": False,
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "nina-uuid",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "my sister Nina lives in Bristol",
                        "confidence": 0.9,
                    },

                ]
            }
        ),
    )

    assert output.status == "success"
    assert len(output.items) == 2
    assert "emotional_state" not in output.items[0]
    assert "follow_up_question" not in output.items[0]


def test_fact_agent_does_not_store_operational_items_as_durable_facts() -> None:
    output = fact_agent.run(
        _agent_input(
            "I need to send the proposal tomorrow. I have a product review Thursday. Alex invited me to dinner next Tuesday. The design deadline is Friday."
        ),
        llm_client=MockLLMClient({"items": []}),
    )
    assert output.status == "success"
    assert output.items == []


def test_fact_agent_normalizes_companion_specific_fact_type_to_preference() -> None:
    output = fact_agent.run(
        _agent_input("Please don't over-comfort me. Just be direct and give me the next step."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "subject": "user",
                        "fact_type": "communication_preference",
                        "content": "The user prefers direct, practical support over heavy comforting.",
                        "companion_category": None,
                        "about_user": True,
                        "person_name": None,
                        "related_people": [],
                        "related_projects": [],
                        "salience": "high",
                        "sensitivity": "medium",
                        "needs_confirmation": False,
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "user",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "Please don't over-comfort me. Just be direct and give me the next step.",
                        "confidence": 0.98,
                    }
                ]
            }
        ),
    )

    assert output.status == "success"
    assert output.items[0]["fact_type"] == "preference"
    assert output.items[0]["companion_category"] == "communication_preference"


def test_fact_agent_normalizes_companion_specific_fact_type_to_constraint() -> None:
    output = fact_agent.run(
        _agent_input("Please don't bring up the fertility stuff unless I mention it first."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "subject": "user",
                        "fact_type": "avoid_topic",
                        "content": "The user does not want fertility topics raised unless they mention them first.",
                        "companion_category": None,
                        "about_user": True,
                        "person_name": None,
                        "related_people": [],
                        "related_projects": ["fertility"],
                        "salience": "high",
                        "sensitivity": "high",
                        "needs_confirmation": False,
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "user",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "Please don't bring up the fertility stuff unless I mention it first.",
                        "confidence": 0.99,
                    }
                ]
            }
        ),
    )

    assert output.status == "success"
    assert output.items[0]["fact_type"] == "constraint"
    assert output.items[0]["companion_category"] == "avoid_topic"


def test_state_agent_extracts_only_temporary_state() -> None:
    output = state_agent.run(
        _agent_input("I am exhausted today and stressed about the investor update."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "emotional_state": "stressed",
                        "current_focus": "Finishing the investor update.",
                        "companion_category": None,
                        "energy_level": "low",
                        "stress_level": "high",
                        "notable_tension": "User feels behind on the investor update.",
                        "sensitivity": "medium",
                        "stale_after_hours": 48,
                        "raw_evidence": "I am exhausted today and stressed about the investor update.",
                        "confidence": 0.93,
                        "provisional": True,
                    }
                ]
            }
        ),
    )

    item = output.items[0]
    assert output.status == "success"
    assert item["provisional"] is True
    assert "fact_type" not in item
    assert "due_date" not in item


def test_thread_agent_extracts_only_unresolved_thread_domain() -> None:
    output = thread_agent.run(
        _agent_input("Things with Nina still feel unresolved and we said we would talk again this weekend."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "title": "Unresolved argument with Nina",
                        "summary": "The user still feels unresolved after an argument with Nina.",
                        "companion_category": None,
                        "involves": ["Nina"],
                        "last_status": "A follow-up conversation is expected this weekend.",
                        "follow_up_question": "How did the conversation with Nina go?",
                        "follow_up_after_hours": 48,
                        "needs_confirmation": False,
                        "salience": "high",
                        "priority": "high",
                        "sensitivity": "high",
                        "stale_after_hours": 168,
                        "related_people": ["Nina"],
                        "related_projects": [],
                        "raw_evidence": "Things with Nina still feel unresolved",
                        "confidence": 0.94,
                    }
                ]
            }
        ),
    )

    item = output.items[0]
    assert output.status == "success"
    assert item["follow_up_after_hours"] == 48
    assert "emotional_state" not in item
    assert "date" not in item


def test_waiting_on_transcript_extracts_thread() -> None:
    output = thread_agent.run(
        _agent_input("I am still waiting on Jordan to send the contract."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "title": "Waiting on Jordan to send the contract",
                        "summary": "The user is still waiting for Jordan to send the contract.",
                        "companion_category": None,
                        "involves": ["Jordan", "User"],
                        "last_status": "Contract still has not been sent.",
                        "follow_up_question": "Have you heard back from Jordan about the contract?",
                        "follow_up_after_hours": 24,
                        "needs_confirmation": True,
                        "salience": "high",
                        "priority": "high",
                        "sensitivity": "medium",
                        "stale_after_hours": 72,
                        "related_people": ["Jordan"],
                        "related_projects": ["contract"],
                        "raw_evidence": "I am still waiting on Jordan to send the contract.",
                        "confidence": 0.95,
                    }
                ]
            }
        ),
    )
    assert output.status == "success"
    assert len(output.items) == 1


def test_reminder_only_transcript_is_not_a_thread() -> None:
    output = thread_agent.run(
        _agent_input("Remind me to send Leo the draft on Monday."),
        llm_client=MockLLMClient({"items": []}),
    )
    assert output.status == "success"
    assert output.items == []


def test_thread_agent_tentative_social_plan_requires_confirmation_when_kept() -> None:
    output = thread_agent.run(
        _agent_input("Priya mentioned a possible catch-up next week, but nothing is fixed yet."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "title": "Possible catch-up with Priya",
                        "summary": "Priya mentioned a possible catch-up next week but nothing is scheduled.",
                        "companion_category": None,
                        "involves": ["Priya", "User"],
                        "last_status": "No date or time has been confirmed.",
                        "follow_up_question": "Have you and Priya picked a time yet?",
                        "follow_up_after_hours": 48,
                        "needs_confirmation": True,
                        "salience": "medium",
                        "priority": "low",
                        "sensitivity": "low",
                        "stale_after_hours": 168,
                        "related_people": ["Priya"],
                        "related_projects": [],
                        "raw_evidence": "Priya mentioned a possible catch-up next week, but nothing is fixed yet.",
                        "confidence": 0.78,
                    }
                ]
            }
        ),
    )
    assert output.status == "success"
    assert output.items[0]["needs_confirmation"] is True


def test_extraction_agents_surface_errors() -> None:
    output = event_agent.run(
        _agent_input("This is broken"),
        llm_client=MockLLMClient({"items": [{"title": "Missing keys"}]}),
    )
    assert output.status == "error"
    assert output.items == []
    assert output.errors


def test_win_or_accomplishment_extracts_without_task() -> None:
    state_output = state_agent.run(
        _agent_input("I finally finished the investor deck and I'm actually proud of myself."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "emotional_state": "happy",
                        "current_focus": "Finished the investor deck and feels proud of it.",
                        "companion_category": "win",
                        "energy_level": "medium",
                        "stress_level": "low",
                        "notable_tension": None,
                        "sensitivity": "medium",
                        "stale_after_hours": 48,
                        "raw_evidence": "I finally finished the investor deck and I'm actually proud of myself.",
                        "confidence": 0.95,
                        "provisional": True,
                    }
                ]
            }
        ),
    )
    task_output = task_agent.run(
        _agent_input("I finally finished the investor deck and I'm actually proud of myself."),
        llm_client=MockLLMClient({"items": []}),
    )

    assert state_output.status == "success"
    assert state_output.items[0]["companion_category"] == "win"
    assert state_output.items[0]["sensitivity"] in {"medium", "high"}
    assert task_output.items == []


def test_low_or_struggle_extracts_as_provisional_state() -> None:
    output = state_agent.run(
        _agent_input("Today has been rough. I feel like I can't catch up."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "emotional_state": "stressed",
                        "current_focus": "Feeling behind and unable to catch up today.",
                        "companion_category": "low",
                        "energy_level": "low",
                        "stress_level": "high",
                        "notable_tension": "Feels unable to catch up.",
                        "sensitivity": "high",
                        "stale_after_hours": 24,
                        "raw_evidence": "Today has been rough. I feel like I can't catch up.",
                        "confidence": 0.94,
                        "provisional": True,
                    }
                ]
            }
        ),
    )

    assert output.status == "success"
    assert output.items[0]["companion_category"] == "low"
    assert output.items[0]["sensitivity"] == "high"
    assert output.items[0]["provisional"] is True


def test_aspiration_extracts_as_durable_fact_not_task() -> None:
    fact_output = fact_agent.run(
        _agent_input("I really want to write a book one day."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "subject": "user",
                        "fact_type": "background",
                        "content": "The user wants to write a book one day.",
                        "companion_category": "aspiration",
                        "about_user": True,
                        "person_name": None,
                        "related_people": [],
                        "related_projects": ["book"],
                        "salience": "high",
                        "sensitivity": "medium",
                        "needs_confirmation": False,
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "user",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "I really want to write a book one day.",
                        "confidence": 0.96,
                    }
                ]
            }
        ),
    )
    task_output = task_agent.run(
        _agent_input("I really want to write a book one day."),
        llm_client=MockLLMClient({"items": []}),
    )

    assert fact_output.status == "success"
    assert fact_output.items[0]["companion_category"] == "aspiration"
    assert task_output.items == []


def test_fear_or_worry_extracts_with_gentle_follow_up() -> None:
    state_output = state_agent.run(
        _agent_input("I'm scared I'm heading back toward burnout."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "emotional_state": "anxious",
                        "current_focus": "Fear of heading back toward burnout.",
                        "companion_category": "fear",
                        "energy_level": "low",
                        "stress_level": "high",
                        "notable_tension": "Scared of slipping back toward burnout.",
                        "sensitivity": "high",
                        "stale_after_hours": 24,
                        "raw_evidence": "I'm scared I'm heading back toward burnout.",
                        "confidence": 0.95,
                        "provisional": True,
                    }
                ]
            }
        ),
    )
    thread_output = thread_agent.run(
        _agent_input("I'm scared I'm heading back toward burnout."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "title": "Burnout worry",
                        "summary": "The user is worried they may be heading back toward burnout.",
                        "companion_category": "worry",
                        "involves": ["User"],
                        "last_status": "The concern is present now and unresolved.",
                        "follow_up_question": "How are you feeling about the burnout worry today?",
                        "follow_up_after_hours": 24,
                        "needs_confirmation": False,
                        "salience": "high",
                        "priority": "medium",
                        "sensitivity": "high",
                        "stale_after_hours": 72,
                        "related_people": [],
                        "related_projects": [],
                        "raw_evidence": "I'm scared I'm heading back toward burnout.",
                        "confidence": 0.88,
                    }
                ]
            }
        ),
    )

    assert state_output.status == "success"
    assert state_output.items[0]["companion_category"] == "fear"
    assert state_output.items[0]["sensitivity"] == "high"
    assert thread_output.status == "success"
    assert thread_output.items[0]["companion_category"] == "worry"
    assert "How are you feeling" in thread_output.items[0]["follow_up_question"]


def test_inside_joke_extracts_as_fact_without_task_or_thread() -> None:
    fact_output = fact_agent.run(
        _agent_input("I'm back in spreadsheet goblin mode again."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "subject": "user",
                        "fact_type": "trait",
                        "content": "The user refers playfully to focused spreadsheet work as spreadsheet goblin mode.",
                        "companion_category": "inside_joke",
                        "about_user": True,
                        "person_name": None,
                        "related_people": [],
                        "related_projects": ["spreadsheet work"],
                        "salience": "low",
                        "sensitivity": "low",
                        "needs_confirmation": True,
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "user",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "I'm back in spreadsheet goblin mode again.",
                        "confidence": 0.84,
                    }
                ]
            }
        ),
    )
    task_output = task_agent.run(
        _agent_input("I'm back in spreadsheet goblin mode again."),
        llm_client=MockLLMClient({"items": []}),
    )
    thread_output = thread_agent.run(
        _agent_input("I'm back in spreadsheet goblin mode again."),
        llm_client=MockLLMClient({"items": []}),
    )

    assert fact_output.status == "success"
    assert fact_output.items[0]["companion_category"] == "inside_joke"
    assert fact_output.items[0]["salience"] in {"low", "medium"}
    assert task_output.items == []
    assert thread_output.items == []


def test_communication_preference_extracts_without_task_or_thread() -> None:
    fact_output = fact_agent.run(
        _agent_input("Please don't over-comfort me. Just be direct and give me the next step."),
        llm_client=MockLLMClient(
            {
                "items": [
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
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "user",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "Please don't over-comfort me. Just be direct and give me the next step.",
                        "confidence": 0.98,
                    }
                ]
            }
        ),
    )
    task_output = task_agent.run(
        _agent_input("Please don't over-comfort me. Just be direct and give me the next step."),
        llm_client=MockLLMClient({"items": []}),
    )
    thread_output = thread_agent.run(
        _agent_input("Please don't over-comfort me. Just be direct and give me the next step."),
        llm_client=MockLLMClient({"items": []}),
    )

    assert fact_output.status == "success"
    assert fact_output.items[0]["companion_category"] == "communication_preference"
    assert fact_output.items[0]["salience"] == "high"
    assert task_output.items == []
    assert thread_output.items == []


def test_avoid_topic_extracts_as_explicit_boundary() -> None:
    output = fact_agent.run(
        _agent_input("Please don't bring up the fertility stuff unless I mention it first."),
        llm_client=MockLLMClient(
            {
                "items": [
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
                        "claimed_by_entity_id": "user",
                        "subject_entity_id": "user",
                        "claim_type": "direct",
                        "evidence_turn_index": 0,
                        "raw_evidence": "Please don't bring up the fertility stuff unless I mention it first.",
                        "confidence": 0.99,
                    }
                ]
            }
        ),
    )

    assert output.status == "success"
    assert output.items[0]["companion_category"] == "avoid_topic"
    assert output.items[0]["sensitivity"] == "high"
    assert output.items[0]["needs_confirmation"] is False


def test_ask_about_later_extracts_as_thread() -> None:
    output = thread_agent.run(
        _agent_input("I'm talking to Nina this weekend. Ask me how it went."),
        llm_client=MockLLMClient(
            {
                "items": [
                    {
                        "title": "Follow up on talk with Nina",
                        "summary": "The user wants Sophie to ask later about their weekend conversation with Nina.",
                        "companion_category": "ask_about_later",
                        "involves": ["User", "Nina"],
                        "last_status": "Conversation is upcoming this weekend.",
                        "follow_up_question": "How did the conversation with Nina go?",
                        "follow_up_after_hours": 48,
                        "needs_confirmation": False,
                        "salience": "medium",
                        "priority": "medium",
                        "sensitivity": "medium",
                        "stale_after_hours": 168,
                        "related_people": ["Nina"],
                        "related_projects": [],
                        "raw_evidence": "I'm talking to Nina this weekend. Ask me how it went.",
                        "confidence": 0.97,
                    }
                ]
            }
        ),
    )

    assert output.status == "success"
    assert output.items[0]["companion_category"] == "ask_about_later"
    assert output.items[0]["follow_up_after_hours"] > 0
    assert output.items[0]["related_people"] == ["Nina"]


def test_ask_about_later_is_not_duplicated_as_task() -> None:
    output = task_agent.run(
        _agent_input("I'm talking to Nina this weekend. Ask me how it went."),
        llm_client=MockLLMClient({"items": []}),
    )

    assert output.status == "success"
    assert output.items == []
