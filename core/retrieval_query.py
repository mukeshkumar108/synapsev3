from __future__ import annotations

import re
from typing import Any

from core.db import Database
from core.entity_repository import fetch_entity_aliases, fetch_entity_links, resolve_entity_by_name


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


def normalize_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"\b([a-z0-9_]+)'s\b", r"\1", lowered)
    lowered = re.sub(r"\b([a-z0-9_]+)s'\b", r"\1", lowered)
    return lowered


def normalized_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_]+", normalize_text(value))
    return [token for token in tokens if token and token not in STOPWORDS]


def infer_recall_type(query: str) -> str:
    lowered = normalize_text(query)
    if any(lowered.startswith(pattern) for pattern in EXACT_PATTERNS):
        return "exact"
    if any(marker in lowered for marker in EPISODIC_MARKERS) or ("remember" in lowered and "conversation" in lowered):
        return "episodic"
    return "hybrid"


def _query_spans(query: str, *, max_words: int = 4) -> list[str]:
    normalized = normalize_text(query)
    words = re.findall(r"[a-z0-9_]+", normalized)
    spans: list[str] = []
    seen: set[str] = set()
    if normalized.strip():
        spans.append(normalized.strip())
        seen.add(normalized.strip())
    for width in range(min(max_words, len(words)), 0, -1):
        for index in range(len(words) - width + 1):
            span = " ".join(words[index : index + width]).strip()
            if not span or span in seen:
                continue
            seen.add(span)
            spans.append(span)
    return spans


async def expand_query_entities(
    database: Database,
    *,
    user_id: str,
    query: str,
) -> dict[str, Any]:
    resolved_entities: list[dict[str, Any]] = []
    expanded_terms: list[str] = []
    seen_entity_ids: set[str] = set()
    seen_terms: set[str] = set()

    for span in _query_spans(query):
        entity = await resolve_entity_by_name(database, user_id=user_id, name=span)
        if entity is None:
            continue
        entity_id = str(entity["id"])
        if entity_id in seen_entity_ids:
            continue
        seen_entity_ids.add(entity_id)
        aliases = await fetch_entity_aliases(database, user_id=user_id, entity_id=entity["id"])
        links = await fetch_entity_links(database, user_id=user_id, entity_id=entity["id"])
        entity_payload = {
            **entity,
            "aliases": aliases,
            "links": links,
            "matched_span": span,
        }
        resolved_entities.append(entity_payload)
        for term in [str(entity.get("canonical_name") or "").strip(), span]:
            if term and term.lower() not in seen_terms:
                seen_terms.add(term.lower())
                expanded_terms.append(term)
        for alias in aliases:
            alias_text = str(alias.get("alias_text") or "").strip()
            if alias_text and alias_text.lower() not in seen_terms:
                seen_terms.add(alias_text.lower())
                expanded_terms.append(alias_text)

    return {
        "original_query": query,
        "resolved_entities": resolved_entities,
        "expanded_terms": expanded_terms,
    }
