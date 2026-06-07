from __future__ import annotations

from typing import Any

from core import embeddings
from core.db import Database
from core.retrieval_lanes import (
    build_archive_episode,
    build_continuity_item,
    build_fact_item,
    build_summary_episode,
    build_timeline_item,
    fact_search_text,
    fetch_active_confirmed_facts,
    fetch_outbox_rows,
    fetch_session_summaries,
    fetch_source_archive_rows,
    fetch_timeline_events,
    fetch_vector_rows,
    include_candidate,
    linked_entities,
    open_loop_status,
    score_match,
    source_refs_for_archive,
    strong_fact_match,
    summary_search_text,
    timeline_search_text,
    vector_hits_by_key,
)
from core.retrieval_merge import merge_candidates
from core.retrieval_query import expand_query_entities, infer_recall_type, normalized_tokens
from core.reranking import get_reranker


def _add_reason(item: dict[str, Any], *, reason: str, lane: str) -> dict[str, Any]:
    payload = dict(item)
    evidence = payload.setdefault("evidence", {"match_reasons": [], "lane_hits": []})
    if reason not in evidence["match_reasons"]:
        evidence["match_reasons"].append(reason)
    if lane not in evidence["lane_hits"]:
        evidence["lane_hits"].append(lane)
    return payload


def _entity_link_targets(resolved_entities: list[dict[str, Any]]) -> dict[str, set[str]]:
    targets = {
        "fact": set(),
        "timeline_event": set(),
        "source_archive": set(),
    }
    for entity in resolved_entities:
        for link in entity.get("links", []):
            if link.get("fact_id"):
                targets["fact"].add(str(link["fact_id"]))
            if link.get("timeline_event_id"):
                targets["timeline_event"].add(str(link["timeline_event_id"]))
            if link.get("source_archive_id"):
                targets["source_archive"].add(str(link["source_archive_id"]))
    return targets


async def recall_v2(
    database: Database,
    *,
    user_id: str,
    query: str,
    limit: int = 5,
    recall_type: str | None = None,
    reranker_name: str = "noop",
) -> dict[str, Any]:
    resolved_type = recall_type or infer_recall_type(query)
    query_tokens = normalized_tokens(query)
    entity_context = await expand_query_entities(database, user_id=user_id, query=query)
    expanded_query = query if not entity_context["expanded_terms"] else query + " " + " ".join(entity_context["expanded_terms"])

    facts = await fetch_active_confirmed_facts(database, user_id=user_id)
    summaries = await fetch_session_summaries(database, user_id=user_id)
    timeline = await fetch_timeline_events(database, user_id=user_id)
    source_archive_rows = await fetch_source_archive_rows(database, user_id=user_id)
    outbox_rows = await fetch_outbox_rows(database, user_id=user_id)
    facts_by_id = {str(fact["id"]): fact for fact in facts}
    vector_rows = await fetch_vector_rows(database, user_id=user_id, query=expanded_query, limit=limit, query_tokens=query_tokens)
    vector_hits = vector_hits_by_key(vector_rows)

    fact_ranked: list[dict[str, Any]] = []
    for fact in facts:
        lexical_meta = score_match(fact_search_text(fact), expanded_query)
        vector_score = float(vector_hits.get(("confirmed_fact", str(fact["id"])), {}).get("vector_score", 0.0))
        item = build_fact_item(fact, lexical_meta=lexical_meta, vector_score=vector_score, outbox_rows=outbox_rows)
        if include_candidate(lexical_meta["score"], vector_score, item["score"]):
            if lexical_meta["score"] > 0:
                item = _add_reason(item, reason="lexical_match", lane="fact")
            if vector_score > 0:
                item = _add_reason(item, reason="vector_match", lane="fact")
            fact_ranked.append(item)
    fact_ranked.sort(key=lambda item: item["score"], reverse=True)

    summary_ranked: list[dict[str, Any]] = []
    for summary in summaries:
        vector_hit = vector_hits.get(("session_summary", str(summary["id"])))
        lexical_meta = score_match(summary_search_text(summary), expanded_query)
        item = build_summary_episode(summary, lexical_meta=lexical_meta, vector_hit=vector_hit, outbox_rows=outbox_rows, query=expanded_query)
        if include_candidate(item["metadata"]["lexical_score"], item["metadata"]["vector_score"], item["score"]):
            if item["metadata"]["lexical_score"] > 0:
                item = _add_reason(item, reason="lexical_match", lane="source")
            if item["metadata"]["vector_score"] > 0:
                item = _add_reason(item, reason="vector_match", lane="source")
            summary_ranked.append(item)
    summary_ranked.sort(key=lambda item: item["score"], reverse=True)

    archive_ranked: list[dict[str, Any]] = []
    for row in source_archive_rows:
        vector_hit = vector_hits.get(("source_archive_chunk", str(row["id"])))
        lexical_meta = score_match(embeddings.build_source_archive_search_text(row), expanded_query)
        item = build_archive_episode(row, lexical_meta=lexical_meta, vector_hit=vector_hit, outbox_rows=outbox_rows, query=expanded_query)
        if include_candidate(item["metadata"]["lexical_score"], item["metadata"]["vector_score"], item["score"]):
            if item["metadata"]["lexical_score"] > 0:
                item = _add_reason(item, reason="lexical_match", lane="source")
            if item["metadata"]["vector_score"] > 0:
                item = _add_reason(item, reason="vector_match", lane="source")
            archive_ranked.append(item)
    archive_ranked.sort(key=lambda item: item["score"], reverse=True)

    continuity_ranked: list[dict[str, Any]] = []
    for fact in facts:
        if fact.get("fact_type") != "thread":
            continue
        if open_loop_status(fact) not in {"active", "unresolved"}:
            continue
        lexical_meta = score_match(fact_search_text(fact), expanded_query)
        vector_score = float(vector_hits.get(("confirmed_fact", str(fact["id"])), {}).get("vector_score", 0.0))
        item = build_continuity_item(fact, lexical_meta=lexical_meta, vector_score=vector_score, outbox_rows=outbox_rows)
        if include_candidate(lexical_meta["score"], vector_score, item["score"]):
            if lexical_meta["score"] > 0:
                item = _add_reason(item, reason="lexical_match", lane="thread")
            if vector_score > 0:
                item = _add_reason(item, reason="vector_match", lane="thread")
            continuity_ranked.append(item)
    for event in timeline:
        lexical_meta = score_match(timeline_search_text(event), expanded_query)
        vector_score = float(vector_hits.get(("timeline_event", str(event["id"])), {}).get("vector_score", 0.0))
        related_entities = {"people": [], "projects": [], "topics": []}
        for fact_id in event.get("related_fact_ids") or []:
            fact = facts_by_id.get(str(fact_id))
            if not fact:
                continue
            entities = linked_entities(fact.get("content") or {})
            for kind in related_entities:
                related_entities[kind].extend(entities[kind])
        item = build_timeline_item(event, lexical_meta=lexical_meta, vector_score=vector_score, related_entities=related_entities)
        if include_candidate(lexical_meta["score"], vector_score, item["score"]):
            if lexical_meta["score"] > 0:
                item = _add_reason(item, reason="lexical_match", lane="timeline")
            if vector_score > 0:
                item = _add_reason(item, reason="vector_match", lane="timeline")
            continuity_ranked.append(item)
    continuity_ranked.sort(key=lambda item: item["score"], reverse=True)

    entity_targets = _entity_link_targets(entity_context["resolved_entities"])
    entity_items: list[dict[str, Any]] = []
    for fact in facts:
        if str(fact["id"]) not in entity_targets["fact"]:
            continue
        lexical_meta = score_match(fact_search_text(fact), expanded_query)
        vector_score = float(vector_hits.get(("confirmed_fact", str(fact["id"])), {}).get("vector_score", 0.0))
        base_item = build_continuity_item(fact, lexical_meta=lexical_meta, vector_score=vector_score, outbox_rows=outbox_rows) if fact.get("fact_type") == "thread" and open_loop_status(fact) in {"active", "unresolved"} else build_fact_item(fact, lexical_meta=lexical_meta, vector_score=vector_score, outbox_rows=outbox_rows)
        base_item["score"] = round(min(1.0, float(base_item["score"]) + 0.18), 4)
        entity_items.append(_add_reason(base_item, reason="entity_link_match", lane="entity"))
    for event in timeline:
        if str(event["id"]) not in entity_targets["timeline_event"]:
            continue
        lexical_meta = score_match(timeline_search_text(event), expanded_query)
        vector_score = float(vector_hits.get(("timeline_event", str(event["id"])), {}).get("vector_score", 0.0))
        item = build_timeline_item(event, lexical_meta=lexical_meta, vector_score=vector_score)
        item["score"] = round(min(1.0, float(item["score"]) + 0.18), 4)
        entity_items.append(_add_reason(item, reason="entity_link_match", lane="entity"))
    for row in source_archive_rows:
        if str(row["id"]) not in entity_targets["source_archive"]:
            continue
        vector_hit = vector_hits.get(("source_archive_chunk", str(row["id"])))
        lexical_meta = score_match(embeddings.build_source_archive_search_text(row), expanded_query)
        item = build_archive_episode(row, lexical_meta=lexical_meta, vector_hit=vector_hit, outbox_rows=outbox_rows, query=expanded_query)
        item["score"] = round(min(1.0, float(item["score"]) + 0.18), 4)
        entity_items.append(_add_reason(item, reason="entity_link_match", lane="entity"))

    continuity_items = [item for item in continuity_ranked if item["type"] == "continuity_note"]
    timeline_items = [item for item in continuity_ranked if item["type"] == "timeline_event"]
    episode_items = sorted(summary_ranked + archive_ranked, key=lambda item: item["score"], reverse=True)

    if resolved_type == "exact":
        combined = fact_ranked + continuity_items + timeline_items + entity_items
    elif resolved_type == "episodic":
        combined = episode_items + continuity_items + timeline_items + entity_items
    else:
        combined = fact_ranked + episode_items + continuity_items + timeline_items + entity_items

    merged = merge_candidates(combined)
    reranker = get_reranker(reranker_name)
    ranked = reranker.rank(expanded_query, merged, resolved_type)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    items = ranked[:limit]
    strong_fact = any(strong_fact_match(item) for item in fact_ranked[:limit])
    has_matches = bool(items)
    certainty = "high" if strong_fact else "partial" if has_matches else "low"
    weak_recall = certainty == "low"
    weak_recall_reason = None if has_matches else "No grounded factual, episodic, or continuity matches were found."
    return {
        "items": items,
        "facts": [item for item in ranked if item["type"] == "fact"][:limit],
        "episodes": [item for item in ranked if item["type"] == "episode"][:limit],
        "continuity": [item for item in ranked if item["type"] == "continuity_note"][:limit],
        "timeline": [item for item in ranked if item["type"] == "timeline_event"][:limit],
        "summaries": [
            {
                "id": item["id"],
                "summary": item["summary"],
                "tags": item.get("metadata", {}).get("tags", []),
                "occurred_at": item["occurred_at"],
            }
            for item in ranked[:limit]
            if item.get("metadata", {}).get("source_kind") == "session_summary"
        ],
        "resolved_entities": [
            {
                "id": str(entity["id"]),
                "canonical_name": entity.get("canonical_name"),
                "entity_type": entity.get("entity_type"),
                "matched_span": entity.get("matched_span"),
                "aliases": [alias.get("alias_text") for alias in entity.get("aliases", [])],
            }
            for entity in entity_context["resolved_entities"]
        ],
        "evidence": {
            "expanded_terms": entity_context["expanded_terms"],
            "items": {f"{item['type']}:{item['id']}": item.get("evidence", {}) for item in items},
        },
        "recall_type": resolved_type,
        "weak_recall": weak_recall,
        "weak_recall_reason": weak_recall_reason,
        "certainty": certainty,
    }
