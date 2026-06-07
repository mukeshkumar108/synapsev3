from __future__ import annotations

from typing import Any
from uuid import UUID

from core.db import Database
from core import entity_repository


def _clean_names(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned_values: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_values.append(cleaned)
    return cleaned_values


def _entity_specs_from_content(content: dict[str, Any]) -> list[tuple[str, str, str]]:
    links = content.get("links") or {}
    specs: list[tuple[str, str, str]] = []
    for name in _clean_names(links.get("people", [])):
        specs.append(("person", name, "person_ref"))
    for name in _clean_names(links.get("projects", [])):
        specs.append(("project", name, "project_ref"))
    for name in _clean_names(links.get("topics", [])):
        specs.append(("topic", name, "topic_ref"))
    return specs


async def sync_candidate_entities(database: Database, candidate: dict[str, Any]) -> None:
    content = candidate.get("content") or {}
    specs = _entity_specs_from_content(content)
    for entity_type, name, link_type in specs:
        entity = await entity_repository.upsert_entity(
            database,
            user_id=candidate["user_id"],
            entity_type=entity_type,
            canonical_name=name,
            metadata={"origin": "candidate_links"},
        )
        await entity_repository.upsert_entity_alias(
            database,
            user_id=candidate["user_id"],
            entity_id=entity["id"],
            alias_text=name,
            alias_kind="canonical",
            is_primary=True,
        )
        await entity_repository.insert_entity_mention(
            database,
            user_id=candidate["user_id"],
            entity_id=entity["id"],
            surface_text=name,
            source_type=candidate.get("source_type") or "chat",
            original_text=candidate.get("original_text") or candidate.get("raw_evidence"),
            who_said_it=candidate.get("who_said_it"),
            channel=candidate.get("channel"),
            conversation_id=candidate.get("conversation_id"),
            created_from=candidate.get("created_from"),
            confidence=float(candidate.get("confidence", 1.0)),
            outbox_id=candidate.get("source_id"),
            candidate_id=candidate["id"],
        )
        await entity_repository.upsert_entity_link(
            database,
            user_id=candidate["user_id"],
            entity_id=entity["id"],
            candidate_id=candidate["id"],
            outbox_id=candidate.get("source_id"),
            link_type=link_type,
            confidence=float(candidate.get("confidence", 1.0)),
            evidence={"origin": "candidate_content_links"},
            created_from=candidate.get("created_from"),
        )


async def sync_confirmed_fact_entities(database: Database, fact: dict[str, Any]) -> None:
    content = fact.get("content") or {}
    specs = _entity_specs_from_content(content)
    if fact.get("fact_type") == "relationship":
        title = str(content.get("title") or "").strip()
        if title:
            specs.append(("person", title, "subject"))
    for entity_type, name, link_type in specs:
        entity = await entity_repository.upsert_entity(
            database,
            user_id=fact["user_id"],
            entity_type=entity_type,
            canonical_name=name,
            metadata={"origin": "confirmed_fact_links"},
        )
        await entity_repository.upsert_entity_alias(
            database,
            user_id=fact["user_id"],
            entity_id=entity["id"],
            alias_text=name,
            alias_kind="canonical",
            is_primary=True,
        )
        await entity_repository.insert_entity_mention(
            database,
            user_id=fact["user_id"],
            entity_id=entity["id"],
            surface_text=name,
            source_type=fact.get("source_type") or "chat",
            original_text=fact.get("original_text") or ((content.get("evidence") or {}).get("raw_evidence")),
            who_said_it=fact.get("who_said_it"),
            channel=fact.get("channel"),
            conversation_id=fact.get("conversation_id"),
            created_from=fact.get("created_from"),
            confidence=float(fact.get("confidence", 1.0)),
            outbox_id=(fact.get("source_ids") or [None])[0],
            fact_id=fact["id"],
        )
        await entity_repository.upsert_entity_link(
            database,
            user_id=fact["user_id"],
            entity_id=entity["id"],
            fact_id=fact["id"],
            outbox_id=(fact.get("source_ids") or [None])[0],
            link_type=link_type,
            confidence=float(fact.get("confidence", 1.0)),
            evidence={"origin": "confirmed_fact_content_links"},
            created_from=fact.get("created_from"),
        )


async def resolve_entity(
    database: Database,
    *,
    user_id: str,
    name: str,
    entity_type: str | None = None,
) -> dict[str, Any] | None:
    entity = await entity_repository.resolve_entity_by_name(
        database,
        user_id=user_id,
        name=name,
        entity_type=entity_type,
    )
    if entity is None:
        return None
    aliases = await entity_repository.fetch_entity_aliases(
        database,
        user_id=user_id,
        entity_id=entity["id"],
    )
    links = await entity_repository.fetch_entity_links(
        database,
        user_id=user_id,
        entity_id=entity["id"],
    )
    return {
        **entity,
        "aliases": aliases,
        "links": links,
    }


def _outbox_rows_for_user(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    if hasattr(database, "outbox_rows"):
        rows = getattr(database, "outbox_rows")
        values = rows.values() if isinstance(rows, dict) else rows
        return [row for row in values if row.get("user_id") == user_id]
    return []


def _source_archive_rows_for_user(database: Database, *, user_id: str) -> dict[UUID, dict[str, Any]]:
    if hasattr(database, "source_archive_rows"):
        rows = getattr(database, "source_archive_rows")
        values = rows.values() if isinstance(rows, dict) else rows
        return {row["id"]: row for row in values if row.get("user_id") == user_id}
    return {}


async def _backfill_source_links_for_fact(database: Database, *, fact: dict[str, Any]) -> None:
    outbox_rows = {row["id"]: row for row in _outbox_rows_for_user(database, user_id=fact["user_id"])}
    archive_rows = _source_archive_rows_for_user(database, user_id=fact["user_id"])
    entity_specs = _entity_specs_from_content(fact.get("content") or {})
    if fact.get("fact_type") == "relationship":
        title = str((fact.get("content") or {}).get("title") or "").strip()
        if title:
            entity_specs.append(("person", title, "subject"))
    for entity_type, name, link_type in entity_specs:
        entity = await entity_repository.resolve_entity_by_name(
            database,
            user_id=fact["user_id"],
            name=name,
            entity_type=entity_type,
        )
        if entity is None:
            continue
        for outbox_id in fact.get("source_ids") or []:
            outbox_row = outbox_rows.get(outbox_id)
            if not outbox_row:
                continue
            source_archive_id = outbox_row.get("source_archive_id")
            if source_archive_id and source_archive_id in archive_rows:
                await entity_repository.upsert_entity_link(
                    database,
                    user_id=fact["user_id"],
                    entity_id=entity["id"],
                    source_archive_id=source_archive_id,
                    outbox_id=outbox_id,
                    link_type=f"{link_type}_source",
                    confidence=float(fact.get("confidence", 1.0)),
                    evidence={"origin": "backfill_source_archive_link"},
                    created_from=fact.get("created_from"),
                )


async def _backfill_timeline_links_for_user(database: Database, *, user_id: str) -> None:
    from core.item_repository import _fetch_confirmed_facts

    if not hasattr(database, "timeline_events"):
        return
    events = [event for event in getattr(database, "timeline_events") if event.get("user_id") == user_id]
    facts = {row["id"]: row for row in await _fetch_confirmed_facts(database, user_id=user_id)}
    for event in events:
        for fact_id in event.get("related_fact_ids") or []:
            fact = facts.get(fact_id)
            if not fact:
                continue
            entity_specs = _entity_specs_from_content(fact.get("content") or {})
            if fact.get("fact_type") == "relationship":
                title = str((fact.get("content") or {}).get("title") or "").strip()
                if title:
                    entity_specs.append(("person", title, "subject"))
            for entity_type, name, link_type in entity_specs:
                entity = await entity_repository.resolve_entity_by_name(
                    database,
                    user_id=user_id,
                    name=name,
                    entity_type=entity_type,
                )
                if entity is None:
                    continue
                await entity_repository.upsert_entity_link(
                    database,
                    user_id=user_id,
                    entity_id=entity["id"],
                    timeline_event_id=event["id"],
                    link_type=f"{link_type}_timeline",
                    confidence=float(event.get("confidence", fact.get("confidence", 1.0))),
                    evidence={"origin": "backfill_timeline_link", "related_fact_id": str(fact["id"])},
                    created_from=fact.get("created_from"),
                )


async def backfill_user_entities(database: Database, *, user_id: str) -> dict[str, int]:
    from core.item_repository import _fetch_candidates, _fetch_confirmed_facts

    facts = await _fetch_confirmed_facts(database, user_id=user_id)
    candidates = await _fetch_candidates(database, user_id=user_id)

    for candidate in candidates:
        await sync_candidate_entities(database, candidate)

    for fact in facts:
        await sync_confirmed_fact_entities(database, fact)
        await _backfill_source_links_for_fact(database, fact=fact)

    await _backfill_timeline_links_for_user(database, user_id=user_id)

    entities = await entity_repository.fetch_entities(database, user_id=user_id)
    entity_links = await entity_repository.fetch_entity_links(database, user_id=user_id, entity_id=entities[0]["id"]) if entities else []
    return {
        "facts_processed": len(facts),
        "candidates_processed": len(candidates),
        "entities_total": len(entities),
        "sample_entity_links": len(entity_links),
    }
