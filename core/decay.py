from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from core.db import Database


EXCLUDED_COMPANION_CATEGORIES = {
    "avoid_topic",
    "sensitivity_boundary",
    "communication_preference",
    "comfort_preference",
    "tone_preference",
    "encouragement_style",
}

STATE_DEFAULT_WINDOWS = {
    "low": 24,
    "medium": 48,
    "high": 72,
}


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _content(fact: dict[str, Any]) -> dict[str, Any]:
    content = fact.get("content")
    return content if isinstance(content, dict) else {}


def _lifecycle(content: dict[str, Any]) -> dict[str, Any]:
    lifecycle = content.get("lifecycle")
    return lifecycle if isinstance(lifecycle, dict) else {}


def _time_block(content: dict[str, Any]) -> dict[str, Any]:
    time_block = content.get("time")
    return time_block if isinstance(time_block, dict) else {}


def _metadata(content: dict[str, Any]) -> dict[str, Any]:
    metadata = content.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _agent_item(content: dict[str, Any]) -> dict[str, Any]:
    agent_item = _metadata(content).get("agent_item")
    return agent_item if isinstance(agent_item, dict) else {}


def _companion_category(fact: dict[str, Any]) -> str | None:
    value = _metadata(_content(fact)).get("companion_category")
    return value if isinstance(value, str) else None


def _is_provisional(fact: dict[str, Any]) -> bool:
    return bool(_agent_item(_content(fact)).get("provisional"))


def _is_state_like(fact: dict[str, Any]) -> bool:
    content = _content(fact)
    return (
        fact.get("fact_type") == "state"
        or fact.get("domain") == "state"
        or content.get("item_type") == "state"
        or _is_provisional(fact)
    )


def _stale_after_hours(fact: dict[str, Any]) -> int | None:
    content = _content(fact)
    for value in (
        _lifecycle(content).get("stale_after_hours"),
        _time_block(content).get("stale_after_hours"),
    ):
        if value is None:
            continue
        try:
            hours = int(value)
        except (TypeError, ValueError):
            continue
        if hours > 0:
            return hours
    if not _is_state_like(fact):
        return None
    salience = content.get("salience")
    if salience in STATE_DEFAULT_WINDOWS:
        return STATE_DEFAULT_WINDOWS[salience]
    return STATE_DEFAULT_WINDOWS["medium"]


def _anchor_time(fact: dict[str, Any]) -> datetime | None:
    for value in (fact.get("last_seen_at"), fact.get("last_confirmed_at"), fact.get("first_seen_at")):
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed
    return None


def _explicit_expiry(fact: dict[str, Any]) -> datetime | None:
    relational = _parse_datetime(fact.get("expires_at"))
    if relational is not None:
        return relational
    return _parse_datetime(_lifecycle(_content(fact)).get("expires_at"))


def _is_eligible(fact: dict[str, Any]) -> bool:
    if fact.get("status") != "active":
        return False
    content = _content(fact)
    return any(
        (
            fact.get("fact_type") == "state",
            fact.get("domain") == "state",
            content.get("item_type") == "state",
            _is_provisional(fact),
            _lifecycle(content).get("stale_after_hours") is not None,
            _time_block(content).get("stale_after_hours") is not None,
            fact.get("expires_at") is not None,
            _lifecycle(content).get("expires_at") is not None,
        )
    )


def _is_excluded(fact: dict[str, Any]) -> bool:
    companion_category = _companion_category(fact)
    if companion_category in EXCLUDED_COMPANION_CATEGORIES:
        return True
    if _is_state_like(fact):
        return False
    if _explicit_expiry(fact) is not None:
        return False
    if _stale_after_hours(fact) is not None:
        return True
    return fact.get("fact_type") in {"preference", "relationship", "identity", "thread"}


def _decay_reason(fact: dict[str, Any], now: datetime) -> tuple[bool, str | None]:
    expires_at = _explicit_expiry(fact)
    if expires_at is not None and expires_at <= now:
        return True, "expires_at passed"

    stale_after_hours = _stale_after_hours(fact)
    if stale_after_hours is None:
        return False, None

    anchor = _anchor_time(fact)
    if anchor is None:
        return False, None
    if anchor <= now - timedelta(hours=stale_after_hours):
        return True, f"last seen more than {stale_after_hours} hours ago"
    return False, None


def _build_result(fact: dict[str, Any], *, reason: str) -> dict[str, Any]:
    content = _content(fact)
    return {
        "fact_id": fact["id"],
        "user_id": fact["user_id"],
        "previous_status": fact["status"],
        "next_status": "stale",
        "reason": reason,
        "fact_type": fact.get("fact_type"),
        "domain": fact.get("domain"),
        "title": content.get("title"),
        "summary": content.get("summary"),
        "companion_category": _companion_category(fact),
        "confidence": fact.get("confidence"),
    }


async def fetch_decay_eligible_facts(
    database: Database,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM confirmed_facts
        WHERE status = 'active'::fact_status
        ORDER BY last_seen_at DESC NULLS LAST, first_seen_at DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )


async def _mark_fact_stale(database: Database, *, fact_id: UUID) -> None:
    await database.execute(
        """
        UPDATE confirmed_facts
        SET status = 'stale'::fact_status
        WHERE id = $1
        """,
        fact_id,
    )


async def _insert_decay_timeline_event(
    database: Database,
    *,
    fact: dict[str, Any],
    now: datetime,
    reason: str,
) -> None:
    content = _content(fact)
    title = content.get("title") or "State memory marked stale"
    summary = f"Marked stale because {reason}."
    await database.execute(
        """
        INSERT INTO timeline_events (
            id,
            user_id,
            event_type,
            timeline_type,
            title,
            summary,
            occurred_at,
            observed_at,
            source_id,
            related_fact_ids,
            status,
            confidence
        ) VALUES (
            $1, $2, $3::event_type, $4::timeline_type, $5, $6, $7, $8, $9, $10, $11::timeline_status, $12
        )
        """,
        uuid4(),
        fact["user_id"],
        "state_change",
        "system",
        title,
        summary,
        now.replace(tzinfo=None),
        now.replace(tzinfo=None),
        None,
        [fact["id"]],
        "current",
        fact.get("confidence"),
    )


async def decay_state_memories(
    database: Database,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    limit: int = 500,
) -> list[dict[str, Any]]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    facts = await fetch_decay_eligible_facts(database, limit=limit)
    results: list[dict[str, Any]] = []
    for fact in facts:
        if not _is_eligible(fact):
            continue
        if _is_excluded(fact):
            continue
        should_decay, reason = _decay_reason(fact, current_time)
        if not should_decay or reason is None:
            continue
        result = _build_result(fact, reason=reason)
        results.append(result)
        if dry_run:
            continue
        await _mark_fact_stale(database, fact_id=fact["id"])
        fact["status"] = "stale"
        await _insert_decay_timeline_event(
            database,
            fact=fact,
            now=current_time,
            reason=reason,
        )
    return results
