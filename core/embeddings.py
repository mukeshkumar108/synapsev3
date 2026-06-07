from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from typing import Any, Protocol

from core.db import Database


DEFAULT_EMBEDDING_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "8"))
DEFAULT_CHUNK_WORDS = 48
DEFAULT_CHUNK_OVERLAP = 12

_SEMANTIC_GROUPS = {
    "spiritual": {"god", "faith", "divine", "sacred", "religion", "religious", "spiritual", "universe"},
    "meaning": {"meaning", "purpose", "purposeful", "significance"},
    "work": {"job", "work", "career", "office", "boss", "coworker", "manager"},
    "stress": {"stress", "stressed", "anxious", "anxiety", "overwhelmed", "pressure"},
    "relationship": {"partner", "relationship", "boyfriend", "girlfriend", "wife", "husband"},
}


class EmbeddingProvider(Protocol):
    dimension: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


def _normalize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _semantic_tokens(text: str) -> list[str]:
    base_tokens = _normalize(text)
    expanded = list(base_tokens)
    token_set = set(base_tokens)
    for group_name, group_tokens in _SEMANTIC_GROUPS.items():
        if token_set & group_tokens:
            expanded.append(f"group:{group_name}")
    return expanded


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(0.0, min(1.0, numerator / (left_norm * right_norm)))


@dataclass(slots=True)
class DeterministicEmbeddingProvider:
    dimension: int = DEFAULT_EMBEDDING_DIMENSION

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _semantic_tokens(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0) * 0.25
            vector[bucket] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    provider_name = os.environ.get("EMBEDDING_PROVIDER", "deterministic").strip().lower()
    if provider_name == "deterministic":
        return DeterministicEmbeddingProvider()
    raise RuntimeError(f"Unsupported embedding provider: {provider_name}")


def build_fact_embedding_text(fact: dict[str, Any]) -> str:
    content = fact.get("content") or {}
    evidence = content.get("evidence") or {}
    links = content.get("links") or {}
    return " ".join(
        part.strip()
        for part in [
            str(content.get("title") or ""),
            str(content.get("summary") or ""),
            str(evidence.get("raw_evidence") or ""),
            " ".join(str(item) for item in links.get("people", []) if str(item).strip()),
            " ".join(str(item) for item in links.get("projects", []) if str(item).strip()),
            " ".join(str(item) for item in links.get("topics", []) if str(item).strip()),
        ]
        if str(part or "").strip()
    )


def build_session_summary_embedding_text(summary: dict[str, Any]) -> str:
    return str(summary.get("summary") or "").strip()


def build_timeline_event_embedding_text(event: dict[str, Any]) -> str:
    return " ".join(
        part.strip()
        for part in [
            str(event.get("title") or ""),
            str(event.get("summary") or ""),
        ]
        if str(part or "").strip()
    )


def build_source_archive_search_text(row: dict[str, Any]) -> str:
    payload = row.get("payload") or {}
    raw_content = str(payload.get("raw_content") or "").strip()
    if raw_content:
        return raw_content
    messages = payload.get("messages") or []
    message_lines = []
    for message in messages:
        role = str(message.get("role") or "unknown").strip()
        content = str(message.get("content") or "").strip()
        if content:
            message_lines.append(f"{role}: {content}")
    if message_lines:
        return "\n".join(message_lines)
    return str(payload).strip()


def chunk_text(text: str, *, max_words: int = DEFAULT_CHUNK_WORDS, overlap_words: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    step = max(1, max_words - overlap_words)
    while start < len(words):
        chunk = " ".join(words[start : start + max_words]).strip()
        if chunk:
            chunks.append(chunk)
        if start + max_words >= len(words):
            break
        start += step
    return chunks


async def upsert_retrieval_embedding(
    database: Database,
    *,
    user_id: str,
    source_type: str,
    source_id: Any,
    text: str,
    embedding: list[float],
    source_archive_id: Any = None,
    chunk_index: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await database.execute(
        """
        INSERT INTO retrieval_embeddings (
            id, user_id, source_type, source_id, source_archive_id, chunk_index,
            text, embedding, metadata, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), $1, $2, $3, $4, $5,
            $6, $7::vector, $8::jsonb, $9, $10
        )
        ON CONFLICT (user_id, source_type, source_id, COALESCE(chunk_index, -1))
        DO UPDATE SET
            source_archive_id = EXCLUDED.source_archive_id,
            text = EXCLUDED.text,
            embedding = EXCLUDED.embedding,
            metadata = EXCLUDED.metadata,
            updated_at = EXCLUDED.updated_at
        """,
        user_id,
        source_type,
        source_id,
        source_archive_id,
        chunk_index,
        text,
        _vector_literal(embedding),
        metadata or {},
        now,
        now,
    )


async def index_confirmed_fact(database: Database, fact: dict[str, Any], *, provider: EmbeddingProvider | None = None) -> None:
    provider = provider or get_embedding_provider()
    text = build_fact_embedding_text(fact)
    if not text:
        return
    [embedding] = await provider.embed_texts([text])
    await upsert_retrieval_embedding(
        database,
        user_id=fact["user_id"],
        source_type="confirmed_fact",
        source_id=fact["id"],
        text=text,
        embedding=embedding,
        metadata={
            "fact_type": fact.get("fact_type"),
            "domain": fact.get("domain"),
            "confidence": float(fact.get("confidence", 0.0)),
        },
    )


async def index_session_summary(database: Database, summary: dict[str, Any], *, provider: EmbeddingProvider | None = None) -> None:
    provider = provider or get_embedding_provider()
    text = build_session_summary_embedding_text(summary)
    if not text:
        return
    [embedding] = await provider.embed_texts([text])
    await upsert_retrieval_embedding(
        database,
        user_id=summary["user_id"],
        source_type="session_summary",
        source_id=summary["id"],
        text=text,
        embedding=embedding,
        metadata={
            "source_id": str(summary.get("source_id") or ""),
            "occurred_at": str(summary.get("occurred_at") or ""),
            "tags": summary.get("tags", []),
        },
    )


async def index_timeline_event(database: Database, event: dict[str, Any], *, provider: EmbeddingProvider | None = None) -> None:
    provider = provider or get_embedding_provider()
    text = build_timeline_event_embedding_text(event)
    if not text:
        return
    [embedding] = await provider.embed_texts([text])
    await upsert_retrieval_embedding(
        database,
        user_id=event["user_id"],
        source_type="timeline_event",
        source_id=event["id"],
        text=text,
        embedding=embedding,
        metadata={
            "event_type": event.get("event_type"),
            "timeline_type": event.get("timeline_type"),
            "confidence": float(event.get("confidence", 0.0)),
        },
    )


async def index_source_archive(database: Database, row: dict[str, Any], *, provider: EmbeddingProvider | None = None) -> None:
    provider = provider or get_embedding_provider()
    base_text = build_source_archive_search_text(row)
    chunks = chunk_text(base_text)
    if not chunks:
        return
    embeddings = await provider.embed_texts(chunks)
    for chunk_index, (chunk_text_value, embedding) in enumerate(zip(chunks, embeddings)):
        await upsert_retrieval_embedding(
            database,
            user_id=row["user_id"],
            source_type="source_archive_chunk",
            source_id=row["id"],
            source_archive_id=row["id"],
            chunk_index=chunk_index,
            text=chunk_text_value,
            embedding=embedding,
            metadata={
                "source_type": row.get("source_type"),
                "session_id": row.get("session_id"),
                "conversation_id": row.get("conversation_id"),
            },
        )


async def search_retrieval_embeddings(
    database: Database,
    *,
    user_id: str,
    query: str,
    source_types: list[str],
    limit: int = 20,
    provider: EmbeddingProvider | None = None,
) -> list[dict[str, Any]]:
    provider = provider or get_embedding_provider()
    [query_embedding] = await provider.embed_texts([query])
    if hasattr(database, "retrieval_embeddings"):
        ranked = []
        for row in getattr(database, "retrieval_embeddings"):
            if row.get("user_id") != user_id or row.get("source_type") not in source_types:
                continue
            score = _cosine_similarity(row.get("embedding") or [], query_embedding)
            ranked.append({**row, "vector_score": score})
        ranked.sort(key=lambda row: row["vector_score"], reverse=True)
        return ranked[:limit]
    return await database.fetch(
        """
        SELECT
            id,
            user_id,
            source_type,
            source_id,
            source_archive_id,
            chunk_index,
            text,
            metadata,
            created_at,
            updated_at,
            GREATEST(0.0, 1 - (embedding <=> $3::vector)) AS vector_score
        FROM retrieval_embeddings
        WHERE user_id = $1
          AND source_type = ANY($2::text[])
        ORDER BY embedding <=> $3::vector, created_at DESC
        LIMIT $4
        """,
        user_id,
        source_types,
        _vector_literal(query_embedding),
        limit,
    )
