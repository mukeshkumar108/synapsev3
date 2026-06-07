from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents import followup_agent
from core.db import Database
from core.followup_policy import evaluate_follow_up_candidates
from core.followup_service import due_follow_up_packets
from core.operational import parse_datetime


def _coerce_utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return parse_datetime(value)


def _iter_rows(container: Any) -> list[dict[str, Any]]:
    if isinstance(container, dict):
        return list(container.values())
    if isinstance(container, list):
        return list(container)
    return []


def _latest_user_activity(database: Database, *, user_id: str) -> datetime | None:
    candidates: list[datetime] = []
    if hasattr(database, "session_summaries"):
        for row in _iter_rows(getattr(database, "session_summaries")):
            if row.get("user_id") != user_id:
                continue
            occurred_at = _coerce_utc(row.get("occurred_at"))
            if occurred_at:
                candidates.append(occurred_at)
    if hasattr(database, "outbox_rows"):
        for row in _iter_rows(getattr(database, "outbox_rows")):
            if row.get("user_id") != user_id:
                continue
            received_at = _coerce_utc(row.get("received_at"))
            if received_at:
                candidates.append(received_at)
    return max(candidates) if candidates else None


def _proactive_sent_today(database: Database, *, user_id: str, now: datetime) -> int:
    total = 0
    if not hasattr(database, "timeline_events"):
        return 0
    for row in _iter_rows(getattr(database, "timeline_events")):
        if row.get("user_id") != user_id:
            continue
        if row.get("event_type") != "thread_progressed" or row.get("timeline_type") != "system":
            continue
        occurred_at = _coerce_utc(row.get("occurred_at") or row.get("observed_at"))
        if occurred_at and occurred_at.date() == now.date():
            total += 1
    return total


async def plan_follow_up(
    database: Database,
    *,
    user_id: str,
    current_datetime: datetime | str | None = None,
    timezone_name: str = "UTC",
    llm_client=None,
) -> dict[str, Any]:
    now = _coerce_utc(current_datetime) or datetime.now(timezone.utc)
    candidates = await due_follow_up_packets(database, user_id=user_id, now=now)
    recent_activity = _latest_user_activity(database, user_id=user_id)
    proactive_sent_today = _proactive_sent_today(database, user_id=user_id, now=now)
    policy = evaluate_follow_up_candidates(
        candidates,
        current_datetime=now,
        recent_user_activity_at=recent_activity,
        proactive_sent_today=proactive_sent_today,
    )
    if not policy["candidates"]:
        return {
            "decision": policy["status"],
            "reason": policy["reason"],
            "candidates_reviewed": len(candidates),
            "selected_thread_ids": [],
            "message": "",
            "policy": policy,
            "agent_decision": None,
            "recent_user_activity_at": recent_activity.isoformat() if recent_activity else None,
            "proactive_sent_today": proactive_sent_today,
        }
    agent_decision = followup_agent.run(
        candidates=policy["candidates"],
        current_datetime=now.isoformat(),
        timezone=timezone_name,
        recent_user_activity=recent_activity.isoformat() if recent_activity else None,
        policy_context=policy.get("policy_context"),
        llm_client=llm_client,
    )
    return {
        "decision": agent_decision["decision"],
        "reason": policy["reason"],
        "candidates_reviewed": len(candidates),
        "selected_thread_ids": agent_decision["selected_thread_ids"],
        "message": agent_decision["message"],
        "policy": policy,
        "agent_decision": agent_decision,
        "recent_user_activity_at": recent_activity.isoformat() if recent_activity else None,
        "proactive_sent_today": proactive_sent_today,
    }
