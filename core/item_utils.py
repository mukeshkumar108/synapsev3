from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from core.operational import extract_operational_fields, normalize_provenance, parse_datetime


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)
    parsed = parse_datetime(value)
    return parsed.replace(tzinfo=None) if parsed else None


def _to_iso(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()
    return value


def _uuid_from_ref(value: str | None, *, fallback: str) -> UUID:
    return uuid5(NAMESPACE_URL, value or fallback)


def _iso_day(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    parsed = parse_datetime(value)
    return parsed.date().isoformat() if parsed else None


def _row_provenance(
    *,
    source_id: UUID | None,
    source_ids: list[UUID] | None,
    source_type: str | None,
    original_text: str | None,
    who_said_it: str | None,
    channel: str | None,
    conversation_id: str | None,
    created_from: dict[str, Any] | None,
) -> dict[str, Any]:
    return normalize_provenance(
        source_id=source_id,
        source_type=source_type,
        original_text=original_text,
        who_said_it=who_said_it,
        channel=channel,
        conversation_id=conversation_id,
        created_from=created_from,
        source_ids=source_ids,
    )


def _refresh_operational_row(row: dict[str, Any], *, item_type: str, source_id: UUID | None, source_ids: list[UUID] | None = None) -> dict[str, Any]:
    provenance = _row_provenance(
        source_id=source_id,
        source_ids=source_ids,
        source_type=row.get("source_type"),
        original_text=row.get("original_text") or row.get("raw_evidence") or ((row.get("content") or {}).get("evidence") or {}).get("raw_evidence"),
        who_said_it=row.get("who_said_it"),
        channel=row.get("channel"),
        conversation_id=row.get("conversation_id"),
        created_from=row.get("created_from"),
    )
    operational = extract_operational_fields(
        item_type=item_type,
        content=row["content"],
        provenance=provenance,
        record_status=row.get("status"),
    )
    row["structured_content"] = operational["structured_content"]
    row["starts_at"] = _to_naive(operational["starts_at"])
    row["ends_at"] = _to_naive(operational["ends_at"])
    row["due_at"] = _to_naive(operational["due_at"])
    row["remind_at"] = _to_naive(operational["remind_at"])
    row["timezone"] = operational["timezone"]
    row["recurrence_rule"] = operational["recurrence_rule"]
    row["completed_at"] = _to_naive(operational["completed_at"])
    row["cancelled_at"] = _to_naive(operational["cancelled_at"])
    row["priority"] = operational["priority"]
    row["source_type"] = operational["source_type"]
    row["who_said_it"] = operational["who_said_it"]
    row["original_text"] = operational["original_text"]
    row["channel"] = operational["channel"]
    row["conversation_id"] = operational["conversation_id"]
    row["created_from"] = operational["created_from"]
    row["provenance"] = operational["provenance"]
    row["follow_up_needed"] = operational["follow_up_needed"]
    row["thread_type"] = operational.get("thread_type")
    row["actionability"] = operational.get("actionability")
    row["next_move"] = operational.get("next_move")
    row["last_progressed_at"] = _to_naive(operational.get("last_progressed_at"))
    row["last_resurfaced_at"] = _to_naive(operational.get("last_resurfaced_at"))
    row["snoozed_until"] = _to_naive(operational.get("snoozed_until"))
    if source_ids is not None:
        row["source_ids"] = source_ids
        row["primary_source_id"] = source_ids[0] if source_ids else None
    return row
