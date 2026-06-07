from __future__ import annotations

from core.reranking import NoopReranker, get_reranker


def test_noop_reranker_preserves_input_order() -> None:
    candidates = [
        {"id": "1", "type": "fact", "score": 0.4},
        {"id": "2", "type": "episode", "score": 0.9},
    ]
    ranked = NoopReranker().rank("query", candidates, "hybrid")
    assert [item["id"] for item in ranked] == ["1", "2"]


def test_get_reranker_defaults_to_noop() -> None:
    reranker = get_reranker()
    ranked = reranker.rank("query", [{"id": "1", "type": "fact", "score": 0.1}], "hybrid")
    assert ranked[0]["id"] == "1"
