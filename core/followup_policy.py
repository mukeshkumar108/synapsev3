from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.operational import parse_datetime

MAX_AGENT_CANDIDATES = 3
RECENT_ACTIVITY_MINUTES = 30
RECENT_RESURFACING_HOURS = 4
MAX_PROACTIVE_PER_DAY = 2


def _coerce_utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return parse_datetime(value)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    haystack = text.lower()
    return any(token in haystack for token in tokens)


def _candidate_text(packet: dict[str, Any]) -> str:
    parts = [
        str(packet.get("title") or ""),
        str(packet.get("summary") or ""),
        str(packet.get("surface_reason") or ""),
        " ".join(str(value) for value in packet.get("linked_topics") or []),
    ]
    return " ".join(parts)


def _priority_score(packet: dict[str, Any]) -> tuple[int, float, float]:
    text = _candidate_text(packet)
    health_tokens = ("symptom", "pain", "hurt", "injury", "ill", "flu", "medication", "swelling", "nausea", "doctor", "migraine")
    relationship_tokens = ("niece", "mum", "mom", "mother", "father", "brother", "sister", "son", "daughter", "family")
    urgency = 0
    if _contains_any(text, health_tokens):
        urgency = 3
    elif _contains_any(text, relationship_tokens):
        urgency = 2
    elif packet.get("thread_type") in {"care_checkin", "followup_thread"}:
        urgency = 1
    return (
        urgency,
        float(packet.get("overdue_hours", 0.0)),
        float(packet.get("confidence", 0.0)),
    )


def evaluate_follow_up_candidates(
    candidates: list[dict[str, Any]],
    *,
    current_datetime: datetime | str | None = None,
    recent_user_activity_at: datetime | str | None = None,
    proactive_sent_today: int = 0,
    max_daily_proactive: int = MAX_PROACTIVE_PER_DAY,
) -> dict[str, Any]:
    now = _coerce_utc(current_datetime) or datetime.now(timezone.utc)
    recent_activity = _coerce_utc(recent_user_activity_at)
    if proactive_sent_today >= max_daily_proactive:
        return {
            "status": "suppress",
            "reason": "daily_limit_reached",
            "candidates": [],
            "suppressed": [{"thread_id": packet["thread_id"], "reason": "daily_limit_reached"} for packet in candidates],
            "deferred": [],
        }
    if recent_activity and (now - recent_activity).total_seconds() < RECENT_ACTIVITY_MINUTES * 60:
        return {
            "status": "suppress",
            "reason": "recent_user_activity",
            "candidates": [],
            "suppressed": [{"thread_id": packet["thread_id"], "reason": "recent_user_activity"} for packet in candidates],
            "deferred": [],
        }

    eligible: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for packet in candidates:
        resurfaced_at = _coerce_utc(packet.get("last_resurfaced_at"))
        if resurfaced_at and (now - resurfaced_at).total_seconds() < RECENT_RESURFACING_HOURS * 3600:
            suppressed.append({"thread_id": packet["thread_id"], "reason": "recent_resurfacing"})
            continue
        overdue_hours = float(packet.get("overdue_hours", 0.0))
        if overdue_hours < 0.5:
            deferred.append({"thread_id": packet["thread_id"], "reason": "freshly_due"})
            continue
        eligible.append(packet)

    eligible.sort(key=_priority_score, reverse=True)
    shortlisted = eligible[:MAX_AGENT_CANDIDATES]
    for packet in eligible[MAX_AGENT_CANDIDATES:]:
        deferred.append({"thread_id": packet["thread_id"], "reason": "rollover_capacity"})

    return {
        "status": "candidate_review" if shortlisted else ("defer" if deferred else "suppress"),
        "reason": "eligible_candidates" if shortlisted else ("nothing_mature_enough" if deferred else "no_eligible_candidates"),
        "candidates": shortlisted,
        "suppressed": suppressed,
        "deferred": deferred,
        "policy_context": {
            "recent_user_activity_at": recent_activity.isoformat() if recent_activity else None,
            "proactive_sent_today": proactive_sent_today,
            "max_daily_proactive": max_daily_proactive,
        },
    }
