from __future__ import annotations

import re
import threading
from typing import Any, Callable

from runtime.cortex_client import CortexClient


SchedulerFn = Callable[[Callable[..., Any], tuple[Any, ...], dict[str, Any]], None]

RECALL_PATTERNS = [
    re.compile(r"\bdo you remember\b", re.IGNORECASE),
    re.compile(r"\bremember\b(?!\s+to\b)", re.IGNORECASE),
    re.compile(r"\bwhat did i say about\b", re.IGNORECASE),
    re.compile(r"\btell me about what we discussed\b", re.IGNORECASE),
    re.compile(r"\bwhat happened with\b", re.IGNORECASE),
]


def _default_scheduler(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    thread.start()


class SophieRuntime:
    def __init__(
        self,
        *,
        cortex_client: CortexClient,
        fallback_client: Any | None = None,
        timezone: str = "UTC",
        platform: str = "runtime",
        scheduler: SchedulerFn | None = None,
    ) -> None:
        self.cortex_client = cortex_client
        self.fallback_client = fallback_client
        self.timezone = timezone
        self.platform = platform
        self.scheduler = scheduler or _default_scheduler

    def start_session(
        self,
        *,
        user_id: str,
        session_id: str,
        current_datetime: str | None = None,
    ) -> dict[str, Any]:
        try:
            packet = self.cortex_client.get_startup_packet(
                user_id,
                current_datetime=current_datetime,
                timezone=self.timezone,
            )
            source = "v3"
        except Exception:
            if not self.fallback_client:
                raise
            packet = self.fallback_client.get_startup_packet(user_id)
            source = "v2_fallback"
        return {
            "user_id": user_id,
            "session_id": session_id,
            "timezone": self.timezone,
            "platform": self.platform,
            "instruction_packet": packet,
            "startup_source": source,
            "last_recall": None,
        }

    def should_trigger_recall(self, message_text: str) -> bool:
        return any(pattern.search(message_text) for pattern in RECALL_PATTERNS)

    def handle_recall(
        self,
        session_context: dict[str, Any],
        *,
        message_text: str,
    ) -> dict[str, Any] | None:
        if not self.should_trigger_recall(message_text):
            return None
        try:
            result = self.cortex_client.recall(session_context["user_id"], message_text)
            source = "v3"
        except Exception:
            if not self.fallback_client:
                raise
            result = self.fallback_client.recall(session_context["user_id"], message_text)
            source = "v2_fallback"

        if result.get("certainty") == "low":
            note = "I don't have a strong memory match for that yet."
        else:
            note = "I found some relevant memory to use for this question."

        session_context["last_recall"] = result
        return {
            "used_recall": True,
            "source": source,
            "recall_result": result,
            "runtime_note": note,
        }

    def close_session(
        self,
        session_context: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
    ) -> None:
        payload = {
            "user_id": session_context["user_id"],
            "session_id": session_context["session_id"],
            "messages": messages,
            "source_type": "chat",
            "metadata": {
                "timezone": session_context.get("timezone", self.timezone),
                "platform": session_context.get("platform", self.platform),
            },
        }
        self.scheduler(self._ingest_with_fallback, (), payload)

    def _ingest_with_fallback(self, **payload: Any) -> None:
        try:
            self.cortex_client.ingest_session(**payload)
        except Exception:
            if self.fallback_client and hasattr(self.fallback_client, "ingest_session"):
                self.fallback_client.ingest_session(**payload)
