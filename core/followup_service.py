from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import _fetch_confirmed_facts, _fetch_fact_by_id, _insert_timeline_event, _update_fact_record
from core.item_shapes import _thread_snoozed, _thread_structured
from core.item_utils import _refresh_operational_row, _to_iso
from core.operational import parse_datetime


def _coerce_utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return parse_datetime(value)


def _thread_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("content") or {}).get("metadata") or {}


def _thread_links(row: dict[str, Any]) -> dict[str, list[str]]:
    links = (row.get("content") or {}).get("links") or {}
    payload: dict[str, list[str]] = {}
    for key in ("people", "projects", "topics"):
        values = links.get(key, [])
        normalized: list[str] = []
        seen: set[str] = set()
        if not isinstance(values, list):
            values = []
        for value in values:
            cleaned = str(value or "").strip()
            if not cleaned:
                continue
            token = cleaned.lower()
            if token in seen:
                continue
            seen.add(token)
            normalized.append(cleaned)
        payload[key] = normalized
    return payload


def _follow_up_hours(row: dict[str, Any]) -> int | None:
    content = row.get("content") or {}
    lifecycle = content.get("lifecycle") or {}
    time_payload = content.get("time") or {}
    metadata = _thread_metadata(row)
    structured = _thread_structured(row)
    for value in (
        lifecycle.get("follow_up_after_hours"),
        time_payload.get("follow_up_after_hours"),
        metadata.get("follow_up_after_hours"),
        structured.get("follow_up_after_hours"),
    ):
        if value in (None, ""):
            continue
        try:
            hours = int(value)
        except (TypeError, ValueError):
            continue
        if hours > 0:
            return hours
    return None


def _follow_up_anchor(row: dict[str, Any]) -> datetime | None:
    structured = _thread_structured(row)
    metadata = _thread_metadata(row)
    for value in (
        row.get("last_resurfaced_at"),
        structured.get("last_resurfaced_at"),
        metadata.get("last_resurfaced_at"),
        row.get("last_progressed_at"),
        structured.get("last_progressed_at"),
        metadata.get("last_progressed_at"),
        row.get("last_seen_at"),
        row.get("last_confirmed_at"),
        row.get("first_seen_at"),
    ):
        coerced = _coerce_utc(value)
        if coerced:
            return coerced
    return None


def thread_follow_up_due_at(row: dict[str, Any]) -> datetime | None:
    anchor = _follow_up_anchor(row)
    hours = _follow_up_hours(row)
    if not anchor or hours is None:
        return None
    return anchor + timedelta(hours=hours)


def thread_follow_up_due(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    if row.get("fact_type") != "thread":
        return False
    if row.get("status") != "active":
        return False
    if not row.get("follow_up_needed", True):
        return False
    metadata = _thread_metadata(row)
    open_loop_status = str(metadata.get("open_loop_status") or _thread_structured(row).get("open_loop_status") or "active").lower()
    if open_loop_status not in {"active", "unresolved", "open"}:
        return False
    current = _coerce_utc(now) or datetime.now(timezone.utc)
    if _thread_snoozed(row, now=current):
        return False
    due_at = thread_follow_up_due_at(row)
    if not due_at:
        return False
    return due_at <= current


def _source_refs(row: dict[str, Any]) -> list[str]:
    return [f"outbox:{value}" for value in row.get("source_ids", []) if value]


def _overdue_hours(due_at: datetime | None, *, now: datetime) -> float:
    if not due_at:
        return 0.0
    delta = now - due_at
    if delta.total_seconds() <= 0:
        return 0.0
    return round(delta.total_seconds() / 3600, 2)


def build_follow_up_packet(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    current = _coerce_utc(now) or datetime.now(timezone.utc)
    due_at = thread_follow_up_due_at(row)
    metadata = _thread_metadata(row)
    structured = _thread_structured(row)
    links = _thread_links(row)
    return {
        "thread_id": str(row["id"]),
        "title": (row.get("content") or {}).get("title"),
        "summary": (row.get("content") or {}).get("summary"),
        "follow_up_question": metadata.get("follow_up_question") or "Any update?",
        "due_at": _to_iso(due_at),
        "overdue_hours": _overdue_hours(due_at, now=current),
        "thread_type": row.get("thread_type") or structured.get("thread_type"),
        "actionability": row.get("actionability") or structured.get("actionability"),
        "next_move": row.get("next_move") or structured.get("next_move") or "follow_up",
        "surface_reason": structured.get("surface_reason") or metadata.get("surface_reason") or "This thread is still open and due for follow-up.",
        "linked_people": links["people"],
        "linked_projects": links["projects"],
        "linked_topics": links["topics"],
        "source_refs": _source_refs(row),
        "confidence": float(row.get("confidence", 0.0)),
        "last_seen_at": _to_iso(row.get("last_seen_at")),
        "last_resurfaced_at": _to_iso(row.get("last_resurfaced_at") or structured.get("last_resurfaced_at") or metadata.get("last_resurfaced_at")),
    }


async def due_follow_up_rows(
    database: Database,
    *,
    user_id: str,
    now: datetime | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    current = _coerce_utc(now) or datetime.now(timezone.utc)
    rows = await _fetch_confirmed_facts(database, user_id=user_id, fact_types=["thread"])
    due_rows = [row for row in rows if thread_follow_up_due(row, now=current)]
    due_rows.sort(
        key=lambda row: (
            thread_follow_up_due_at(row) or datetime.max.replace(tzinfo=timezone.utc),
            -float(row.get("confidence", 0.0)),
        )
    )
    return due_rows[:limit]


async def due_follow_up_packets(
    database: Database,
    *,
    user_id: str,
    now: datetime | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    current = _coerce_utc(now) or datetime.now(timezone.utc)
    rows = await due_follow_up_rows(database, user_id=user_id, now=current, limit=limit)
    return [build_follow_up_packet(row, now=current) for row in rows]


async def mark_thread_resurfaced(
    database: Database,
    *,
    user_id: str,
    item_id: UUID,
    surfaced_at: datetime | None = None,
    surface_reason: str | None = None,
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if not fact or fact.get("fact_type") != "thread":
        raise HTTPException(status_code=404, detail="Thread not found.")
    moment_utc = _coerce_utc(surfaced_at) or datetime.now(timezone.utc)
    moment = moment_utc.replace(tzinfo=None)
    iso_moment = moment.replace(tzinfo=timezone.utc).isoformat()
    metadata = (fact.get("content") or {}).setdefault("metadata", {})
    metadata["last_resurfaced_at"] = iso_moment
    if surface_reason:
        metadata["surface_reason"] = surface_reason
    _refresh_operational_row(
        fact,
        item_type="thread",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        source_ids=fact.get("source_ids"),
    )
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="thread_progressed",
        timeline_type="system",
        title=(fact.get("content") or {}).get("title") or "Thread resurfaced",
        summary=surface_reason or ((fact.get("content") or {}).get("summary") or ""),
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact.get("confidence", 0.0),
    )
    return fact
