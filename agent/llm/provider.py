"""The seam between this module and whatever serves the model.

Every generative call in the pipeline goes through `LLMProvider.generate`, never
directly through an HTTP client. That keeps the model a config value — dev
against a small local model, run the regression suite against the shared
qwen2.5:14b-instruct — and it's what makes the "degrade, don't block" principle
enforceable in one place instead of scattered through every call site.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol, TypeVar

from pydantic import BaseModel

logger = logging.getLogger("qa_agent.llm")

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(Exception):
    """Raised when the model cannot be reached or exhausts its retries.

    Callers catch this specifically and fall through to the deterministic path
    — it is the one exception in this module that is always expected and never
    a bug in itself.
    """


class LLMProvider(Protocol):
    def generate(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        examples: Optional[list[tuple[str, BaseModel]]] = None,
    ) -> BaseModel:
        """Return a validated instance of `schema`, or raise LLMUnavailable."""
        ...


@dataclass
class ProviderConfig:
    """Connection details for the shared model.

    `num_ctx` and `keep_alive` are deliberately absent — this module is a
    tenant of a shared instance and must not dictate either. If the host's
    context window ever needs mirroring, it's set once here rather than per
    call, so there is exactly one place that can drift out of sync.
    """

    host: str = "http://127.0.0.1:11434"
    model: str = "qwen3.8:latest"
    temperature: float = 0.0
    timeout_s: float = 120.0
    max_retries: int = 2
    max_concurrency: int = 1   # a bounded queue, not a fan-out, on a shared endpoint


def log_call(task: str, ok: bool, detail: str = "") -> None:
    level = logging.INFO if ok else logging.WARNING
    logger.log(level, "llm task=%s ok=%s %s", task, ok, detail)
