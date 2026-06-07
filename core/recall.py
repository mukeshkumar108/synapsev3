from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from core.db import Database
from core import embeddings


STOPWORDS = {
    "a",
    "an",
    "and",
    "about",
    "did",
    "do",
    "for",
    "i",
    "is",
    "me",
    "my",
    "of",
    "say",
    "tell",
    "the",
    "to",
    "we",
    "what",
    "with",
    "you",
    "your",
}

EXACT_PATTERNS = (
    "who is",
    "what is",
    "when is",
    "where is",
    "who's",
    "what's",
    "when's",
    "where's",
)
EPISODIC_MARKERS = (
    "remember when",
    "we talked",
    "we discussed",
    "that conversation",
    "conversation about",
    "talked about",
    "discussed",
)


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    return json.dumps(value, sort_keys=True, default=str).lower()


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"\b([a-z0-9_]+)'s\b", r"\1", lowered)
    lowered = re.sub(r"\b([a-z0-9_]+)s'\b", r"\1", lowered)
    return lowered


def _normalized_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_]+", _normalize_text(value))
    return [token for token in tokens if token and token not in STOPWORDS]


def _contains_token_phrase(document_tokens: list[str], query_tokens: list[str]) -> bool:
    if not query_tokens:
        return False
    width = len(query_tokens)
    return any(document_tokens[index : index + width] == query_tokens for index in range(len(document_tokens) - width + 1))


def _best_fuzzy_ratio(query_token: str, document_tokens: set[str]) -> float:
    if len(query_token) < 4:
        return 0.0
    candidates = [
        token
        for token in document_tokens
        if len(token) >= 4 and token[0] == query_token[0] and abs(len(token) - len(query_token)) <= 2
    ]
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


def _score_match(text: str, query: str) -> dict[str, Any]:
    doc_token_list = _normalized_tokens(text)
    doc_tokens = set(doc_token_list)
    query_tokens = _normalized_tokens(query)

    exact_phrase = _contains_token_phrase(doc_token_list, query_tokens)
    exact_overlap = sum(1 for token in query_tokens if token in doc_tokens)
    strong_fuzzy = 0
    weak_fuzzy = 0
    best_fuzzy = 0.0

    for token in query_tokens:
        if token in doc_tokens or len(token) < 4:
            continue
        ratio = _best_fuzzy_ratio(token, doc_tokens)
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


def _recency_score(value: Any) -> float:
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


def _coerce_datetime(value: Any) -> datetime | None:
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


def _truncate(text: str, *, limit: int = 180) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _excerpt(text: str, query: str, *, width: int = 160) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= width:
        return cleaned
    query_tokens = _normalized_tokens(query)
    lowered = cleaned.lower()
    match_index = -1
    for token in query_tokens:
        idx = lowered.find(token.lower())
        if idx >= 0:
            match_index = idx
            break
    if match_index < 0:
        return _truncate(cleaned, limit=width)
    start = max(0, match_index - width // 3)
    end = min(len(cleaned), start + width)
    snippet = cleaned[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(cleaned):
        snippet = snippet + "..."
    return snippet


def _infer_recall_type(query: str) -> str:
    lowered = _normalize_text(query)
    if any(lowered.startswith(pattern) for pattern in EXACT_PATTERNS):
        return "exact"
    if any(marker in lowered for marker in EPISODIC_MARKERS) or ("remember" in lowered and "conversation" in lowered):
        return "episodic"
    return "hybrid"


def _fact_search_text(fact: dict[str, Any]) -> str:
    content = fact.get("content") or {}
    metadata = content.get("metadata") or {}
    agent_item = metadata.get("agent_item") or {}
    links = content.get("links") or {}
    parts = [
        content.get("title"),
        content.get("summary"),
        _serialize(content),
        _serialize(agent_item),
        _serialize(links.get("people", [])),
        _serialize(links.get("projects", [])),
        _serialize(links.get("topics", [])),
    ]
    return " ".join(part for part in parts if part)


def _summary_search_text(summary: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            summary.get("summary"),
            _serialize(summary.get("tags", [])),
            _serialize(summary.get("open_items", [])),
            _serialize(summary.get("key_decisions", [])),
        ]
        if part
    )


def _timeline_search_text(event: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            event.get("title"),
            event.get("summary"),
            _serialize(event.get("event_type")),
        ]
        if part
    )


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


def _source_refs_for_fact(fact: dict[str, Any], outbox_rows: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    source_ids = {str(item) for item in (fact.get("source_ids") or [])}
    outbox_by_id = {str(row["id"]): row for row in outbox_rows}
    for source_id in source_ids:
        refs.append(f"outbox:{source_id}")
        outbox = outbox_by_id.get(source_id)
        if outbox and outbox.get("source_archive_id"):
            refs.append(f"source_archive:{outbox['source_archive_id']}")
    return list(dict.fromkeys(refs))


def _source_refs_for_summary(summary: dict[str, Any], outbox_rows: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    source_id = summary.get("source_id")
    if source_id:
        refs.append(f"outbox:{source_id}")
        for outbox in outbox_rows:
            if str(outbox["id"]) == str(source_id) and outbox.get("source_archive_id"):
                refs.append(f"source_archive:{outbox['source_archive_id']}")
                break
    return refs


def _source_refs_for_archive(row: dict[str, Any], outbox_rows: list[dict[str, Any]]) -> list[str]:
    refs = [f"source_archive:{row['id']}"]
    refs.extend(
        f"outbox:{outbox['id']}"
        for outbox in outbox_rows
        if str(outbox.get("source_archive_id")) == str(row["id"])
    )
    return refs


def _source_refs_for_timeline(event: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    if event.get("source_id"):
        refs.append(f"outbox:{event['source_id']}")
    for fact_id in event.get("related_fact_ids") or []:
        refs.append(f"fact:{fact_id}")
    return refs


def _linked_entities(content: dict[str, Any]) -> dict[str, list[str]]:
    links = content.get("links") or {}
    return {
        "people": [str(item).strip() for item in links.get("people", []) if str(item).strip()],
        "projects": [str(item).strip() for item in links.get("projects", []) if str(item).strip()],
        "topics": [str(item).strip() for item in links.get("topics", []) if str(item).strip()],
    }


def _open_loop_status(fact: dict[str, Any]) -> str | None:
    if fact.get("fact_type") != "thread":
        return None
    if fact.get("status") != "active":
        return str(fact.get("status"))
    snoozed_until = fact.get("snoozed_until")
    if snoozed_until:
        parsed = _coerce_datetime(snoozed_until)
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


def _hybrid_score(*, lexical: float, vector: float, recency: float, confidence: float, weights: tuple[float, float, float, float]) -> float:
    lexical_weight, vector_weight, recency_weight, confidence_weight = weights
    score = lexical * lexical_weight + vector * vector_weight + recency * recency_weight + confidence * confidence_weight
    return round(min(1.0, score), 4)


def _vector_hits_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    hits: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["source_type"], str(row["source_id"]))
        existing = hits.get(key)
        if existing is None or float(row.get("vector_score", 0.0)) > float(existing.get("vector_score", 0.0)):
            hits[key] = row
    return hits


def _build_fact_item(
    fact: dict[str, Any],
    *,
    lexical_meta: dict[str, Any],
    vector_score: float,
    outbox_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    content = fact.get("content") or {}
    confidence = float(fact.get("confidence", 0.0))
    recency = _recency_score(fact.get("last_seen_at") or fact.get("first_seen_at"))
    score = _hybrid_score(
        lexical=lexical_meta["score"],
        vector=vector_score,
        recency=recency,
        confidence=confidence,
        weights=(0.45, 0.35, 0.10, 0.10),
    )
    return {
        "type": "fact",
        "id": str(fact["id"]),
        "title": content.get("title") or fact.get("fact_type"),
        "summary": content.get("summary") or content.get("evidence", {}).get("raw_evidence"),
        "confidence": confidence,
        "score": score,
        "source_refs": _source_refs_for_fact(fact, outbox_rows),
        "evidence_preview": _truncate(content.get("evidence", {}).get("raw_evidence") or content.get("summary") or ""),
        "occurred_at": str(fact.get("last_seen_at") or fact.get("first_seen_at") or ""),
        "metadata": {
            "lane": "factual",
            "fact_type": fact.get("fact_type"),
            "domain": fact.get("domain"),
            "linked_people": _linked_entities(content)["people"],
            "linked_projects": _linked_entities(content)["projects"],
            "linked_topics": _linked_entities(content)["topics"],
            "lexical_score": round(lexical_meta["score"], 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
        },
    }


def _build_summary_episode(
    summary: dict[str, Any],
    *,
    lexical_meta: dict[str, Any],
    vector_hit: dict[str, Any] | None,
    outbox_rows: list[dict[str, Any]],
    query: str,
) -> dict[str, Any]:
    vector_text = str((vector_hit or {}).get("text") or summary.get("summary") or "")
    vector_score = float((vector_hit or {}).get("vector_score", 0.0))
    lexical_from_vector = _score_match(vector_text, query)
    lexical_score = max(lexical_meta["score"], lexical_from_vector["score"])
    recency = _recency_score(summary.get("occurred_at"))
    score = _hybrid_score(
        lexical=lexical_score,
        vector=vector_score,
        recency=recency,
        confidence=0.75,
        weights=(0.30, 0.50, 0.20, 0.0),
    )
    return {
        "type": "episode",
        "id": str(summary["id"]),
        "title": "Session summary",
        "summary": summary.get("summary"),
        "confidence": 0.75,
        "score": score,
        "source_refs": _source_refs_for_summary(summary, outbox_rows),
        "evidence_preview": _excerpt(vector_text or str(summary.get("summary") or ""), query, width=160),
        "occurred_at": str(summary.get("occurred_at") or ""),
        "metadata": {
            "lane": "episodic",
            "source_kind": "session_summary",
            "tags": summary.get("tags", []),
            "lexical_score": round(lexical_score, 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
        },
    }


def _build_archive_episode(
    row: dict[str, Any],
    *,
    lexical_meta: dict[str, Any],
    vector_hit: dict[str, Any] | None,
    outbox_rows: list[dict[str, Any]],
    query: str,
) -> dict[str, Any]:
    raw_content = embeddings.build_source_archive_search_text(row)
    vector_text = str((vector_hit or {}).get("text") or raw_content)
    vector_score = float((vector_hit or {}).get("vector_score", 0.0))
    lexical_from_vector = _score_match(vector_text, query)
    lexical_score = max(lexical_meta["score"], lexical_from_vector["score"])
    recency = _recency_score(row.get("occurred_at") or row.get("captured_at"))
    score = _hybrid_score(
        lexical=lexical_score,
        vector=vector_score,
        recency=recency,
        confidence=0.7,
        weights=(0.25, 0.55, 0.20, 0.0),
    )
    return {
        "type": "episode",
        "id": str(row["id"]),
        "title": row.get("session_id") or row.get("source_external_id") or row.get("source_type"),
        "summary": _truncate(vector_text, limit=120),
        "confidence": 0.7,
        "score": score,
        "source_refs": _source_refs_for_archive(row, outbox_rows),
        "evidence_preview": _excerpt(vector_text, query, width=160),
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
        },
    }


def _build_continuity_item(
    fact: dict[str, Any],
    *,
    lexical_meta: dict[str, Any],
    vector_score: float,
    outbox_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    content = fact.get("content") or {}
    confidence = float(fact.get("confidence", 0.0))
    recency = _recency_score(fact.get("last_seen_at") or fact.get("first_seen_at"))
    score = _hybrid_score(
        lexical=lexical_meta["score"],
        vector=vector_score,
        recency=recency,
        confidence=confidence,
        weights=(0.35, 0.35, 0.15, 0.15),
    )
    return {
        "type": "continuity_note",
        "id": str(fact["id"]),
        "title": content.get("title") or "Open loop",
        "summary": content.get("summary") or content.get("evidence", {}).get("raw_evidence"),
        "confidence": confidence,
        "score": score,
        "source_refs": _source_refs_for_fact(fact, outbox_rows),
        "evidence_preview": _truncate(content.get("evidence", {}).get("raw_evidence") or content.get("summary") or ""),
        "occurred_at": str(fact.get("last_seen_at") or fact.get("first_seen_at") or ""),
        "metadata": {
            "lane": "continuity",
            "derived": True,
            "fact_type": fact.get("fact_type"),
            "open_loop_status": _open_loop_status(fact),
            "linked_people": _linked_entities(content)["people"],
            "linked_projects": _linked_entities(content)["projects"],
            "linked_topics": _linked_entities(content)["topics"],
            "lexical_score": round(lexical_meta["score"], 4),
            "vector_score": round(vector_score, 4),
            "recency_score": round(recency, 4),
        },
    }


def _build_timeline_item(
    event: dict[str, Any],
    *,
    lexical_meta: dict[str, Any],
    vector_score: float,
    related_entities: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    confidence = float(event.get("confidence", 0.0))
    recency = _recency_score(event.get("observed_at") or event.get("occurred_at"))
    score = _hybrid_score(
        lexical=lexical_meta["score"],
        vector=vector_score,
        recency=recency,
        confidence=confidence,
        weights=(0.35, 0.40, 0.15, 0.10),
    )
    return {
        "type": "timeline_event",
        "id": str(event["id"]),
        "title": event.get("title") or event.get("event_type"),
        "summary": event.get("summary"),
        "confidence": confidence,
        "score": score,
        "source_refs": _source_refs_for_timeline(event),
        "evidence_preview": _truncate(event.get("summary") or event.get("title") or ""),
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
    }


def _strong_fact_match(item: dict[str, Any]) -> bool:
    return (
        float(item.get("confidence", 0.0)) > 0.8
        and item.get("score", 0.0) >= 0.25
        and (
            item.get("metadata", {}).get("lexical_score", 0.0) >= 0.05
            or item.get("metadata", {}).get("vector_score", 0.0) >= 0.82
        )
    )


def _include_candidate(lexical_score: float, vector_score: float, hybrid_score: float) -> bool:
    if lexical_score <= 0 and vector_score <= 0:
        return False
    return hybrid_score >= 0.22 or lexical_score >= 0.12 or vector_score >= 0.72


async def recall(
    database: Database,
    *,
    user_id: str,
    query: str,
    limit: int = 5,
    recall_type: str | None = None,
) -> dict[str, Any]:
    resolved_type = recall_type or _infer_recall_type(query)
    query_tokens = _normalized_tokens(query)
    facts = await fetch_active_confirmed_facts(database, user_id=user_id)
    summaries = await fetch_session_summaries(database, user_id=user_id)
    timeline = await fetch_timeline_events(database, user_id=user_id)
    source_archive_rows = await fetch_source_archive_rows(database, user_id=user_id)
    outbox_rows = await fetch_outbox_rows(database, user_id=user_id)
    facts_by_id = {str(fact["id"]): fact for fact in facts}
    vector_rows: list[dict[str, Any]] = []
    if any(len(token) >= 3 for token in query_tokens):
        vector_rows = await embeddings.search_retrieval_embeddings(
            database,
            user_id=user_id,
            query=query,
            source_types=["confirmed_fact", "session_summary", "source_archive_chunk", "timeline_event"],
            limit=max(limit * 8, 24),
        )
    vector_hits = _vector_hits_by_key(vector_rows)

    fact_ranked: list[dict[str, Any]] = []
    for fact in facts:
        lexical_meta = _score_match(_fact_search_text(fact), query)
        vector_score = float(vector_hits.get(("confirmed_fact", str(fact["id"])), {}).get("vector_score", 0.0))
        item = _build_fact_item(fact, lexical_meta=lexical_meta, vector_score=vector_score, outbox_rows=outbox_rows)
        if _include_candidate(lexical_meta["score"], vector_score, item["score"]):
            fact_ranked.append(item)
    fact_ranked.sort(key=lambda item: item["score"], reverse=True)

    summary_ranked: list[dict[str, Any]] = []
    for summary in summaries:
        vector_hit = vector_hits.get(("session_summary", str(summary["id"])))
        lexical_meta = _score_match(_summary_search_text(summary), query)
        item = _build_summary_episode(
            summary,
            lexical_meta=lexical_meta,
            vector_hit=vector_hit,
            outbox_rows=outbox_rows,
            query=query,
        )
        if _include_candidate(
            item["metadata"]["lexical_score"],
            item["metadata"]["vector_score"],
            item["score"],
        ):
            summary_ranked.append(item)
    summary_ranked.sort(key=lambda item: item["score"], reverse=True)

    archive_ranked: list[dict[str, Any]] = []
    for row in source_archive_rows:
        vector_hit = vector_hits.get(("source_archive_chunk", str(row["id"])))
        lexical_meta = _score_match(embeddings.build_source_archive_search_text(row), query)
        item = _build_archive_episode(
            row,
            lexical_meta=lexical_meta,
            vector_hit=vector_hit,
            outbox_rows=outbox_rows,
            query=query,
        )
        if _include_candidate(
            item["metadata"]["lexical_score"],
            item["metadata"]["vector_score"],
            item["score"],
        ):
            archive_ranked.append(item)
    archive_ranked.sort(key=lambda item: item["score"], reverse=True)

    continuity_ranked: list[dict[str, Any]] = []
    for fact in facts:
        if fact.get("fact_type") != "thread":
            continue
        if _open_loop_status(fact) not in {"active", "unresolved"}:
            continue
        lexical_meta = _score_match(_fact_search_text(fact), query)
        vector_score = float(vector_hits.get(("confirmed_fact", str(fact["id"])), {}).get("vector_score", 0.0))
        item = _build_continuity_item(fact, lexical_meta=lexical_meta, vector_score=vector_score, outbox_rows=outbox_rows)
        if _include_candidate(lexical_meta["score"], vector_score, item["score"]):
            continuity_ranked.append(item)
    for event in timeline:
        lexical_meta = _score_match(_timeline_search_text(event), query)
        vector_score = float(vector_hits.get(("timeline_event", str(event["id"])), {}).get("vector_score", 0.0))
        related_entities = {"people": [], "projects": [], "topics": []}
        for fact_id in event.get("related_fact_ids") or []:
            fact = facts_by_id.get(str(fact_id))
            if not fact:
                continue
            entities = _linked_entities(fact.get("content") or {})
            for kind in related_entities:
                related_entities[kind].extend(entities[kind])
        item = _build_timeline_item(event, lexical_meta=lexical_meta, vector_score=vector_score, related_entities=related_entities)
        if _include_candidate(lexical_meta["score"], vector_score, item["score"]):
            continuity_ranked.append(item)
    continuity_ranked.sort(key=lambda item: item["score"], reverse=True)

    continuity_items = [item for item in continuity_ranked if item["type"] == "continuity_note"]
    timeline_items = [item for item in continuity_ranked if item["type"] == "timeline_event"]
    episode_items = sorted(summary_ranked + archive_ranked, key=lambda item: item["score"], reverse=True)

    if resolved_type == "exact":
        combined = fact_ranked + continuity_items + timeline_items
    elif resolved_type == "episodic":
        combined = episode_items + continuity_items + timeline_items
    else:
        combined = fact_ranked + episode_items + continuity_items + timeline_items

    combined.sort(key=lambda item: item["score"], reverse=True)
    items = combined[:limit]
    strong_fact = any(_strong_fact_match(item) for item in fact_ranked[:limit])
    has_matches = bool(items)
    certainty = "high" if strong_fact else "partial" if has_matches else "low"
    weak_recall = certainty == "low"
    weak_recall_reason = None if has_matches else "No grounded factual, episodic, or continuity matches were found."

    return {
        "items": items,
        "facts": fact_ranked[:limit],
        "episodes": episode_items[:limit],
        "continuity": continuity_items[:limit],
        "timeline": timeline_items[:limit],
        "summaries": [
            {
                "id": item["id"],
                "summary": item["summary"],
                "tags": item.get("metadata", {}).get("tags", []),
                "occurred_at": item["occurred_at"],
            }
            for item in episode_items[:limit]
            if item.get("metadata", {}).get("source_kind") == "session_summary"
        ],
        "recall_type": resolved_type,
        "weak_recall": weak_recall,
        "weak_recall_reason": weak_recall_reason,
        "certainty": certainty,
    }
