from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Reranker(Protocol):
    def rank(self, query: str, candidates: list[dict], mode: str) -> list[dict]:
        ...


@dataclass(slots=True)
class NoopReranker:
    def rank(self, query: str, candidates: list[dict], mode: str) -> list[dict]:
        return list(candidates)


@dataclass(slots=True)
class HeuristicReranker:
    def rank(self, query: str, candidates: list[dict], mode: str) -> list[dict]:
        ranked = list(candidates)
        ranked.sort(
            key=lambda item: (
                float(item.get("score", 0.0)),
                len((item.get("evidence") or {}).get("match_reasons", [])),
            ),
            reverse=True,
        )
        return ranked


def get_reranker(name: str | None = None) -> Reranker:
    normalized = (name or "noop").strip().lower()
    if normalized == "noop":
        return NoopReranker()
    if normalized == "heuristic":
        return HeuristicReranker()
    raise RuntimeError(f"Unsupported reranker: {name}")
