from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


class LLMClient:
    def __init__(self) -> None:
        _load_dotenv()
        self.provider = os.environ.get("LLM_PROVIDER") or self._default_provider()
        self.model = os.environ.get("LLM_MODEL") or self._default_model()
        self.timeout_seconds = float(os.environ.get("LLM_TIMEOUT_SECONDS", "45"))

    def _default_provider(self) -> str:
        if os.environ.get("OPENROUTER_API_KEY"):
            return "openrouter"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        raise RuntimeError("No supported LLM API key found in environment.")

    def _default_model(self) -> str:
        if self.provider == "openrouter":
            return "openai/gpt-4.1-mini"
        return "gpt-4.1-mini"

    def _endpoint(self) -> str:
        if self.provider == "openrouter":
            return "https://openrouter.ai/api/v1/chat/completions"
        if self.provider == "openai":
            return "https://api.openai.com/v1/chat/completions"
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {self.provider}")

    def _headers(self) -> dict[str, str]:
        if self.provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY is not set.")
            return {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "http://localhost"),
                "X-Title": os.environ.get("OPENROUTER_APP_NAME", "synapse-v3"),
            }

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> Any:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        req = request.Request(
            self._endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed with HTTP {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected LLM response shape: {body}") from exc

        if not isinstance(content, str):
            raise RuntimeError(f"LLM content was not a string: {content!r}")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON: {content}") from exc
