from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from agents import reconciliation_agent
from core.db import Database
from core import embeddings
from core.operational import apply_lifecycle_timestamp, extract_operational_fields, normalize_provenance, parse_datetime, parse_datetime as _parse_datetime


CREATE_MERGE_UPDATE = {"CREATE", "MERGE", "UPDATE"}
CONFIRMED_FACT_TYPES = {"task", "event", "preference", "relationship", "state", "thread", "identity"}
RELATIVE_TIME_MARKERS = ("tomorrow", "today", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "weekend", "next week")
OPEN_LOOP_STATES = {"active", "unresolved", "resolved", "dismissed", "stale", "deferred"}


def _title_for_timeline(candidate: dict[str, Any], fact_type: str) -> str:
    content = candidate["content"]
    return (
        content.get("title")
        or content.get("summary")
        or content.get("metadata", {}).get("agent_item", {}).get("content")
        or f"{fact_type} confirmed"
    )


def _summary_for_timeline(candidate: dict[str, Any]) -> str:
    content = candidate["content"]
    return (
        content.get("summary")
        or content.get("evidence", {}).get("raw_evidence")
        or "Confirmed from reconciliation pipeline."
    )


def _normalized_entity_values(values: list[Any]) -> list[str]:
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


def _entity_links(content: dict[str, Any]) -> dict[str, list[str]]:
    links = content.get("links") or {}
    return {
        "people": _normalized_entity_values(links.get("people", [])),
        "projects": _normalized_entity_values(links.get("projects", [])),
        "topics": _normalized_entity_values(links.get("topics", [])),
    }


def _merge_link_values(*values: list[Any]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in values:
        for value in group:
            cleaned = str(value or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
    return merged


def _candidate_open_loop_status(candidate: dict[str, Any]) -> str | None:
    content = candidate.get("content") or {}
    metadata = content.get("metadata") or {}
    status = metadata.get("open_loop_status") or (metadata.get("agent_item") or {}).get("open_loop_status")
    if status in OPEN_LOOP_STATES:
        return str(status)
    if candidate.get("candidate_type") == "thread":
        return "active"
    return None


def _summary_overlap_ratio(left: str, right: str) -> float:
    left_tokens = {token for token in left.lower().split() if len(token) >= 4}
    right_tokens = {token for token in right.lower().split() if len(token) >= 4}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _is_ambiguous_entity_merge(candidate: dict[str, Any], fact: dict[str, Any]) -> bool:
    candidate_links = _entity_links(candidate.get("content") or {})
    fact_links = _entity_links(fact.get("content") or {})
    candidate_people = {value.lower() for value in candidate_links["people"]}
    fact_people = {value.lower() for value in fact_links["people"]}
    shared_people = candidate_people & fact_people
    if not shared_people:
        return False

    candidate_projects = {value.lower() for value in candidate_links["projects"] + candidate_links["topics"]}
    fact_projects = {value.lower() for value in fact_links["projects"] + fact_links["topics"]}
    shared_context = candidate_projects & fact_projects
    if shared_context:
        return False
    if candidate_projects and fact_projects and candidate_projects != fact_projects:
        return True

    candidate_title = str((candidate.get("content") or {}).get("title") or "").strip().lower()
    fact_title = str((fact.get("content") or {}).get("title") or "").strip().lower()
    same_title = bool(candidate_title and candidate_title == fact_title)
    candidate_summary = str((candidate.get("content") or {}).get("summary") or candidate.get("raw_evidence") or "")
    fact_summary = str((fact.get("content") or {}).get("summary") or "")
    summary_overlap = _summary_overlap_ratio(candidate_summary, fact_summary)
    return same_title and summary_overlap < 0.35


def _merged_content(existing_content: dict[str, Any], candidate_content: dict[str, Any], *, instruction: str) -> dict[str, Any]:
    base = dict(candidate_content if instruction == "UPDATE" else existing_content)
    fallback = existing_content if instruction == "UPDATE" else candidate_content
    merged = {
        **base,
        "title": base.get("title") or fallback.get("title"),
        "summary": base.get("summary") or fallback.get("summary"),
        "salience": base.get("salience") or fallback.get("salience"),
        "priority": base.get("priority") or fallback.get("priority"),
        "urgency": base.get("urgency") or fallback.get("urgency"),
        "importance": base.get("importance") or fallback.get("importance"),
        "sensitivity": base.get("sensitivity") or fallback.get("sensitivity"),
    }

    existing_links = _entity_links(existing_content)
    candidate_links = _entity_links(candidate_content)
    existing_raw_links = existing_content.get("links") or {}
    candidate_raw_links = candidate_content.get("links") or {}
    merged["links"] = {
        "people": _merge_link_values(existing_links["people"], candidate_links["people"]),
        "projects": _merge_link_values(existing_links["projects"], candidate_links["projects"]),
        "topics": _merge_link_values(existing_links["topics"], candidate_links["topics"]),
        "related_facts": _merge_link_values(existing_raw_links.get("related_facts", []), candidate_raw_links.get("related_facts", [])),
        "related_threads": _merge_link_values(existing_raw_links.get("related_threads", []), candidate_raw_links.get("related_threads", [])),
    }

    existing_metadata = existing_content.get("metadata") or {}
    candidate_metadata = candidate_content.get("metadata") or {}
    merged["metadata"] = {
        **existing_metadata,
        **candidate_metadata,
        "companion_category": candidate_metadata.get("companion_category") or existing_metadata.get("companion_category"),
        "open_loop_status": candidate_metadata.get("open_loop_status") or existing_metadata.get("open_loop_status"),
        "last_status": candidate_metadata.get("last_status") or existing_metadata.get("last_status"),
        "follow_up_question": candidate_metadata.get("follow_up_question") or existing_metadata.get("follow_up_question"),
        "waiting_on": candidate_metadata.get("waiting_on") or existing_metadata.get("waiting_on"),
        "last_surfaced_at": existing_metadata.get("last_surfaced_at") or candidate_metadata.get("last_surfaced_at"),
        "involves": _merge_link_values(existing_metadata.get("involves", []), candidate_metadata.get("involves", [])),
        "agent_item": {
            **(existing_metadata.get("agent_item") or {}),
            **(candidate_metadata.get("agent_item") or {}),
        },
    }

    existing_lifecycle = existing_content.get("lifecycle") or {}
    candidate_lifecycle = candidate_content.get("lifecycle") or {}
    merged["lifecycle"] = {
        **existing_lifecycle,
        **candidate_lifecycle,
    }
    return merged


def _fact_type_for_candidate(candidate: dict[str, Any]) -> str:
    candidate_type = candidate["candidate_type"]
    agent_item = candidate["content"].get("metadata", {}).get("agent_item", {})

    if candidate_type == "task":
        return "task"
    if candidate_type == "reminder":
        return "reminder"
    if candidate_type == "habit":
        return "habit"
    if candidate_type in {"event", "invitation"}:
        return "event"
    if candidate_type == "state":
        return "state"
    if candidate_type == "thread":
        return "thread"
    if candidate_type != "fact":
        raise ValueError(f"Unsupported candidate type for confirmed fact mapping: {candidate_type}")

    fact_type = agent_item.get("fact_type")
    companion_category = candidate["content"].get("metadata", {}).get("companion_category")
    if fact_type == "relationship":
        return "relationship"
    if fact_type == "preference":
        return "preference"
    if fact_type in {"trait", "background", "constraint"}:
        if companion_category == "important_person":
            return "relationship"
        return "identity"
    return "identity"


def _domain_for_candidate(candidate: dict[str, Any], fact_type: str) -> str:
    candidate_type = candidate["candidate_type"]
    content = candidate["content"]
    companion_category = content.get("metadata", {}).get("companion_category")
    projects = content.get("links", {}).get("projects", [])
    people = content.get("links", {}).get("people", [])

    if candidate_type in {"task", "reminder"}:
        return "obligations"
    if candidate_type == "habit":
        return "habits"
    if candidate_type in {"event", "invitation"}:
        return "events"
    if candidate_type == "state":
        return "state"
    if candidate_type == "thread":
        if companion_category in {"relationship_context", "ask_about_later"} or people:
            return "people"
        if projects:
            return "workstreams"
        return "obligations"

    if fact_type == "relationship":
        return "people"
    if companion_category in {"communication_preference", "tone_preference", "comfort_preference", "encouragement_style", "avoid_topic", "sensitivity_boundary"}:
        return "profile"
    if companion_category == "meaningful_routine":
        return "habits"
    if companion_category in {"aspiration", "hope"}:
        return "goals"
    if projects:
        return "workstreams"
    return "profile"


def _timeline_event_type_for_fact_type(fact_type: str) -> str:
    if fact_type == "task":
        return "task_confirmed"
    if fact_type == "reminder":
        return "fact_learned"
    if fact_type == "habit":
        return "fact_learned"
    if fact_type == "event":
        return "event_confirmed"
    if fact_type == "state":
        return "state_change"
    if fact_type == "relationship":
        return "relationship_update"
    return "fact_learned"


def _timeline_type_for_fact_type(fact_type: str, domain: str) -> str:
    if fact_type == "event":
        return "calendar"
    if fact_type == "relationship" or domain == "people":
        return "relationship"
    if fact_type == "state":
        return "interaction"
    if domain in {"obligations", "events", "workstreams", "goals"}:
        return "user_life"
    return "system"


def _candidate_is_structurally_valid(candidate: dict[str, Any]) -> bool:
    content = candidate.get("content")
    if not isinstance(content, dict):
        return False
    if content.get("schema_version") != "v1":
        return False
    expected_type = candidate.get("candidate_type")
    if expected_type in {"habit", "reminder"}:
        expected_type = "task"
    if content.get("item_type") != expected_type:
        return False
    evidence = content.get("evidence", {})
    return isinstance(evidence.get("raw_evidence"), str) and bool(evidence["raw_evidence"].strip())


def _has_temporal_ambiguity(candidate: dict[str, Any]) -> bool:
    time = candidate["content"].get("time", {})
    return bool(time.get("time_text") or time.get("date_resolution_basis"))


def _has_suspicious_temporal_values(candidate: dict[str, Any], now: datetime) -> bool:
    if _has_temporal_ambiguity(candidate):
        return True

    content = candidate["content"]
    time = content.get("time", {})
    agent_item = content.get("metadata", {}).get("agent_item", {})
    candidate_type = candidate["candidate_type"]
    parsed_values = [
        _parse_datetime(time.get("due_date")),
        _parse_datetime(time.get("reminder_at")),
        _parse_datetime(time.get("date")),
    ]
    parsed_values = [value for value in parsed_values if value is not None]
    if not parsed_values:
        return False

    comparison_now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    raw_evidence = str(candidate.get("raw_evidence", "")).lower()
    for value in parsed_values:
        if value < comparison_now - timedelta(days=180):
            return True
        if candidate_type in {"task", "event", "invitation", "reminder", "habit"} and not agent_item.get("is_past") and value < comparison_now - timedelta(days=1):
            return True
        if any(marker in raw_evidence for marker in RELATIVE_TIME_MARKERS) and value.year < comparison_now.year:
            return True
    return False


def _is_explicit_high_sensitivity_boundary(candidate: dict[str, Any]) -> bool:
    content = candidate.get("content", {})
    metadata = content.get("metadata", {})
    companion_category = metadata.get("companion_category")
    if companion_category not in {"avoid_topic", "sensitivity_boundary"}:
        return False

    raw_evidence = str(candidate.get("raw_evidence") or content.get("evidence", {}).get("raw_evidence") or "").lower()
    explicit_markers = (
        "please don't",
        "do not",
        "don't",
        "dont",
        "unless i mention",
        "unless i bring",
        "unless i raise",
        "don't bring up",
        "do not bring up",
    )
    return any(marker in raw_evidence for marker in explicit_markers)


def should_auto_confirm(candidate: dict[str, Any], *, now: datetime) -> bool:
    if candidate["confidence"] < 0.8:
        return False
    if candidate["needs_confirmation"]:
        return False
    if not _candidate_is_structurally_valid(candidate):
        return False
    if _has_suspicious_temporal_values(candidate, now):
        return False

    content = candidate["content"]
    sensitivity = content.get("sensitivity")
    if sensitivity == "high" and not _is_explicit_high_sensitivity_boundary(candidate):
        return False
    return True


async def fetch_active_confirmed_facts(
    database: Database,
    *,
    user_id: str,
    candidate_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = await database.fetch(
        """
        SELECT *
        FROM confirmed_facts
        WHERE user_id = $1 AND status = 'active'::fact_status
        ORDER BY last_seen_at DESC NULLS LAST, first_seen_at DESC NULLS LAST
        LIMIT $2
        """,
        user_id,
        limit,
    )
    if candidate_type is None:
        return rows
    if candidate_type in {"event", "invitation"}:
        allowed = {"event"}
    elif candidate_type == "fact":
        allowed = {"preference", "relationship", "identity"}
    else:
        allowed = {candidate_type}
    return [row for row in rows if row.get("fact_type") in allowed][:limit]


async def fetch_pending_candidates(
    database: Database,
    *,
    user_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM candidates
        WHERE user_id = $1 AND status = 'pending'::candidate_status
        ORDER BY created_at, id
        LIMIT $2
        """,
        user_id,
        limit,
    )


async def fetch_confirmed_fact_for_source(
    database: Database,
    *,
    user_id: str,
    source_id: UUID,
    fact_type: str,
) -> dict[str, Any] | None:
    rows = await database.fetch(
        """
        SELECT *
        FROM confirmed_facts
        WHERE user_id = $1 AND status = 'active'::fact_status
        ORDER BY last_seen_at DESC NULLS LAST, first_seen_at DESC NULLS LAST
        """,
        user_id,
    )
    for row in rows:
        if row.get("fact_type") != fact_type:
            continue
        source_ids = {str(item) for item in (row.get("source_ids") or [])}
        if str(source_id) in source_ids:
            return row
    return None


async def _timeline_event_exists(
    database: Database,
    *,
    user_id: str,
    source_id: UUID,
    event_type: str,
    title: str,
) -> bool:
    rows = await database.fetch(
        """
        SELECT *
        FROM timeline_events
        WHERE user_id = $1
        ORDER BY observed_at DESC NULLS LAST, occurred_at DESC NULLS LAST
        """,
        user_id,
    )
    for row in rows:
        if row.get("source_id") == source_id and row.get("event_type") == event_type and row.get("title") == title:
            return True
    return False


async def update_candidate_reconciliation(
    database: Database,
    *,
    candidate_id: UUID,
    instruction: str,
    target_id: UUID | None,
) -> None:
    await database.execute(
        """
        UPDATE candidates
        SET reconciliation_instruction = $2::reconciliation_instruction,
            merge_target_id = $3
        WHERE id = $1
        """,
        candidate_id,
        instruction,
        target_id,
    )


async def fetch_relevant_existing_facts_for_candidate(
    database: Database,
    candidate: dict[str, Any],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    return await fetch_active_confirmed_facts(
        database,
        user_id=candidate["user_id"],
        candidate_type=candidate["candidate_type"],
        limit=limit,
    )


async def reconcile_candidates(
    database: Database,
    *,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    instructions: list[dict[str, Any]] = []
    for candidate in candidates:
        existing_facts = await fetch_relevant_existing_facts_for_candidate(database, candidate)
        candidate_payload = {
            "id": str(candidate["id"]),
            "user_id": candidate["user_id"],
            "source_id": str(candidate["source_id"]),
            "candidate_type": candidate["candidate_type"],
            "content": candidate["content"],
            "raw_evidence": candidate["raw_evidence"],
            "confidence": candidate["confidence"],
            "needs_confirmation": candidate["needs_confirmation"],
            "status": candidate["status"],
            "created_at": candidate["created_at"],
        }
        fact_payloads = [
            {
                "id": str(fact["id"]),
                "user_id": fact["user_id"],
                "fact_type": fact["fact_type"],
                "domain": fact["domain"],
                "content": fact["content"],
                "confidence": fact["confidence"],
                "status": fact["status"],
                "source_ids": [str(source_id) for source_id in fact.get("source_ids", [])],
            }
            for fact in existing_facts
        ]
        result = reconciliation_agent.run(
            new_candidates=[candidate_payload],
            existing_facts=fact_payloads,
        )[0]
        if result["instruction"] in {"MERGE", "UPDATE"} and result.get("target_id"):
            target_fact = next((fact for fact in existing_facts if str(fact["id"]) == result["target_id"]), None)
            if target_fact and _is_ambiguous_entity_merge(candidate, target_fact):
                result = {
                    **result,
                    "instruction": "CREATE",
                    "target_id": None,
                    "reason": f"{result.get('reason', '')} Ambiguous same-name entity context kept distinct.".strip(),
                }
        await update_candidate_reconciliation(
            database,
            candidate_id=candidate["id"],
            instruction=result["instruction"],
            target_id=UUID(result["target_id"]) if result["target_id"] else None,
        )
        instructions.append(result)
    return instructions


async def _insert_timeline_event(
    database: Database,
    *,
    candidate: dict[str, Any],
    fact_id: UUID,
    fact_type: str,
    domain: str,
    confidence: float,
    observed_at: datetime,
) -> None:
    event_type = _timeline_event_type_for_fact_type(fact_type)
    title = _title_for_timeline(candidate, fact_type)
    if await _timeline_event_exists(
        database,
        user_id=candidate["user_id"],
        source_id=candidate["source_id"],
        event_type=event_type,
        title=title,
    ):
        return
    occurred_at = (
        _parse_datetime(candidate["content"].get("time", {}).get("date"))
        or _parse_datetime(candidate["content"].get("time", {}).get("due_date"))
        or observed_at.replace(tzinfo=timezone.utc)
    )
    occurred_at_naive = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    observed_at_naive = observed_at.astimezone(timezone.utc).replace(tzinfo=None)
    event_id = uuid4()
    event_row = {
        "id": event_id,
        "user_id": candidate["user_id"],
        "event_type": event_type,
        "timeline_type": _timeline_type_for_fact_type(fact_type, domain),
        "title": title,
        "summary": _summary_for_timeline(candidate),
        "occurred_at": occurred_at_naive,
        "observed_at": observed_at_naive,
        "source_id": candidate["source_id"],
        "related_fact_ids": [fact_id],
        "status": "current",
        "confidence": confidence,
        "content": candidate.get("content") or {},
    }
    await database.execute(
        """
        INSERT INTO timeline_events (
            id, user_id, event_type, timeline_type, title, summary,
            occurred_at, observed_at, source_id, related_fact_ids, status, confidence
        ) VALUES (
            $1, $2, $3::event_type, $4::timeline_type, $5, $6,
            $7, $8, $9, $10, $11::timeline_status, $12
        )
        """,
        event_row["id"],
        event_row["user_id"],
        event_row["event_type"],
        event_row["timeline_type"],
        event_row["title"],
        event_row["summary"],
        event_row["occurred_at"],
        event_row["observed_at"],
        event_row["source_id"],
        event_row["related_fact_ids"],
        event_row["status"],
        event_row["confidence"],
    )
    await embeddings.index_timeline_event(database, event_row)


def _candidate_provenance(candidate: dict[str, Any]) -> dict[str, Any]:
    provenance = candidate.get("provenance")
    if isinstance(provenance, dict) and provenance:
        return provenance
    return normalize_provenance(
        source_id=candidate.get("source_id"),
        source_type=candidate.get("source_type"),
        original_text=candidate.get("original_text") or candidate.get("raw_evidence"),
        who_said_it=candidate.get("who_said_it"),
        channel=candidate.get("channel"),
        conversation_id=candidate.get("conversation_id"),
        created_from=candidate.get("created_from"),
        source_ids=[candidate.get("source_id")] if candidate.get("source_id") else [],
    )


async def _create_confirmed_fact(
    database: Database,
    *,
    candidate: dict[str, Any],
    now: datetime,
) -> UUID:
    fact_type = _fact_type_for_candidate(candidate)
    domain = _domain_for_candidate(candidate, fact_type)
    content = candidate["content"]
    existing_fact = await fetch_confirmed_fact_for_source(
        database,
        user_id=candidate["user_id"],
        source_id=candidate["source_id"],
        fact_type=fact_type,
    )
    if existing_fact:
        await database.execute(
            """
            UPDATE candidates
            SET status = 'confirmed'::candidate_status
            WHERE id = $1
            """,
            candidate["id"],
        )
        return existing_fact["id"]

    fact_id = uuid4()
    first_seen_at = candidate["created_at"]
    now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)
    provenance = _candidate_provenance(candidate)
    operational = extract_operational_fields(
        item_type=fact_type,
        content=content,
        provenance=provenance,
        record_status="active",
    )
    await database.execute(
        """
        INSERT INTO confirmed_facts (
            id, user_id, fact_type, domain, content, confidence,
            first_seen_at, last_seen_at, last_confirmed_at, source_ids,
            status, user_corrected, correction_note, expires_at,
            structured_content, source_type, primary_source_id, who_said_it, original_text,
            channel, conversation_id, created_from, provenance,
            starts_at, ends_at, due_at, remind_at, timezone, recurrence_rule,
            completed_at, cancelled_at, priority, follow_up_needed,
            claimed_by_entity_id, subject_entity_id, claim_type, interaction_mode
        ) VALUES (
            $1, $2, $3::fact_type, $4::fact_domain, $5::jsonb, $6,
            $7, $8, $9, $10, $11::fact_status, $12, $13, $14,
            $15::jsonb, $16, $17, $18, $19,
            $20, $21, $22::jsonb, $23::jsonb,
            $24, $25, $26, $27, $28, $29,
            $30, $31, $32, $33,
            $34, $35, $36, $37
        )
        """,
        fact_id,
        candidate["user_id"],
        fact_type,
        domain,
        content,
        candidate["confidence"],
        first_seen_at,
        now_naive,
        now_naive,
        [candidate["source_id"]],
        "active",
        False,
        None,
        _parse_datetime(content.get("lifecycle", {}).get("expires_at")).replace(tzinfo=None) if _parse_datetime(content.get("lifecycle", {}).get("expires_at")) else None,
        operational["structured_content"],
        operational["source_type"],
        UUID(operational["source_id"]) if operational.get("source_id") else None,
        operational["who_said_it"],
        operational["original_text"],
        operational["channel"],
        operational["conversation_id"],
        operational["created_from"] or {},
        operational["provenance"] or {},
        parse_datetime(operational["starts_at"]).replace(tzinfo=None) if parse_datetime(operational["starts_at"]) else None,
        parse_datetime(operational["ends_at"]).replace(tzinfo=None) if parse_datetime(operational["ends_at"]) else None,
        parse_datetime(operational["due_at"]).replace(tzinfo=None) if parse_datetime(operational["due_at"]) else None,
        parse_datetime(operational["remind_at"]).replace(tzinfo=None) if parse_datetime(operational["remind_at"]) else None,
        operational["timezone"],
        operational["recurrence_rule"],
        parse_datetime(operational["completed_at"]).replace(tzinfo=None) if parse_datetime(operational["completed_at"]) else None,
        parse_datetime(operational["cancelled_at"]).replace(tzinfo=None) if parse_datetime(operational["cancelled_at"]) else None,
        operational["priority"],
        operational["follow_up_needed"],
        candidate.get("claimed_by_entity_id"),
        candidate.get("subject_entity_id"),
        candidate.get("claim_type"),
        candidate.get("interaction_mode"),
    )
    fact_row = {
        "id": fact_id,
        "user_id": candidate["user_id"],
        "fact_type": fact_type,
        "domain": domain,
        "content": content,
        "confidence": candidate["confidence"],
        "first_seen_at": first_seen_at,
        "last_seen_at": now_naive,
        "last_confirmed_at": now_naive,
        "source_ids": [candidate["source_id"]],
        "status": "active",
        "structured_content": operational["structured_content"],
        "source_type": operational["source_type"],
        "primary_source_id": UUID(operational["source_id"]) if operational.get("source_id") else None,
        "who_said_it": operational["who_said_it"],
        "original_text": operational["original_text"],
        "channel": operational["channel"],
        "conversation_id": operational["conversation_id"],
        "created_from": operational["created_from"],
        "provenance": operational["provenance"],
        "starts_at": parse_datetime(operational["starts_at"]).replace(tzinfo=None) if parse_datetime(operational["starts_at"]) else None,
        "ends_at": parse_datetime(operational["ends_at"]).replace(tzinfo=None) if parse_datetime(operational["ends_at"]) else None,
        "due_at": parse_datetime(operational["due_at"]).replace(tzinfo=None) if parse_datetime(operational["due_at"]) else None,
        "remind_at": parse_datetime(operational["remind_at"]).replace(tzinfo=None) if parse_datetime(operational["remind_at"]) else None,
        "timezone": operational["timezone"],
        "recurrence_rule": operational["recurrence_rule"],
        "completed_at": parse_datetime(operational["completed_at"]).replace(tzinfo=None) if parse_datetime(operational["completed_at"]) else None,
        "cancelled_at": parse_datetime(operational["cancelled_at"]).replace(tzinfo=None) if parse_datetime(operational["cancelled_at"]) else None,
        "priority": operational["priority"],
        "follow_up_needed": operational["follow_up_needed"],
        "user_corrected": False,
        "correction_note": None,
        "expires_at": _parse_datetime(content.get("lifecycle", {}).get("expires_at")).replace(tzinfo=None) if _parse_datetime(content.get("lifecycle", {}).get("expires_at")) else None,
        "claimed_by_entity_id": candidate.get("claimed_by_entity_id"),
        "subject_entity_id": candidate.get("subject_entity_id"),
        "claim_type": candidate.get("claim_type"),
        "interaction_mode": candidate.get("interaction_mode"),
    }
    await embeddings.index_confirmed_fact(database, fact_row)
    await _insert_timeline_event(
        database,
        candidate=candidate,
        fact_id=fact_id,
        fact_type=fact_type,
        domain=domain,
        confidence=candidate["confidence"],
        observed_at=now,
    )
    await database.execute(
        """
        UPDATE candidates
        SET status = 'confirmed'::candidate_status
        WHERE id = $1
        """,
        candidate["id"],
    )
    return fact_id


async def _merge_or_update_confirmed_fact(
    database: Database,
    *,
    candidate: dict[str, Any],
    existing_fact: dict[str, Any],
    instruction: str,
    confidence_delta: float,
    now: datetime,
) -> None:
    now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)
    new_confidence = max(0.0, min(1.0, float(existing_fact["confidence"]) + confidence_delta))
    existing_sources = [UUID(str(source_id)) for source_id in (existing_fact.get("source_ids") or [])]
    if candidate["source_id"] not in existing_sources:
        existing_sources.append(candidate["source_id"])

    content = existing_fact["content"]
    if instruction == "UPDATE":
        content = candidate["content"]
    content = _merged_content(existing_fact["content"], candidate["content"], instruction=instruction)

    expires_at = _parse_datetime(content.get("lifecycle", {}).get("expires_at"))
    provenance = _candidate_provenance(candidate)
    operational = extract_operational_fields(
        item_type=existing_fact["fact_type"],
        content=content,
        provenance=provenance,
        record_status=existing_fact.get("status"),
    )

    # UPDATE CLAIM TYPE and CONFIDENCE
    claim_type = existing_fact.get("claim_type")
    if instruction == "UPDATE" and candidate.get("claim_type") == "direct" and existing_fact.get("claim_type") == "interpretation":
        claim_type = "direct" # Upgraded by user confirmation

    await database.execute(
        """
        UPDATE confirmed_facts
        SET content = $2::jsonb,
            confidence = $3,
            last_seen_at = $4,
            last_confirmed_at = $5,
            source_ids = $6,
            expires_at = $7,
            claim_type = $8,
            structured_content = $9::jsonb,
            source_type = $10,
            primary_source_id = $11,
            who_said_it = $12,
            original_text = $13,
            channel = $14,
            conversation_id = $15,
            created_from = $16::jsonb,
            provenance = $17::jsonb,
            starts_at = $18,
            ends_at = $19,
            due_at = $20,
            remind_at = $21,
            timezone = $22,
            recurrence_rule = $23,
            completed_at = $24,
            cancelled_at = $25,
            priority = $26,
            follow_up_needed = $27
        WHERE id = $1
        """,
        existing_fact["id"],
        content,
        new_confidence,
        now_naive,
        now_naive,
        existing_sources,
        expires_at.replace(tzinfo=None) if expires_at else None,
        claim_type,
        operational["structured_content"],
        operational["source_type"],
        UUID(operational["source_id"]) if operational.get("source_id") else None,
        operational["who_said_it"],
        operational["original_text"],
        operational["channel"],
        operational["conversation_id"],
        operational["created_from"] or {},
        operational["provenance"] or {},
        parse_datetime(operational["starts_at"]).replace(tzinfo=None) if parse_datetime(operational["starts_at"]) else None,
        parse_datetime(operational["ends_at"]).replace(tzinfo=None) if parse_datetime(operational["ends_at"]) else None,
        parse_datetime(operational["due_at"]).replace(tzinfo=None) if parse_datetime(operational["due_at"]) else None,
        parse_datetime(operational["remind_at"]).replace(tzinfo=None) if parse_datetime(operational["remind_at"]) else None,
        operational["timezone"],
        operational["recurrence_rule"],
        parse_datetime(operational["completed_at"]).replace(tzinfo=None) if parse_datetime(operational["completed_at"]) else None,
        parse_datetime(operational["cancelled_at"]).replace(tzinfo=None) if parse_datetime(operational["cancelled_at"]) else None,
        operational["priority"],
        operational["follow_up_needed"],
    )
    await embeddings.index_confirmed_fact(
        database,
        {
            **existing_fact,
            "content": content,
            "structured_content": operational["structured_content"],
            "confidence": new_confidence,
            "last_seen_at": now_naive,
            "last_confirmed_at": now_naive,
            "source_ids": existing_sources,
            "expires_at": expires_at.replace(tzinfo=None) if expires_at else None,
            "claim_type": claim_type,
            "source_type": operational["source_type"],
            "primary_source_id": UUID(operational["source_id"]) if operational.get("source_id") else None,
            "who_said_it": operational["who_said_it"],
            "original_text": operational["original_text"],
            "channel": operational["channel"],
            "conversation_id": operational["conversation_id"],
            "created_from": operational["created_from"],
            "provenance": operational["provenance"],
            "starts_at": parse_datetime(operational["starts_at"]).replace(tzinfo=None) if parse_datetime(operational["starts_at"]) else None,
            "ends_at": parse_datetime(operational["ends_at"]).replace(tzinfo=None) if parse_datetime(operational["ends_at"]) else None,
            "due_at": parse_datetime(operational["due_at"]).replace(tzinfo=None) if parse_datetime(operational["due_at"]) else None,
            "remind_at": parse_datetime(operational["remind_at"]).replace(tzinfo=None) if parse_datetime(operational["remind_at"]) else None,
            "timezone": operational["timezone"],
            "recurrence_rule": operational["recurrence_rule"],
            "completed_at": parse_datetime(operational["completed_at"]).replace(tzinfo=None) if parse_datetime(operational["completed_at"]) else None,
            "cancelled_at": parse_datetime(operational["cancelled_at"]).replace(tzinfo=None) if parse_datetime(operational["cancelled_at"]) else None,
            "priority": operational["priority"],
            "follow_up_needed": operational["follow_up_needed"],
        },
    )
    await _insert_timeline_event(
        database,
        candidate=candidate,
        fact_id=existing_fact["id"],
        fact_type=existing_fact["fact_type"],
        domain=existing_fact["domain"],
        confidence=new_confidence,
        observed_at=now,
    )
    await database.execute(
        """
        UPDATE candidates
        SET status = 'confirmed'::candidate_status
        WHERE id = $1
        """,
        candidate["id"],
    )


async def apply_reconciliation_results(
    database: Database,
    *,
    candidates: list[dict[str, Any]],
    instructions: list[dict[str, Any]],
    now: datetime | None = None,
) -> None:
    current_time = now or datetime.now(timezone.utc)
    candidate_map = {str(candidate["id"]): candidate for candidate in candidates}

    for instruction in instructions:
        candidate = candidate_map[instruction["candidate_id"]]
        action = instruction["instruction"]
        target_id = instruction["target_id"]
        await update_candidate_reconciliation(
            database,
            candidate_id=candidate["id"],
            instruction=action,
            target_id=UUID(target_id) if target_id else None,
        )

        if action == "DISMISS":
            await database.execute(
                """
                UPDATE candidates
                SET status = 'dismissed'::candidate_status
                WHERE id = $1
                """,
                candidate["id"],
            )
            continue

        if not should_auto_confirm(candidate, now=current_time):
            continue

        if action == "CREATE":
            await _create_confirmed_fact(database, candidate=candidate, now=current_time)
            continue

        if not target_id:
            raise ValueError("MERGE and UPDATE instructions require a target_id.")

        existing_fact = await database.fetchone(
            """
            SELECT *
            FROM confirmed_facts
            WHERE id = $1
            """,
            UUID(target_id),
        )
        if not existing_fact:
            raise ValueError(f"Target confirmed_fact not found: {target_id}")

        await _merge_or_update_confirmed_fact(
            database,
            candidate=candidate,
            existing_fact=existing_fact,
            instruction=action,
            confidence_delta=float(instruction["confidence_delta"]),
            now=current_time,
        )
