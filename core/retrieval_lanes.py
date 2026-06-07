from __future__ import annotations

import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from core import embeddings
from core.db import Database
from core.retrieval_query import normalized_tokens


def serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    return json.dumps(value, sort_keys=True, default=str).lower()


def contains_token_phrase(document_tokens: list[str], query_tokens: list[str]) -> bool:
    if not query_tokens:
        return False
    width = len(query_tokens)
    return any(document_tokens[index : index + width] == query_tokens for index in range(len(document_tokens) - width + 1))


def best_fuzzy_ratio(query_token: str, document_tokens: set[str]) -> float:
    if len(query_token) < 4:
        return 0.0
    candidates = [token for token in document_tokens if len(token) >= 4 and token[0] == query_token[0] and abs(len(token) - len(query_token)) <= 2]
    best_ratio = 0.0
    for token in candidates:
        ratio = SequenceMatcher(None, query_token, token).ratio()
        if ratio < 0.84 and len(query_token) == len(token):
            for index in range(len(query_token) - 1):
                swapped = list(query_token)
                swapped[index], swapped[index + 1] = swapped[index + 1], swapped[index]
                if "".join(swapped) == token:
                    ratio = max(ratio, 0.89)
                    break
        best_ratio = max(best_ratio, ratio)
    return best_ratio


def score_match(text: str, query: str) -> dict[str, Any]:
    doc_token_list = normalized_tokens(text)
    doc_tokens = set(doc_token_list)
    query_tokens = normalized_tokens(query)
    exact_phrase = contains_token_phrase(doc_token_list, query_tokens)
    exact_overlap = sum(1 for token in query_tokens if token in doc_tokens)
    strong_fuzzy = 0
    weak_fuzzy = 0
    best_fuzzy = 0.0
    for token in query_tokens:
        if token in doc_tokens or len(token) < 4:
            continue
        ratio = best_fuzzy_ratio(token, doc_tokens)
        best_fuzzy = max(best_fuzzy, ratio)
        if ratio >= 0.9:
            strong_fuzzy += 1
        elif ratio >= 0.84:
            weak_fuzzy += 1
    raw_score = 0
    if exact_phrase:
        raw_score += 10
    raw_score += exact_overlap * 4
    raw_score += strong_fuzzy * 3
    raw_score += weak_fuzzy
    normalized_score = min(1.0, raw_score / 14.0) if raw_score else 0.0
    return {
        "score": normalized_score,
        "raw_score": raw_score,
        "exact_phrase": exact_phrase,
        "exact_overlap": exact_overlap,
        "strong_fuzzy": strong_fuzzy,
        "weak_fuzzy": weak_fuzzy,
        "best_fuzzy": best_fuzzy,
    }


def recency_score(value: Any) -> float:
    if isinstance(value, datetime):
        occurred = value
    else:
        normalized = str(value or "").replace("Z", "+00:00")
        try:
            occurred = datetime.fromisoformat(normalized)
        except ValueError:
            return 0.2
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days_delta = abs((now - occurred.astimezone(timezone.utc)).total_seconds()) / 86400.0
    if days_delta <= 1:
        return 1.0
    if days_delta <= 7:
        return 0.8
    if days_delta <= 30:
        return 0.6
    return 0.35


def coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    normalized = str(value or "").replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def truncate(text: str, *, limit: int = 180) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def excerpt(text: str, query: str, *, width: int = 160) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= width:
        return cleaned
    query_tokens = normalized_tokens(query)
    lowered = cleaned.lower()
    match_index = -1
    for token in query_tokens:
        idx = lowered.find(token.lower())
        if idx >= 0:
            match_index = idx
            break
    if match_index < 0:
        return truncate(cleaned, limit=width)
    start = max(0, match_index - width // 3)
    end = min(len(cleaned), start + width)
    snippet = cleaned[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(cleaned):
        snippet = snippet + "..."
    return snippet


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


async def fetch_session_summaries(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM session_summaries
        WHERE user_id = $1
        ORDER BY occurred_at DESC NULLS LAST
        """,
        user_id,
    )


async def fetch_timeline_events(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM timeline_events
        WHERE user_id = $1
        ORDER BY observed_at DESC NULLS LAST, occurred_at DESC NULLS LAST
        """,
        user_id,
    )


async def fetch_source_archive_rows(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM source_archive
        WHERE user_id = $1
        ORDER BY captured_at DESC NULLS LAST, created_at DESC NULLS LAST
        """,
        user_id,
    )


async def fetch_outbox_rows(database: Database, *, user_id: str) -> list[dict[str, Any]]:
    return await database.fetch(
        """
        SELECT *
        FROM outbox
        WHERE user_id = $1
        ORDER BY received_at DESC NULLS LAST
        """,
        user_id,
    )


def source_refs_for_fact(fact: dict[str, Any], outbox_rows: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    source_ids = {str(item) for item in (fact.get("source_ids") or [])}
    outbox_by_id = {str(row["id"]): row for row in outbox_rows}
    for source_id in source_ids:
        refs.append(f"outbox:{source_id}")
        outbox = outbox_by_id.get(source_id)
        if outbox and outbox.get("source_archive_id"):
            refs.append(f"source_archive:{outbox['source_archive_id']}")
    return list(dict.fromkeys(refs))


def source_refs_for_summary(summary: dict[str, Any], outbox_rows: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    source_id = summary.get("source_id")
    if source_id:
        refs.append(f"outbox:{source_id}")
        for outbox in outbox_rows:
            if str(outbox["id"]) == str(source_id) and outbox.get("source_archive_id"):
                refs.append(f"source_archive:{outbox['source_archive_id']}")
                break
    return refs


def source_refs_for_archive(row: dict[str, Any], outbox_rows: list[dict[str, Any]]) -> list[str]:
    refs = [f"source_archive:{row['id']}"]
    refs.extend(f"outbox:{outbox['id']}" for outbox in outbox_rows if str(outbox.get("source_archive_id")) == str(row["id"]))
    return refs


def source_refs_for_timeline(event: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    if event.get("source_id"):
        refs.append(f"outbox:{event['source_id']}")
    for fact_id in event.get("related_fact_ids") or []:
        refs.append(f"fact:{fact_id}")
    return refs


def linked_entities(content: dict[str, Any]) -> dict[str, list[str]]:
    links = content.get("links") or {}
    return {
        "people": [str(item).strip() for item in links.get("people", []) if str(item).strip()],
        "projects": [str(item).strip() for item in links.get("projects", []) if str(item).strip()],
        "topics": [str(item).strip() for item in links.get("topics", []) if str(item).strip()],
    }


def open_loop_status(fact: dict[str, Any]) -> str | None:
    if fact.get("fact_type") != "thread":
        return None
    if fact.get("status") != "active":
        return str(fact.get("status"))
    snoozed_until = fact.get("snoozed_until")
    if snoozed_until:
        parsed = coerce_datetime(snoozed_until)
        if parsed and parsed > datetime.now(timezone.utc):
            return "snoozed"
    content = fact.get("content") or {}
    metadata = content.get("metadata") or {}
    explicit = metadata.get("open_loop_status") or (metadata.get("agent_item") or {}).get("open_loop_status")
    if explicit:
        return str(explicit)
    last_status = str(metadata.get("last_status") or (metadata.get("agent_item") or {}).get("last_status") or "").lower()
    if any(token in last_status for token in ("resolved", "finished", "complete", "closed")) and "unresolved" not in last_status:
        return "resolved"
    if content.get("lifecycle", {}).get("expires_at"):
        return "stale"
    return "active"


def hybrid_score(*, lexical: float, vector: float, recency: float, confidence: float, weights: tuple[float, float, float, float]) -> float:
    lexical_weight, vector_weight, recency_weight, confidence_weight = weights
    score = lexical * lexical_weight + vector * vector_weight + recency * recency_weight + confidence * confidence_weight
    return round(min(1.0, score), 4)


def vector_hits_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    hits: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["source_type"], str(row["source_id"]))
        existing = hits.get(key)
        if existing is None or float(row.get("vector_score", 0.0)) > float(existing.get("vector_score", 0.0)):
            hits[key] = row
    return hits


def fact_search_text(fact: dict[str, Any]) -> str:
    content = fact.get("content") or {}
    metadata = content.get("metadata") or {}
    agent_item = metadata.get("agent_item") or {}
    links = content.get("links") or {}
    parts = [content.get("title"), content.get("summary"), serialize(content), serialize(agent_item), serialize(links.get("people", [])), serialize(links.get("projects", [])), serialize(links.get("topics", []))]
    return " ".join(part for part in parts if part)


def summary_search_text(summary: dict[str, Any]) -> str:
    return " ".join(part for part in [summary.get("summary"), serialize(summary.get("tags", [])), serialize(summary.get("open_items", [])), serialize(summary.get("key_decisions", []))] if part)


def timeline_search_text(event: dict[str, Any]) -> str:
    return " ".join(part for part in [event.get("title"), event.get("summary"), serialize(event.get("event_type"))] if part)


def build_fact_item(fact: dict[str, Any], *, lexical_meta: dict[str, Any], vector_score: float, outbox_rows: list[dict[str, Any]]) -> dict[str, Any]:
    content = fact.get("content") or {}
    confidence = float(fact.get("confidence", 0.0))
    recency = recency_score(fact.get("last_seen_at") or fact.get("first_seen_at"))
    score = hybrid_score(lexical=lexical_meta["score"], vector=vector_score, recency=recency, confidence=confidence, weights=(0.45, 0.35, 0.10, 0.10))
    return {
        "type": "fact",
        "id": str(fact["id"]),
        "title": content.get("title") or fact.get("fact_type"),
        "summary": content.get("summary") or content.get("evidence", {}).get("raw_evidence"),
        "confidence": confidence,
        "score": score,
        "source_refs": source_refs_for_fact(fact, outbox_rows),
        "evidence_preview": truncate(content.get("evidence", {}).get("raw_evidence") or content.get("summary") or ""),
        "occurred_at": str(fact.get("last_seen_at") or fact.get("first_seen_at") or ""),
        "metadata": {
            "lane": "factual",
            "fact_type": fact.get("fact_type"),
            "domain": fact.get("domain"),
            "linked_people": linked_entities(content)["people"],
            "linked_projects": linked_entities(content)["projects"],
            "linked_topics": linked_entities(content)["topics"],
            "lexical_score": round(lexical_meta["score"], 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
        },
        "evidence": {"match_reasons": [], "lane_hits": ["fact"]},
    }


def build_summary_episode(summary: dict[str, Any], *, lexical_meta: dict[str, Any], vector_hit: dict[str, Any] | None, outbox_rows: list[dict[str, Any]], query: str) -> dict[str, Any]:
    vector_text = str((vector_hit or {}).get("text") or summary.get("summary") or "")
    vector_score = float((vector_hit or {}).get("vector_score", 0.0))
    lexical_from_vector = score_match(vector_text, query)
    lexical_score = max(lexical_meta["score"], lexical_from_vector["score"])
    recency = recency_score(summary.get("occurred_at"))
    score = hybrid_score(lexical=lexical_score, vector=vector_score, recency=recency, confidence=0.75, weights=(0.30, 0.50, 0.20, 0.0))
    return {
        "type": "episode",
        "id": str(summary["id"]),
        "title": "Session summary",
        "summary": summary.get("summary"),
        "confidence": 0.75,
        "score": score,
        "source_refs": source_refs_for_summary(summary, outbox_rows),
        "evidence_preview": excerpt(vector_text or str(summary.get("summary") or ""), query, width=160),
        "occurred_at": str(summary.get("occurred_at") or ""),
        "metadata": {
            "lane": "episodic",
            "source_kind": "session_summary",
            "tags": summary.get("tags", []),
            "lexical_score": round(lexical_score, 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
            "linked_people": [],
            "linked_projects": [],
            "linked_topics": [],
        },
        "evidence": {"match_reasons": [], "lane_hits": ["source"]},
    }


def build_archive_episode(row: dict[str, Any], *, lexical_meta: dict[str, Any], vector_hit: dict[str, Any] | None, outbox_rows: list[dict[str, Any]], query: str) -> dict[str, Any]:
    raw_content = embeddings.build_source_archive_search_text(row)
    vector_text = str((vector_hit or {}).get("text") or raw_content)
    vector_score = float((vector_hit or {}).get("vector_score", 0.0))
    lexical_from_vector = score_match(vector_text, query)
    lexical_score = max(lexical_meta["score"], lexical_from_vector["score"])
    recency = recency_score(row.get("occurred_at") or row.get("captured_at"))
    score = hybrid_score(lexical=lexical_score, vector=vector_score, recency=recency, confidence=0.7, weights=(0.25, 0.55, 0.20, 0.0))
    return {
        "type": "episode",
        "id": str(row["id"]),
        "title": row.get("session_id") or row.get("source_external_id") or row.get("source_type"),
        "summary": truncate(vector_text, limit=120),
        "confidence": 0.7,
        "score": score,
        "source_refs": source_refs_for_archive(row, outbox_rows),
        "evidence_preview": excerpt(vector_text, query, width=160),
        "occurred_at": str(row.get("occurred_at") or row.get("captured_at") or ""),
        "metadata": {
            "lane": "episodic",
            "source_kind": "source_archive",
            "source_type": row.get("source_type"),
            "session_id": row.get("session_id"),
            "chunk_index": (vector_hit or {}).get("chunk_index"),
            "lexical_score": round(lexical_score, 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
            "linked_people": [],
            "linked_projects": [],
            "linked_topics": [],
        },
        "evidence": {"match_reasons": [], "lane_hits": ["source"]},
    }


def build_continuity_item(fact: dict[str, Any], *, lexical_meta: dict[str, Any], vector_score: float, outbox_rows: list[dict[str, Any]]) -> dict[str, Any]:
    content = fact.get("content") or {}
    confidence = float(fact.get("confidence", 0.0))
    recency = recency_score(fact.get("last_seen_at") or fact.get("first_seen_at"))
    score = hybrid_score(lexical=lexical_meta["score"], vector=vector_score, recency=recency, confidence=confidence, weights=(0.35, 0.35, 0.15, 0.15))
    return {
        "type": "continuity_note",
        "id": str(fact["id"]),
        "title": content.get("title") or "Open loop",
        "summary": content.get("summary") or content.get("evidence", {}).get("raw_evidence"),
        "confidence": confidence,
        "score": score,
        "source_refs": source_refs_for_fact(fact, outbox_rows),
        "evidence_preview": truncate(content.get("evidence", {}).get("raw_evidence") or content.get("summary") or ""),
        "occurred_at": str(fact.get("last_seen_at") or fact.get("first_seen_at") or ""),
        "metadata": {
            "lane": "continuity",
            "derived": True,
            "fact_type": fact.get("fact_type"),
            "open_loop_status": open_loop_status(fact),
            "linked_people": linked_entities(content)["people"],
            "linked_projects": linked_entities(content)["projects"],
            "linked_topics": linked_entities(content)["topics"],
            "lexical_score": round(lexical_meta["score"], 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
        },
        "evidence": {"match_reasons": [], "lane_hits": ["thread"]},
    }


def build_timeline_item(event: dict[str, Any], *, lexical_meta: dict[str, Any], vector_score: float, related_entities: dict[str, list[str]] | None = None) -> dict[str, Any]:
    confidence = float(event.get("confidence", 0.0))
    recency = recency_score(event.get("observed_at") or event.get("occurred_at"))
    score = hybrid_score(lexical=lexical_meta["score"], vector=vector_score, recency=recency, confidence=confidence, weights=(0.35, 0.40, 0.15, 0.10))
    return {
        "type": "timeline_event",
        "id": str(event["id"]),
        "title": event.get("title") or event.get("event_type"),
        "summary": event.get("summary"),
        "confidence": confidence,
        "score": score,
        "source_refs": source_refs_for_timeline(event),
        "evidence_preview": truncate(event.get("summary") or event.get("title") or ""),
        "occurred_at": str(event.get("occurred_at") or event.get("observed_at") or ""),
        "metadata": {
            "lane": "continuity",
            "derived": True,
            "event_type": event.get("event_type"),
            "linked_people": (related_entities or {}).get("people", []),
            "linked_projects": (related_entities or {}).get("projects", []),
            "linked_topics": (related_entities or {}).get("topics", []),
            "lexical_score": round(lexical_meta["score"], 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
        },
        "evidence": {"match_reasons": [], "lane_hits": ["timeline"]},
    }


def strong_fact_match(item: dict[str, Any]) -> bool:
    return float(item.get("confidence", 0.0)) > 0.8 and item.get("score", 0.0) >= 0.25 and (item.get("metadata", {}).get("lexical_score", 0.0) >= 0.05 or item.get("metadata", {}).get("vector_score", 0.0) >= 0.82)


def include_candidate(lexical_score: float, vector_score: float, hybrid_score_value: float) -> bool:
    if lexical_score <= 0 and vector_score <= 0:
        return False
    return hybrid_score_value >= 0.22 or lexical_score >= 0.12 or vector_score >= 0.72


async def fetch_vector_rows(database: Database, *, user_id: str, query: str, limit: int, query_tokens: list[str]) -> list[dict[str, Any]]:
    if not any(len(token) >= 3 for token in query_tokens):
        return []
    return await embeddings.search_retrieval_embeddings(
        database,
        user_id=user_id,
        query=query,
        source_types=["confirmed_fact", "session_summary", "source_archive_chunk", "timeline_event"],
        limit=max(limit * 8, 24),
    )
