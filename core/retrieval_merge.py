from __future__ import annotations

from typing import Any


def merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (str(candidate.get("type")), str(candidate.get("id")))
        existing = merged.get(key)
        if existing is None:
            payload = dict(candidate)
            payload["evidence"] = {
                "match_reasons": list((candidate.get("evidence") or {}).get("match_reasons", [])),
                "lane_hits": list((candidate.get("evidence") or {}).get("lane_hits", [])),
            }
            merged[key] = payload
            continue
        existing["score"] = max(float(existing.get("score", 0.0)), float(candidate.get("score", 0.0)))
        existing["confidence"] = max(float(existing.get("confidence", 0.0)), float(candidate.get("confidence", 0.0)))
        existing["source_refs"] = list(dict.fromkeys(list(existing.get("source_refs", [])) + list(candidate.get("source_refs", []))))
        evidence = existing.setdefault("evidence", {"match_reasons": [], "lane_hits": []})
        for reason in (candidate.get("evidence") or {}).get("match_reasons", []):
            if reason not in evidence["match_reasons"]:
                evidence["match_reasons"].append(reason)
        for lane in (candidate.get("evidence") or {}).get("lane_hits", []):
            if lane not in evidence["lane_hits"]:
                evidence["lane_hits"].append(lane)
        existing_metadata = existing.setdefault("metadata", {})
        for key_name in ("linked_people", "linked_projects", "linked_topics"):
            existing_metadata[key_name] = list(
                dict.fromkeys(list(existing_metadata.get(key_name, [])) + list((candidate.get("metadata") or {}).get(key_name, [])))
            )
    return list(merged.values())
