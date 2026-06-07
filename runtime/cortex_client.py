from __future__ import annotations

import json
from typing import Any, Callable
from urllib import parse, request


RequestFn = Callable[..., dict[str, Any]]


class CortexClient:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8000",
        request_fn: RequestFn | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._request_fn = request_fn

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._request_fn is not None:
            return self._request_fn(method, path, params=params, json_body=json_body)

        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{parse.urlencode(params)}"
        body = None
        headers = {}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=body, headers=headers, method=method)
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_startup_packet(
        self,
        user_id: str,
        *,
        current_datetime: str | None = None,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"user_id": user_id, "timezone": timezone}
        if current_datetime:
            params["current_datetime"] = current_datetime
        return self._request("GET", "/v3/sessions/instruction-packet", params=params)

    def recall(
        self,
        user_id: str,
        query_text: str,
        *,
        limit: int = 5,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v3/recall",
            json_body={"user_id": user_id, "query": query_text, "limit": limit},
        )

    def ingest_session(
        self,
        *,
        user_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
        source_type: str = "chat",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v3/session/ingest",
            json_body={
                "user_id": user_id,
                "session_id": session_id,
                "messages": messages,
                "source_type": source_type,
                "metadata": metadata or {},
            },
        )
