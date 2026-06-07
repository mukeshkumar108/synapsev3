from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from core.db import Database


DEFAULT_CONFIDENCE = 0.95
TENTATIVE_CONFIDENCE = 0.85


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


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _event_confidence(event: dict[str, Any]) -> float:
    return TENTATIVE_CONFIDENCE if event.get("status") == "tentative" else DEFAULT_CONFIDENCE


def _fact_status(event: dict[str, Any]) -> str:
    return "historical" if event.get("status") == "cancelled" else "active"


def _timeline_status(event: dict[str, Any]) -> str:
    return "historical" if event.get("status") == "cancelled" else "current"


def _event_summary(event: dict[str, Any]) -> str:
    title = event.get("title") or "Untitled event"
    status = event.get("status") or "confirmed"
    starts_at = event.get("starts_at")
    if status == "cancelled":
        return f"Cancelled calendar event: {title}"
    if event.get("all_day"):
        prefix = "Tentative all-day event" if status == "tentative" else "All-day event"
        return f"{prefix}: {title}"
    if starts_at:
        prefix = "Tentative event" if status == "tentative" else "Calendar event"
        return f"{prefix}: {title} at {starts_at}"
    return title


def _timeline_summary(event: dict[str, Any], action: str) -> str:
    title = event.get("title") or "Untitled event"
    if event.get("status") == "cancelled":
        return f"Calendar event import marked {title} as cancelled."
    if action == "created":
        return f"Imported calendar event {title}."
    return f"Updated calendar event {title} from provider import."


def _normalized_content(
    *,
    event: dict[str, Any],
    external_provider: str,
    external_calendar_id: str,
) -> dict[str, Any]:
    starts_at = event.get("starts_at")
    ends_at = event.get("ends_at")
    timezone_name = event.get("timezone")
    return {
        "schema_version": "v1",
        "item_type": "event",
        "title": event.get("title"),
        "summary": _event_summary(event),
        "salience": "high" if event.get("status") == "confirmed" else "medium",
        "priority": None,
        "urgency": None,
        "importance": "high" if event.get("status") == "confirmed" else "medium",
        "sensitivity": "low",
        "time": {
            "due_date": None,
            "reminder_at": None,
            "date": starts_at,
            "time": starts_at,
            "duration": None,
            "follow_up_after_hours": None,
            "stale_after_hours": None,
            "expires_at": ends_at,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "timezone": timezone_name,
            "all_day": bool(event.get("all_day")),
        },
        "links": {
            "people": event.get("participants", []),
            "projects": [],
            "related_facts": [],
            "related_threads": [],
        },
        "lifecycle": {
            "follow_up_after_hours": None,
            "stale_after_hours": None,
            "expires_at": ends_at,
        },
        "evidence": {
            "raw_evidence": event.get("description") or event.get("title") or "calendar event import",
            "source_turn_refs": [],
        },
        "metadata": {
            "companion_category": None,
            "agent_item": {
                "title": event.get("title"),
                "description": event.get("description"),
                "location": event.get("location"),
                "participants": event.get("participants", []),
                "organizer": event.get("organizer"),
                "status": event.get("status"),
                "all_day": bool(event.get("all_day")),
            },
            "source_type": "calendar",
            "external_provider": external_provider,
            "external_calendar_id": external_calendar_id,
            "external_id": event.get("external_id"),
            "external_updated_at": event.get("external_updated_at"),
            "etag": event.get("etag"),
            "calendar_status": event.get("status"),
            "raw": event.get("raw", {}),
        },
    }


async def _insert_outbox_row(
    database: Database,
    *,
    user_id: str,
    event: dict[str, Any],
    external_provider: str,
    external_calendar_id: str,
    now: datetime,
) -> UUID:
    source_id = uuid4()
    await database.execute(
        """
        INSERT INTO outbox (
            id, user_id, source_type, raw_content, received_at, status, retry_count, metadata
        ) VALUES ($1, $2, $3::outbox_source_type, $4, $5, $6::outbox_status, $7, $8::jsonb)
        """,
        source_id,
        user_id,
        "calendar",
        json.dumps(event, sort_keys=True, default=str),
        _naive_utc(now),
        "done",
        0,
        {
            "source_type": "calendar",
            "external_provider": external_provider,
            "external_calendar_id": external_calendar_id,
            "external_id": event.get("external_id"),
            "external_updated_at": event.get("external_updated_at"),
            "etag": event.get("etag"),
        },
    )
    return source_id


async def _fetch_existing_fact(
    database: Database,
    *,
    user_id: str,
    external_provider: str,
    external_calendar_id: str,
    external_id: str,
) -> dict[str, Any] | None:
    return await database.fetchone(
        """
        SELECT *
        FROM confirmed_facts
        WHERE user_id = $1
          AND fact_type = 'event'::fact_type
          AND content->'metadata'->>'source_type' = 'calendar'
          AND content->'metadata'->>'external_provider' = $2
          AND content->'metadata'->>'external_calendar_id' = $3
          AND content->'metadata'->>'external_id' = $4
        LIMIT 1
        """,
        user_id,
        external_provider,
        external_calendar_id,
        external_id,
    )


async def _insert_timeline_event(
    database: Database,
    *,
    user_id: str,
    source_id: UUID,
    fact_id: UUID,
    event: dict[str, Any],
    action: str,
    confidence: float,
    now: datetime,
) -> None:
    occurred_at = _parse_datetime(event.get("starts_at")) or now
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
        uuid4(),
        user_id,
        "event_confirmed",
        "calendar",
        event.get("title") or "Untitled event",
        _timeline_summary(event, action),
        _naive_utc(occurred_at),
        _naive_utc(now),
        source_id,
        [fact_id],
        _timeline_status(event),
        confidence,
    )


async def _create_fact(
    database: Database,
    *,
    user_id: str,
    source_id: UUID,
    content: dict[str, Any],
    confidence: float,
    fact_status: str,
    now: datetime,
) -> UUID:
    fact_id = uuid4()
    await database.execute(
        """
        INSERT INTO confirmed_facts (
            id, user_id, fact_type, domain, content, confidence,
            first_seen_at, last_seen_at, last_confirmed_at, source_ids,
            status, user_corrected, correction_note, expires_at
        ) VALUES (
            $1, $2, $3::fact_type, $4::fact_domain, $5::jsonb, $6,
            $7, $8, $9, $10, $11::fact_status, $12, $13, $14
        )
        """,
        fact_id,
        user_id,
        "event",
        "events",
        content,
        confidence,
        _naive_utc(now),
        _naive_utc(now),
        _naive_utc(now),
        [source_id],
        fact_status,
        False,
        None,
        _naive_utc(_parse_datetime(content.get("lifecycle", {}).get("expires_at"))),
    )
    return fact_id


async def _update_fact(
    database: Database,
    *,
    fact: dict[str, Any],
    source_id: UUID,
    content: dict[str, Any],
    confidence: float,
    fact_status: str,
    now: datetime,
) -> None:
    existing_sources = [UUID(str(value)) for value in (fact.get("source_ids") or [])]
    if source_id not in existing_sources:
        existing_sources.append(source_id)
    await database.execute(
        """
        UPDATE confirmed_facts
        SET content = $2::jsonb,
            confidence = $3,
            last_seen_at = $4,
            last_confirmed_at = $5,
            source_ids = $6,
            status = $7::fact_status,
            expires_at = $8
        WHERE id = $1
        """,
        fact["id"],
        content,
        confidence,
        _naive_utc(now),
        _naive_utc(now),
        existing_sources,
        fact_status,
        _naive_utc(_parse_datetime(content.get("lifecycle", {}).get("expires_at"))),
    )


async def import_calendar_events(
    database: Database,
    *,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    user_id = payload["user_id"]
    external_provider = payload["external_provider"]
    external_calendar_id = payload["external_calendar_id"]
    results: list[dict[str, Any]] = []
    created = 0
    updated = 0
    cancelled = 0

    for event in payload.get("events", []):
        source_id = await _insert_outbox_row(
            database,
            user_id=user_id,
            event=event,
            external_provider=external_provider,
            external_calendar_id=external_calendar_id,
            now=current_time,
        )
        content = _normalized_content(
            event=event,
            external_provider=external_provider,
            external_calendar_id=external_calendar_id,
        )
        confidence = _event_confidence(event)
        fact_status = _fact_status(event)
        existing = await _fetch_existing_fact(
            database,
            user_id=user_id,
            external_provider=external_provider,
            external_calendar_id=external_calendar_id,
            external_id=event["external_id"],
        )

        action = "created"
        fact_id: UUID
        if existing is None:
            fact_id = await _create_fact(
                database,
                user_id=user_id,
                source_id=source_id,
                content=content,
                confidence=confidence,
                fact_status=fact_status,
                now=current_time,
            )
            created += 1
        else:
            await _update_fact(
                database,
                fact=existing,
                source_id=source_id,
                content=content,
                confidence=confidence,
                fact_status=fact_status,
                now=current_time,
            )
            action = "updated"
            fact_id = existing["id"]
            updated += 1

        if event.get("status") == "cancelled":
            cancelled += 1

        await _insert_timeline_event(
            database,
            user_id=user_id,
            source_id=source_id,
            fact_id=fact_id,
            event=event,
            action=action,
            confidence=confidence,
            now=current_time,
        )
        results.append(
            {
                "external_id": event["external_id"],
                "source_id": str(source_id),
                "fact_id": str(fact_id),
                "action": action,
                "fact_status": fact_status,
                "calendar_status": event.get("status"),
                "confidence": confidence,
            }
        )

    return {
        "user_id": user_id,
        "source_type": "calendar",
        "external_provider": external_provider,
        "external_calendar_id": external_calendar_id,
        "created": created,
        "updated": updated,
        "cancelled": cancelled,
        "results": results,
    }
