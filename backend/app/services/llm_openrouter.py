"""OpenRouter provider — free-tier models on an OpenAI-compatible endpoint.

Why this exists: when the OpenAI quota runs out, ``LLM_PROVIDER=openrouter`` keeps
the assistant answering through ``https://openrouter.ai/api/v1`` (same Chat
Completions shape, same streaming SSE, same tool-call deltas), so the agent, the
WebSocket contract and the frontend do not change at all.

Everything that is *not* standard Chat Completions is inherited from
:class:`~app.services.llm_openai.OpenAIProvider`; this subclass only adjusts what
OpenRouter genuinely differs on:

* the API key / model / base URL come from ``OPENROUTER_*``
* ``max_tokens`` instead of OpenAI's ``max_completion_tokens``
* **no** ``reasoning_effort`` — OpenRouter takes a ``reasoning`` object, and free
  models reject the OpenAI spelling
* ``usage: {"include": true}`` so the final chunk reports tokens and cost
* optional ``HTTP-Referer`` / ``X-Title`` attribution headers

Free models are rate limited (OpenRouter answers ``429`` with a ``Retry-After``),
which the inherited backoff already treats as retryable; ``402`` means the free
allowance for the day is spent and is reported as-is.
"""

from __future__ import annotations

from typing import Any

from ..core.config import Settings
from .llm_openai import OpenAIProvider

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAIProvider):
    """``LLM_PROVIDER=openrouter`` — e.g. ``baidu/ernie-5.5-flash-preview`` (free)."""

    name = "openrouter"
    token_field = "max_tokens"
    default_base_url = DEFAULT_BASE_URL
    key_variable = "OPENROUTER_API_KEY"

    # ------------------------------------------------------------------ identity
    @property
    def available(self) -> bool:
        return bool(self.settings.openrouter_api_key)

    @property
    def model(self) -> str:
        return self.settings.openrouter_model

    @property
    def model_fast(self) -> str:
        return self.settings.openrouter_model_fast or self.settings.openrouter_model

    @property
    def _raw_base_url(self) -> str:
        return (self.settings.openrouter_base_url or "").strip()

    def _api_key(self) -> str:
        return self.settings.openrouter_api_key

    def _timeout(self) -> float:
        return self.settings.openrouter_timeout

    def _default_headers(self) -> dict[str, str] | None:
        """Attribution headers OpenRouter uses for its app rankings (optional)."""
        headers: dict[str, str] = {}
        referer = (self.settings.openrouter_referer or "").strip()
        title = (self.settings.openrouter_title or "").strip()
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-Title"] = title
        return headers or None

    # ------------------------------------------------------------------ request building
    def _max_tokens_default(self) -> int:
        return self.settings.openrouter_max_tokens

    def _extra_payload(self) -> dict[str, Any]:
        # OpenRouter reports token counts + cost in the trailing chunk when asked;
        # it travels via extra_body because it is not a named SDK parameter.
        return {"extra_body": {"usage": {"include": True}}}
