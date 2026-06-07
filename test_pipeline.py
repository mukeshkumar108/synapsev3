from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from agent_contract import AgentInput, AgentOutput
from agents import (
    event_agent,
    fact_agent,
    session_summary_agent,
    state_agent,
    task_agent,
    thread_agent,
    triage_agent,
)
from core.candidates import candidate_records_from_outputs, persist_candidate_records
from core.db import Database


TRANSCRIPTS = [
    {
        "name": "task_reminder_heavy",
        "source_type": "chat",
        "raw_content": """User: I need to send the revised proposal to Maya tomorrow morning.
User: Please remind me at 8am to call the insurance company, and I am still waiting on Jordan to send the contract.
User: I should also keep doing my Sunday meal prep every week.
""",
    },
    {
        "name": "calendar_invitation_heavy",
        "source_type": "chat",
        "raw_content": """User: Alex invited me to dinner next Tuesday at 7pm in Shoreditch.
User: I have a product review with Sam on Thursday at 3pm.
User: The design deadline is Friday, but the venue for the offsite is still TBD.
""",
    },
    {
        "name": "durable_facts_entities",
        "source_type": "chat",
        "raw_content": """User: I am vegetarian and I hate red-eye flights.
User: My sister Nina lives in Bristol and she just started at Bluum.
User: I have been leading the Apollo migration project since January.
""",
    },
    {
        "name": "temporary_emotional_state",
        "source_type": "chat",
        "raw_content": """User: I am exhausted today and I cannot focus on anything except this investor update.
User: I am stressed that I am behind and worried the team can tell.
""",
    },
    {
        "name": "unresolved_relationship_project_thread",
        "source_type": "chat",
        "raw_content": """User: Things with Nina still feel unresolved after our argument.
User: We said we would talk again this weekend, but I do not know how to start.
User: The vendor negotiation is also stuck because legal has not responded.
""",
    },
    {
        "name": "mixed_noisy_chat",
        "source_type": "chat",
        "raw_content": """User: I grabbed coffee, watched a silly clip, and reset for a bit.
User: Anyway, can you remind me to send Leo the draft on Monday?
User: Also, Priya mentioned a possible catch-up sometime next week, but nothing is fixed yet.
""",
    },
    {
        "name": "companion_win_state",
        "source_type": "chat",
        "raw_content": """User: I finally finished the investor deck and I'm actually proud of myself.
""",
    },
    {
        "name": "companion_communication_preference",
        "source_type": "chat",
        "raw_content": """User: Please don't over-comfort me. Just be direct and give me the next step.
""",
    },
    {
        "name": "companion_avoid_topic",
        "source_type": "chat",
        "raw_content": """User: Please don't bring up the fertility stuff unless I mention it first.
""",
    },
    {
        "name": "companion_ask_about_later",
        "source_type": "chat",
        "raw_content": """User: I'm talking to Nina this weekend. Ask me how it went.
""",
    },
]


def _agent_input(source_type: str, raw_content: str) -> AgentInput:
    return AgentInput(
        user_id="demo-user",
        source_type=source_type,
        raw_content=raw_content,
        context={"current_date": datetime.now(timezone.utc).date().isoformat()},
    )


def _extraction_outputs(agent_input: AgentInput, triage_output: AgentOutput) -> list[AgentOutput]:
    item = triage_output.items[0] if triage_output.items else {}
    outputs: list[AgentOutput] = []
    if item.get("has_tasks"):
        outputs.append(task_agent.run(agent_input))
    if item.get("has_events") or item.get("has_invitations"):
        outputs.append(event_agent.run(agent_input))
    if item.get("has_facts"):
        outputs.append(fact_agent.run(agent_input))
    if item.get("has_state_change"):
        outputs.append(state_agent.run(agent_input))
    if item.get("has_threads"):
        outputs.append(thread_agent.run(agent_input))
    return outputs


async def _insert_outbox(database: Database, agent_input: AgentInput, transcript_name: str):
    source_id = uuid4()
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await database.execute(
        """
        INSERT INTO outbox (
            id, user_id, source_type, raw_content, received_at, status, retry_count, metadata
        ) VALUES ($1, $2, $3::outbox_source_type, $4, $5, $6::outbox_status, $7, $8::jsonb)
        """,
        source_id,
        agent_input.user_id,
        agent_input.source_type,
        agent_input.raw_content,
        created_at,
        "pending",
        0,
        {"test_pipeline": True, "transcript_name": transcript_name},
    )
    return source_id, created_at


async def _clear_demo_rows(database: Database) -> None:
    await database.execute("DELETE FROM candidates WHERE user_id = $1", "demo-user")
    await database.execute("DELETE FROM outbox WHERE user_id = $1", "demo-user")


async def _fetch_written_candidates(database: Database, source_id) -> list[dict]:
    return await database.fetch(
        """
        SELECT id, candidate_type, raw_evidence, confidence, needs_confirmation, status, content
        FROM candidates
        WHERE source_id = $1
        ORDER BY created_at, id
        """,
        source_id,
    )


async def run_transcript(database: Database, transcript: dict[str, str]) -> dict[str, object]:
    agent_input = _agent_input(transcript["source_type"], transcript["raw_content"])
    source_id, created_at = await _insert_outbox(database, agent_input, transcript["name"])

    triage_output = triage_agent.run(agent_input)
    summary_output = session_summary_agent.run(agent_input)
    extraction_outputs = _extraction_outputs(agent_input, triage_output)

    candidate_records = candidate_records_from_outputs(
        user_id=agent_input.user_id,
        source_id=source_id,
        outputs=extraction_outputs,
        created_at=created_at,
    )
    await persist_candidate_records(database, candidate_records)
    written_rows = await _fetch_written_candidates(database, source_id)

    return {
        "source_id": str(source_id),
        "source_type": transcript["source_type"],
        "raw_content": transcript["raw_content"],
        "triage": triage_output.model_dump(),
        "session_summary": summary_output.model_dump(),
        "extraction_outputs": [output.model_dump() for output in extraction_outputs],
        "candidate_rows": written_rows,
    }


async def main() -> None:
    database = Database()
    try:
        await _clear_demo_rows(database)
        for transcript in TRANSCRIPTS:
            result = await run_transcript(database, transcript)
            print(f"=== {transcript['name']} ===")
            print(json.dumps(result, indent=2, default=str))
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
