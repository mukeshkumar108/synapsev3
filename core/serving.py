from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from agents import surfacing_agent
from core.db import Database


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _current_datetime(value: str | None) -> datetime:
    parsed = _parse_datetime(value)
    return parsed or datetime.now(timezone.utc)


def _time_of_day(current_dt: datetime) -> str:
    hour = current_dt.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _coerce_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        return _parse_datetime(value)
    return None


def _localize(dt: datetime, timezone_name: str) -> datetime:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def _serialize_session_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(summary["id"]),
        "summary": summary["summary"],
        "tags": summary.get("tags", []),
        "open_items": summary.get("open_items", []),
        "key_decisions": summary.get("key_decisions", []),
        "emotional_tone": summary.get("emotional_tone"),
        "occurred_at": _coerce_utc_datetime(summary.get("occurred_at")).isoformat() if _coerce_utc_datetime(summary.get("occurred_at")) else None,
    }


def _time_since(last_dt: datetime, now: datetime) -> str:
    delta = max(now - last_dt, __import__("datetime").timedelta())
    seconds = int(delta.total_seconds())
    if seconds < 3600:
        minutes = max(1, seconds // 60)
        return f"{minutes}m"
    if seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days = seconds // 86400
    return f"{days}d"


def _rank_value(value: Any) -> int:
    if value == "high":
        return 3
    if value == "medium":
        return 2
    if value == "low":
        return 1
    return 0


def _normalized_names(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


def _content_metadata(fact: dict[str, Any]) -> dict[str, Any]:
    return (fact.get("content") or {}).get("metadata") or {}


def _content_links(fact: dict[str, Any]) -> dict[str, list[str]]:
    links = (fact.get("content") or {}).get("links") or {}
    return {
        "people": _normalized_names(links.get("people", [])),
        "projects": _normalized_names(links.get("projects", [])),
        "topics": _normalized_names(links.get("topics", [])),
    }


def _fact_source_refs(fact: dict[str, Any]) -> list[str]:
    return [f"outbox:{source_id}" for source_id in fact.get("source_ids", [])]


def _fact_is_expired(fact: dict[str, Any], now: datetime) -> bool:
    expires_at = _parse_datetime(fact.get("expires_at"))
    if expires_at and expires_at < now:
        return True

    content = fact.get("content", {})
    lifecycle = content.get("lifecycle", {})
    expires_at = _parse_datetime(lifecycle.get("expires_at"))
    if expires_at and expires_at < now:
        return True
    return False


def _fact_is_stale_state(fact: dict[str, Any], now: datetime) -> bool:
    content = fact.get("content", {})
    metadata = content.get("metadata", {})
    agent_item = metadata.get("agent_item", {})
    is_state_like = (
        fact.get("fact_type") == "state"
        or fact.get("domain") == "state"
        or content.get("item_type") == "state"
        or bool(agent_item.get("provisional"))
    )
    if not is_state_like:
        return False
    lifecycle = content.get("lifecycle", {})
    stale_after_hours = lifecycle.get("stale_after_hours") or content.get("time", {}).get("stale_after_hours")
    if not stale_after_hours:
        return False
    anchor = fact.get("last_seen_at") or fact.get("last_confirmed_at") or fact.get("first_seen_at")
    anchor_dt = anchor if isinstance(anchor, datetime) else _parse_datetime(str(anchor) if anchor else None)
    if not anchor_dt:
        return False
    return anchor_dt.replace(tzinfo=timezone.utc) < now - __import__("datetime").timedelta(hours=int(stale_after_hours))


def _open_loop_status(fact: dict[str, Any], now: datetime) -> str:
    if fact.get("status") == "dismissed":
        return "dismissed"
    if fact.get("status") in {"historical", "corrected"}:
        return "resolved"
    snoozed_until = fact.get("snoozed_until")
    if snoozed_until:
        snoozed_dt = _coerce_utc_datetime(snoozed_until)
        if snoozed_dt and snoozed_dt > now:
            return "snoozed"
    if _fact_is_expired(fact, now) or _fact_is_stale_state(fact, now):
        return "stale"

    metadata = _content_metadata(fact)
    explicit = metadata.get("open_loop_status") or (metadata.get("agent_item") or {}).get("open_loop_status")
    if explicit in {"active", "unresolved", "resolved", "dismissed", "stale", "deferred", "snoozed"}:
        return str(explicit)

    last_status = str(metadata.get("last_status") or (metadata.get("agent_item") or {}).get("last_status") or "").lower()
    if any(token in last_status for token in ("resolved", "finished", "complete", "closed")) and "unresolved" not in last_status:
        return "resolved"
    return "active" if fact.get("fact_type") == "thread" else "unresolved"


def _is_open_loop_fact(fact: dict[str, Any], now: datetime) -> bool:
    if fact.get("fact_type") != "thread":
        return False
    return _open_loop_status(fact, now) in {"active", "unresolved"}


def _open_loop_payload(fact: dict[str, Any]) -> dict[str, Any]:
    content = fact.get("content", {})
    metadata = content.get("metadata") or {}
    links = _content_links(fact)
    return {
        "id": str(fact["id"]),
        "title": content.get("title"),
        "summary": content.get("summary"),
        "salience": content.get("salience"),
        "priority": content.get("priority"),
        "importance": content.get("importance"),
        "urgency": content.get("urgency"),
        "confidence": float(fact.get("confidence", 0.0)),
        "last_seen_at": _coerce_utc_datetime(fact.get("last_seen_at")).isoformat() if _coerce_utc_datetime(fact.get("last_seen_at")) else None,
        "last_surfaced_at": metadata.get("last_surfaced_at"),
        "open_loop_status": metadata.get("open_loop_status") or ("active" if fact.get("fact_type") == "thread" else None),
        "last_status": metadata.get("last_status"),
        "follow_up_question": metadata.get("follow_up_question"),
        "source_refs": _fact_source_refs(fact),
        "evidence_preview": content.get("evidence", {}).get("raw_evidence") or content.get("summary"),
        "linked_people": links["people"],
        "linked_projects": links["projects"],
        "linked_topics": links["topics"],
    }


def _entity_hints(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        category = _content_metadata(fact).get("companion_category")
        if category in {"avoid_topic", "sensitivity_boundary"}:
            continue
        content = fact.get("content", {})
        links = _content_links(fact)
        for kind in ("people", "projects", "topics"):
            for name in links[kind]:
                key = (kind, name.lower())
                if key in seen:
                    continue
                seen.add(key)
                hints.append(
                    {
                        "name": name,
                        "kind": "person" if kind == "people" else "project" if kind == "projects" else "topic",
                        "source_fact_ids": [str(fact["id"])],
                        "last_seen_at": _coerce_utc_datetime(fact.get("last_seen_at")).isoformat() if _coerce_utc_datetime(fact.get("last_seen_at")) else None,
                    }
                )
        if fact.get("fact_type") == "relationship":
            title = str(content.get("title") or "").strip()
            key = ("people", title.lower())
            if title and key not in seen:
                seen.add(key)
                hints.append(
                    {
                        "name": title,
                        "kind": "person",
                        "source_fact_ids": [str(fact["id"])],
                        "last_seen_at": _coerce_utc_datetime(fact.get("last_seen_at")).isoformat() if _coerce_utc_datetime(fact.get("last_seen_at")) else None,
                    }
                )
    return hints[:8]


def _avoid_descriptors(facts: list[dict[str, Any]]) -> list[str]:
    avoid: list[str] = []
    for fact in facts:
        content = fact.get("content", {})
        category = content.get("metadata", {}).get("companion_category")
        if category not in {"avoid_topic", "sensitivity_boundary"}:
            continue
        descriptor = content.get("summary") or content.get("evidence", {}).get("raw_evidence") or content.get("title")
        if isinstance(descriptor, str) and descriptor.strip():
            avoid.append(descriptor.strip())
    return avoid


def _sanitize_topics(topics: list[str], avoid_items: list[str]) -> list[str]:
    if not avoid_items:
        return topics
    filtered: list[str] = []
    avoid_tokens = {
        token
        for item in avoid_items
        for token in item.lower().replace(",", " ").split()
        if len(token) >= 4
    }
    for topic in topics:
        lowered = topic.lower()
        if any(token in lowered for token in avoid_tokens):
            continue
        filtered.append(topic)
    return filtered


def _sanitize_worth_attention(items: list[dict[str, Any]], avoid_fact_ids: set[str]) -> list[dict[str, Any]]:
    if not avoid_fact_ids:
        return items
    return [
        item
        for item in items
        if not any(source_id in avoid_fact_ids for source_id in item.get("source_fact_ids", []))
    ]


def _serialize_content(content: Any) -> str:
    return json.dumps(content, sort_keys=True, default=str).lower()


def _fact_matches_query(fact: dict[str, Any], query_text: str) -> int:
    haystack = _serialize_content(fact.get("content"))
    words = [word for word in query_text.lower().split() if word]
    return sum(haystack.count(word) for word in words)


def _classify_facts(facts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tasks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    state: list[dict[str, Any]] = []
    threads: list[dict[str, Any]] = []
    for fact in facts:
        fact_type = fact.get("fact_type")
        if fact_type == "task":
            tasks.append(fact)
        elif fact_type == "event":
            events.append(fact)
        elif fact_type == "state":
            state.append(fact)
        elif fact_type == "thread":
            threads.append(fact)
    return tasks, events, state, threads


async def fetch_active_confirmed_facts(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM confirmed_facts
        WHERE user_id = $1 AND status = 'active'::fact_status
        ORDER BY last_seen_at DESC NULLS LAST, first_seen_at DESC NULLS LAST
        """,
        user_id,
    )


async def fetch_recent_timeline(database: Database, *, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM timeline_events
        WHERE user_id = $1
        ORDER BY observed_at DESC NULLS LAST, occurred_at DESC NULLS LAST
        LIMIT $2
        """,
        user_id,
        limit,
    )


async def fetch_recent_session_summaries(database: Database, *, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM session_summaries
        WHERE user_id = $1
        ORDER BY occurred_at DESC NULLS LAST
        LIMIT $2
        """,
        user_id,
        limit,
    )


async def fetch_catch_up_rows(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM outbox
        WHERE user_id = $1
          AND status IN ('pending'::outbox_status, 'processing'::outbox_status)
        ORDER BY received_at DESC NULLS LAST
        """,
        user_id,
    )


async def build_instruction_packet(
    database: Database,
    *,
    user_id: str,
    current_datetime: str | None = None,
    timezone_name: str = "UTC",
    llm_client=None,
) -> dict[str, Any]:
    now = _current_datetime(current_datetime)
    facts = await fetch_active_confirmed_facts(database, user_id=user_id)
    current_facts = [
        fact
        for fact in facts
        if not _fact_is_expired(fact, now) and not _fact_is_stale_state(fact, now)
    ]
    tasks, events, state, threads = _classify_facts(current_facts)
    threads = [fact for fact in threads if _is_open_loop_fact(fact, now)]
    timeline = await fetch_recent_timeline(database, user_id=user_id, limit=5)
    summaries = await fetch_recent_session_summaries(database, user_id=user_id, limit=20)
    catch_up_rows = await fetch_catch_up_rows(database, user_id=user_id)

    last_summary = summaries[0] if summaries else None
    last_interaction_dt = _coerce_utc_datetime(last_summary.get("occurred_at")) if last_summary else None
    local_now = _localize(now, timezone_name)
    sessions_today = [
        summary
        for summary in summaries
        if (_coerce_utc_datetime(summary.get("occurred_at")) and _localize(_coerce_utc_datetime(summary.get("occurred_at")), timezone_name).date() == local_now.date())
    ]
    yesterday_date = local_now.date() - __import__("datetime").timedelta(days=1)
    yesterday_summaries = [
        summary
        for summary in summaries
        if (_coerce_utc_datetime(summary.get("occurred_at")) and _localize(_coerce_utc_datetime(summary.get("occurred_at")), timezone_name).date() == yesterday_date)
    ]

    if not last_interaction_dt:
        handover_depth = "cold_start"
    else:
        local_last = _localize(last_interaction_dt, timezone_name)
        if now - last_interaction_dt <= __import__("datetime").timedelta(minutes=30):
            handover_depth = "continuation"
        elif local_last.date() == local_now.date():
            handover_depth = "same_day"
        elif local_last.date() == yesterday_date:
            handover_depth = "yesterday"
        else:
            handover_depth = "multi_day"

    active_open_loops = [
        _open_loop_payload(fact)
        for fact in sorted(
            [fact for fact in current_facts if _is_open_loop_fact(fact, now)],
            key=lambda fact: (
                1 if _open_loop_status(fact, now) == "active" else 0,
                _rank_value(fact.get("content", {}).get("priority")),
                _rank_value(fact.get("content", {}).get("urgency")),
                _rank_value(fact.get("content", {}).get("importance")),
                _rank_value(fact.get("content", {}).get("salience")),
                float(fact.get("confidence", 0.0)),
                _coerce_utc_datetime(fact.get("last_seen_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
            ),
            reverse=True,
        )
    ]

    avoid_items = _avoid_descriptors(current_facts)
    avoid_fact_ids = {
        str(fact["id"])
        for fact in current_facts
        if fact.get("content", {}).get("metadata", {}).get("companion_category") in {"avoid_topic", "sensitivity_boundary"}
    }

    surfacing = surfacing_agent.run(
        confirmed_facts=current_facts,
        tasks=tasks,
        events=events,
        state=state,
        threads=threads,
        recent_timeline=timeline,
        time_of_day=_time_of_day(now),
        current_datetime=now.isoformat(),
        timezone=timezone_name,
        llm_client=llm_client,
    )
    surfacing["worth_attention"] = _sanitize_worth_attention(surfacing["worth_attention"], avoid_fact_ids)
    surfacing["relevant_topics"] = _sanitize_topics(surfacing["relevant_topics"], avoid_items)
    merged_avoid = list(dict.fromkeys([*avoid_items, *surfacing.get("avoid", [])]))

    freshness = {
        "pending_outbox_count": sum(1 for row in catch_up_rows if row.get("status") == "pending"),
        "processing_outbox_count": sum(1 for row in catch_up_rows if row.get("status") == "processing"),
        "catch_up_needed": bool(catch_up_rows),
        "status": "catching_up" if catch_up_rows else "up_to_date",
    }

    return {
        **surfacing,
        "avoid": merged_avoid,
        "last_interaction_at": last_interaction_dt.isoformat() if last_interaction_dt else None,
        "time_since_last_interaction": _time_since(last_interaction_dt, now) if last_interaction_dt else None,
        "sessions_today_count": len(sessions_today),
        "is_first_contact_today": len(sessions_today) == 0,
        "handover_depth": handover_depth,
        "last_session_summary": _serialize_session_summary(last_summary) if last_summary else None,
        "today_context": [_serialize_session_summary(summary) for summary in sessions_today[:3]],
        "yesterday_context": [_serialize_session_summary(summary) for summary in yesterday_summaries[:3]],
        "active_open_loops": active_open_loops[:5],
        "entity_hints": _entity_hints(current_facts),
        "freshness": freshness,
    }


async def build_daily_overview(
    database: Database,
    *,
    user_id: str,
    day: str | None = None,
    timezone_name: str = "UTC",
    llm_client=None,
) -> dict[str, Any]:
    now = _current_datetime(day)
    packet = await build_instruction_packet(
        database,
        user_id=user_id,
        current_datetime=now.isoformat(),
        timezone_name=timezone_name,
        llm_client=llm_client,
    )
    facts = await fetch_active_confirmed_facts(database, user_id=user_id)
    current_facts = [
        fact
        for fact in facts
        if not _fact_is_expired(fact, now) and not _fact_is_stale_state(fact, now)
    ]
    tasks, events, _, _ = _classify_facts(current_facts)
    return {
        "date": now.date().isoformat(),
        "schedule": [event["content"] for event in events],
        "open_tasks": [task["content"] for task in tasks],
        "worth_attention": packet["worth_attention"],
        "suggested_focus": packet["suggested_focus"],
    }


async def query_memory(
    database: Database,
    *,
    user_id: str,
    query_text: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    facts = await fetch_active_confirmed_facts(database, user_id=user_id)
    scored = [
        (fact, _fact_matches_query(fact, query_text))
        for fact in facts
        if fact.get("status") == "active"
    ]
    ranked = [fact for fact, score in sorted(scored, key=lambda item: item[1], reverse=True) if score > 0]
    return ranked[:limit]


async def ingest_outbox(
    database: Database,
    *,
    user_id: str,
    source_type: str,
    raw_content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_id = uuid4()
    received_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await database.execute(
        """
        INSERT INTO outbox (
            id, user_id, source_type, raw_content, received_at, status, retry_count, metadata
        ) VALUES ($1, $2, $3::outbox_source_type, $4, $5, $6::outbox_status, $7, $8::jsonb)
        """,
        source_id,
        user_id,
        source_type,
        raw_content,
        received_at,
        "pending",
        0,
        metadata or {},
    )
    return {"source_id": str(source_id), "status": "pending"}
