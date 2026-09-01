"""Ollama-backed LLMProvider.

Structured output goes through Ollama's `format` field with a JSON Schema, which
does grammar-constrained decoding — the response cannot be malformed JSON. That
is treated as non-negotiable here: nothing in this module falls back to regex
scraping a text response, because a 14B (and more so a small dev-time model)
under-constrained will occasionally narrate instead of answering.
"""

from __future__ import annotations

import json
import threading
from typing import Optional

import httpx
from pydantic import BaseModel, ValidationError

from .provider import LLMUnavailable, ProviderConfig, log_call


class OllamaProvider:
    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig()
        self._client = httpx.Client(
            base_url=self.config.host, timeout=self.config.timeout_s
        )
        # A bounded queue, not a fan-out — this endpoint may be shared with a
        # much larger host application, and firing a dozen concurrent
        # cluster-naming calls at it is not this module's call to make.
        self._gate = threading.Semaphore(self.config.max_concurrency)

    def close(self) -> None:
        self._client.close()

    def generate(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        examples: Optional[list[tuple[str, BaseModel]]] = None,
    ) -> BaseModel:
        prompt = self._build_prompt(system, user, examples)
        json_schema = schema.model_json_schema()

        last_error: Optional[Exception] = None
        with self._gate:
            for attempt in range(self.config.max_retries + 1):
                try:
                    raw = self._call(prompt, json_schema)
                    parsed = schema.model_validate_json(raw)
                    log_call(schema.__name__, ok=True)
                    return parsed
                except (httpx.HTTPError, ValidationError, ValueError,
                        json.JSONDecodeError) as e:
                    last_error = e
                    log_call(schema.__name__, ok=False, detail=str(e)[:160])

        raise LLMUnavailable(
            f"{schema.__name__} failed after {self.config.max_retries + 1} "
            f"attempt(s): {last_error}"
        ) from last_error

    def _build_prompt(
        self, system: str, user: str,
        examples: Optional[list[tuple[str, BaseModel]]],
    ) -> list[dict]:
        messages = [{"role": "system", "content": system}]
        for ex_input, ex_output in examples or []:
            messages.append({"role": "user", "content": ex_input})
            messages.append({
                "role": "assistant",
                "content": ex_output.model_dump_json(),
            })
        messages.append({"role": "user", "content": user})
        return messages

    def _call(self, messages: list[dict], json_schema: dict) -> str:
        # num_ctx and keep_alive are intentionally not set — this provider is a
        # tenant of a shared model instance. Diverging options force a reload
        # that evicts whatever else is loaded on the host application's side.
        resp = self._client.post(
            "/api/chat",
            json={
                "model": self.config.model,
                "messages": messages,
                "format": json_schema,
                "stream": False,
                "options": {"temperature": self.config.temperature},
            },
        )
        resp.raise_for_status()
        body = resp.json()
        content = body.get("message", {}).get("content", "")
        if not content:
            raise ValueError("empty response content")
        return content

    def healthy(self) -> bool:
        try:
            resp = self._client.get("/api/version", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
