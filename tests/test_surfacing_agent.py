from __future__ import annotations

from agents import surfacing_agent


class MockLLMClient:
    def __init__(self, response):
        self.response = response

    def generate_json(self, **_: object):
        return self.response


def test_surfacing_agent_validates_basic_open_loop_output() -> None:
    output = surfacing_agent.run(
        confirmed_facts=[],
        tasks=[],
        events=[],
        state=[],
        threads=[],
        recent_timeline=[],
        time_of_day="morning",
        current_datetime="2026-05-22T09:00:00+00:00",
        timezone="Europe/London",
        llm_client=MockLLMClient(
            {
                "session_instructions": "Lead with the contract follow-up context and stay practical.",
                "relevant_topics": ["Jordan contract"],
                "worth_attention": [
                    {
                        "title": "Waiting on Jordan contract",
                        "why_it_matters": "It is blocking forward progress.",
                        "suggested_way_to_raise": "Ask whether Jordan has replied yet.",
                        "sensitivity": "low",
                        "source_fact_ids": ["fact-1"],
                    }
                ],
                "suggested_focus": "Jordan contract follow-up",
                "tone_note": "Be direct and practical.",
                "avoid": [],
                "stale_warnings": [],
            }
        ),
    )
    assert output["worth_attention"][0]["title"] == "Waiting on Jordan contract"


def test_surfacing_agent_rejects_more_than_three_attention_items() -> None:
    try:
        surfacing_agent.run(
            confirmed_facts=[],
            tasks=[],
            events=[],
            state=[],
            threads=[],
            recent_timeline=[],
            time_of_day="morning",
            current_datetime="2026-05-22T09:00:00+00:00",
            timezone="Europe/London",
            llm_client=MockLLMClient(
                {
                    "session_instructions": "x",
                    "relevant_topics": [],
                    "worth_attention": [
                        {"title": "1", "why_it_matters": "a", "suggested_way_to_raise": "a", "sensitivity": "low", "source_fact_ids": []},
                        {"title": "2", "why_it_matters": "a", "suggested_way_to_raise": "a", "sensitivity": "low", "source_fact_ids": []},
                        {"title": "3", "why_it_matters": "a", "suggested_way_to_raise": "a", "sensitivity": "low", "source_fact_ids": []},
                        {"title": "4", "why_it_matters": "a", "suggested_way_to_raise": "a", "sensitivity": "low", "source_fact_ids": []},
                    ],
                    "suggested_focus": "x",
                    "tone_note": "x",
                    "avoid": [],
                    "stale_warnings": [],
                }
            ),
        )
    except ValueError as exc:
        assert "at most 3" in str(exc)
    else:
        raise AssertionError("Expected surfacing agent validation to fail.")
