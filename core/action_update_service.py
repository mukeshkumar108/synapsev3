from __future__ import annotations

from datetime import timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from core.db import Database
from core.item_repository import (
    _fetch_candidate_by_id,
    _fetch_fact_by_id,
    _insert_candidate,
    _insert_confirmed_fact,
    _insert_outbox_reference,
    _insert_timeline_event,
    _update_candidate_record,
    _update_fact_record,
)
from core.operational import apply_lifecycle_timestamp
from core.item_shapes import (
    _apply_item_updates,
    _build_content,
    _canonical_item,
    _event_type_for_completion,
    _kind_for_row,
)
from core.item_utils import _now_naive, _refresh_operational_row


async def create_action(
    database: Database,
    *,
    user_id: str,
    title: str,
    summary: str,
    due_at: str | None,
    priority: str | None,
    links: dict[str, Any] | None,
    source: str,
    requires_confirmation: bool,
) -> dict[str, Any]:
    content = _build_content(
        item_type="task",
        title=title,
        summary=summary,
        due_at=due_at,
        priority=priority,
        links=links,
        source=source,
        requires_confirmation=requires_confirmation,
    )
    outbox_id = await _insert_outbox_reference(
        database,
        user_id=user_id,
        source=source,
        raw_content=summary or title,
        metadata={"internal_source": source, "item_class": "action"},
    )
    if requires_confirmation:
        row = await _insert_candidate(
            database,
            user_id=user_id,
            source_id=outbox_id,
            candidate_type="task",
            content=content,
            confidence=0.99,
            needs_confirmation=True,
            source_type=source,
            created_from={"path": "create_action", "source": source},
        )
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type="fact_learned",
            timeline_type="user_life",
            title=title,
            summary=summary,
            source_id=outbox_id,
            confidence=0.99,
        )
        return _canonical_item(source_kind="candidate", row=row, item_class="action")
    row = await _insert_confirmed_fact(
        database,
        user_id=user_id,
        fact_type="task",
        domain="obligations",
        content=content,
        confidence=0.99,
        source_ids=[outbox_id],
        status="active",
        source_type=source,
        created_from={"path": "create_action", "source": source},
    )
    await _insert_timeline_event(
        database,
        user_id=user_id,
        event_type="task_confirmed",
        timeline_type="user_life",
        title=title,
        summary=summary,
        source_id=outbox_id,
        related_fact_ids=[row["id"]],
        confidence=0.99,
    )
    return _canonical_item(source_kind="confirmed_fact", row=row, item_class="action")


async def _confirm_candidate_as_fact(
    database: Database,
    *,
    candidate: dict[str, Any],
    fact_type: str,
    domain: str,
    status: str = "active",
) -> dict[str, Any]:
    candidate["status"] = "confirmed"
    await _update_candidate_record(database, candidate)
    return await _insert_confirmed_fact(
        database,
        user_id=candidate["user_id"],
        fact_type=fact_type,
        domain=domain,
        content=candidate["content"],
        confidence=candidate["confidence"],
        source_ids=[candidate["source_id"]],
        status=status,
        source_type=candidate.get("source_type", "chat"),
        who_said_it=candidate.get("who_said_it", "user"),
        channel=candidate.get("channel"),
        conversation_id=candidate.get("conversation_id"),
        created_from=candidate.get("created_from"),
    )


async def update_action(
    database: Database,
    *,
    item_id: UUID,
    user_id: str,
    status: str,
    title: str | None,
    summary: str | None,
    due_at: str | None,
    priority: str | None,
) -> dict[str, Any]:
    fact = await _fetch_fact_by_id(database, user_id=user_id, item_id=item_id)
    if fact and fact.get("fact_type") in {"task", "habit", "reminder"}:
        kind = _kind_for_row(fact)
        fact["content"] = _apply_item_updates(fact["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        fact["last_seen_at"] = _now_naive()
        fact["last_confirmed_at"] = fact["last_seen_at"]
        if status == "completed":
            fact["status"] = "historical"
            fact["content"].setdefault("metadata", {})["item_status"] = "completed"
            fact["content"] = apply_lifecycle_timestamp(
                fact["content"],
                completed_at=fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
            )
            event_type = _event_type_for_completion(kind)
        elif status == "dismissed":
            fact["status"] = "dismissed"
            fact["content"].setdefault("metadata", {})["item_status"] = "dismissed"
            fact["content"] = apply_lifecycle_timestamp(
                fact["content"],
                cancelled_at=fact["last_seen_at"].replace(tzinfo=timezone.utc).isoformat(),
            )
            event_type = "reminder_dismissed" if kind == "reminder" else "item_dismissed"
        else:
            fact["status"] = "active"
            fact["content"].setdefault("metadata", {})["item_status"] = "active"
            event_type = "state_change"
        _refresh_operational_row(fact, item_type=fact.get("fact_type") or "task", source_id=fact["source_ids"][0] if fact.get("source_ids") else None, source_ids=fact.get("source_ids"))
        await _update_fact_record(database, fact)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type=event_type,
            timeline_type="user_life",
            title=fact["content"].get("title") or "Action updated",
            summary=fact["content"].get("summary") or "",
            source_id=fact["source_ids"][0] if fact.get("source_ids") else None,
            related_fact_ids=[fact["id"]],
            confidence=fact["confidence"],
        )
        return _canonical_item(source_kind="confirmed_fact", row=fact, item_class="action")

    candidate = await _fetch_candidate_by_id(database, user_id=user_id, item_id=item_id)
    if candidate and candidate.get("candidate_type") in {"task", "habit", "reminder"}:
        kind = _kind_for_row(candidate)
        candidate["content"] = _apply_item_updates(candidate["content"], title=title, summary=summary, due_at=due_at, priority=priority)
        candidate["raw_evidence"] = candidate["content"]["evidence"]["raw_evidence"]
        _refresh_operational_row(candidate, item_type=candidate.get("candidate_type") or "task", source_id=candidate["source_id"], source_ids=[candidate["source_id"]])
        if status == "dismissed":
            candidate["status"] = "dismissed"
            await _update_candidate_record(database, candidate)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type="reminder_dismissed" if kind == "reminder" else "item_dismissed",
                timeline_type="user_life",
                title=candidate["content"].get("title") or "Action dismissed",
                summary=candidate["content"].get("summary") or "",
                source_id=candidate["source_id"],
                confidence=candidate["confidence"],
            )
            return _canonical_item(source_kind="candidate", row=candidate, item_class="action")
        if status == "completed":
            fact_type = candidate.get("candidate_type") or "task"
            domain = "habits" if fact_type == "habit" else "obligations"
            fact_row = await _confirm_candidate_as_fact(database, candidate=candidate, fact_type=fact_type, domain=domain, status="historical")
            fact_row["content"].setdefault("metadata", {})["item_status"] = "completed"
            fact_row["content"] = apply_lifecycle_timestamp(
                fact_row["content"],
                completed_at=_now_naive().replace(tzinfo=timezone.utc).isoformat(),
            )
            _refresh_operational_row(fact_row, item_type=fact_type, source_id=candidate["source_id"], source_ids=fact_row.get("source_ids"))
            await _update_fact_record(database, fact_row)
            await _insert_timeline_event(
                database,
                user_id=user_id,
                event_type=_event_type_for_completion(kind),
                timeline_type="user_life",
                title=fact_row["content"].get("title") or "Action completed",
                summary=fact_row["content"].get("summary") or "",
                source_id=candidate["source_id"],
                related_fact_ids=[fact_row["id"]],
                confidence=fact_row["confidence"],
            )
            return _canonical_item(source_kind="confirmed_fact", row=fact_row, item_class="action")
        candidate["status"] = "pending"
        await _update_candidate_record(database, candidate)
        await _insert_timeline_event(
            database,
            user_id=user_id,
            event_type="fact_learned",
            timeline_type="user_life",
            title=candidate["content"].get("title") or "Action updated",
            summary=candidate["content"].get("summary") or "",
            source_id=candidate["source_id"],
            confidence=candidate["confidence"],
        )
        return _canonical_item(source_kind="candidate", row=candidate, item_class="action")
    raise HTTPException(status_code=404, detail="Action not found.")
