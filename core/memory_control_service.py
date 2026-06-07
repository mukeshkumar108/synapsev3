from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import (
    _fetch_candidate_by_id,
    _fetch_fact_by_id,
    _insert_confirmed_fact,
    _insert_outbox_reference,
    _insert_timeline_event,
    _update_candidate_record,
    _update_fact_record,
)
from core.item_shapes import _build_content, _canonical_item
from core.item_utils import _now_naive, _refresh_operational_row


async def create_avoid_topic_memory(database: Database, *, user_id: str, note: str) -> dict[str, Any]:
    content = _build_content(
        item_type="fact",
        title="user",
        summary=note,
        links={"projects": [note]},
        source="memory_control",
        requires_confirmation=False,
        companion_category="avoid_topic",
        note=note,
    )
    outbox_id = await _insert_outbox_reference(
        database,
        user_id=user_id,
        source="memory_control",
        raw_content=note,
        metadata={"internal_source": "memory_control", "item_class": "memory_control", "action": "avoid_topic"},
    )
    row = await _insert_confirmed_fact(
        database,
        user_id=user_id,
        fact_type="identity",
        domain="profile",
        content=content,
        confidence=1.0,
        source_ids=[outbox_id],
        status="active",
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="fact_learned",
        timeline_type="system",
        title="Avoid topic updated",
        summary=note,
        source_id=outbox_id,
        related_fact_ids=[row["id"]],
        confidence=1.0,
    )
    return _canonical_item(source_kind="confirmed_fact", row=row, item_class="memory_control")


async def apply_memory_control(
    database: Database,
    *,
    user_id: str,
    action: str,
    target_id: UUID | None,
    target_type: str,
    note: str | None,
) -> dict[str, Any]:
    if action == "avoid_topic":
        return await create_avoid_topic_memory(database, user_id=user_id, note=note or "Avoid this topic.")

    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=target_id) if target_id else None
    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=target_id) if target_id else None
    if not fact and not candidate:
        raise HTTPException(status_code=404, detail="Target item not found.")

    if candidate:
        if action in {"forget", "dismiss"}:
            candidate["status"] = "dismissed"
            if note:
                candidate["content"].setdefault("metadata", {})["control_note"] = note
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="item_dismissed",
                timeline_type="system",
                title=candidate["content"].get("title") or "Candidate dismissed",
                summary=note or candidate["content"].get("summary") or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class=target_type if target_type in {"action", "event"} else "memory_control")
        if action == "correct":
            candidate["status"] = "dismissed"
            candidate["content"].setdefault("metadata", {})["control_note"] = note
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="user_correction",
                timeline_type="system",
                title=candidate["content"].get("title") or "Candidate corrected",
                summary=note or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class=target_type if target_type in {"action", "event"} else "memory_control")
        raise HTTPException(status_code=400, detail="Unsupported memory control for candidate.")

    assert fact is not None
    if action in {"forget", "dismiss"}:
        fact["status"] = "dismissed"
        fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
        if note:
            fact["correction_note"] = note
        event_type = "item_dismissed"
    elif action == "correct":
        fact["status"] = "corrected"
        fact["user_corrected"] = True
        fact["correction_note"] = note
        event_type = "user_correction"
    elif action == "resolve_loop":
        fact["status"] = "historical"
        fact["content"].setdefault("metadata", {})["open_loop_status"] = "resolved"
        fact["content"]["metadata"]["item_status"] = "completed"
        fact["follow_up_needed"] = False
        _refresh_operational_row(fact, item_type=fact.get("fact_type") or "thread", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
        event_type = "thread_resolved"
    else:
        raise HTTPException(status_code=400, detail="Unsupported memory control.")
    fact["last_seen_at"] = _now_naive()
    fact["last_confirmed_at"] = fact["last_seen_at"]
    await _update_fact_record(database, fact)
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type=event_type,
        timeline_type="system" if action != "resolve_loop" else "relationship",
        title=fact["content"].get("title") or "Memory control applied",
        summary=note or fact["content"].get("summary") or "",
        source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
        related_fact_ids=[fact["id"]],
        confidence=fact["confidence"],
    )
    return _canonical_item(source_kind="confirmed_fact", row=fact, item_class=target_type if target_type in {"action", "event"} else "memory_control")
