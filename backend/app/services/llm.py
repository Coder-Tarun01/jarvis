"""Provider-neutral LLM interface.

``LLM_PROVIDER`` selects the backend:

* ``openai``     (default)  -> :mod:`app.services.llm_openai`
* ``anthropic``  (optional) -> :mod:`app.services.llm_anthropic`
* ``openrouter`` (free tier)-> :mod:`app.services.llm_openrouter`

The agent and the memory extractor only talk to this module. A provider returns a
neutral :class:`LLMTurn` (text + assistant message + tool calls) and knows how to
turn tool results into its own message shape, so the WebSocket event contract and
the frontend stay untouched.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from ..core.config import Settings, get_settings
from ..core.errors import LLMNotConfigured
from ..core.logging import get_logger

log = get_logger("llm")

TextCallback = Callable[[str], Awaitable[None]]

#: Transient HTTP statuses worth another attempt (matches OpenAI + Anthropic advice).
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}

#: Exception class names that always mean "try again".
RETRYABLE_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
    "ServiceUnavailableError",
    "OverloadedError",
    "ConflictError",
}


def is_retryable(exc: BaseException) -> bool:
    """Rate limits, transient 5xx and connection problems are worth a retry."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in RETRYABLE_STATUS:
        return True
    return type(exc).__name__ in RETRYABLE_NAMES


def explain_error(exc: BaseException) -> str | None:
    """Turn a provider failure into a line a human can act on (None = unknown)."""
    status = getattr(exc, "status_code", None)
    text = str(exc)
    lowered = text.lower()

    if status == 429:
        if "per-day" in lowered or "free-models-per-day" in lowered or "daily" in lowered:
            return (
                "The free OpenRouter allowance for today is used up. Add $10 of credits for "
                "1000 free requests/day (https://openrouter.ai/settings/credits), wait for the "
                "daily reset, or switch LLM_PROVIDER back to openai in .env and restart."
            )
        return "The provider is rate limiting requests — wait a few seconds and try again."
    if status == 402:
        return "The provider says this API key is out of credit."
    if status == 403:
        return "The provider blocked this request (spend limit reached, key disabled or access denied)."
    if status == 401:
        return (
            "The API key was rejected — paste a fresh one with host\\set-openrouter-key.ps1 "
            "and restart the backend."
        )
    if status == 404:
        return (
            "That model does not exist on the provider — run "
            "'python scripts/check_llm.py --models' and put a valid id in OPENROUTER_MODEL."
        )
    return None


@dataclass(slots=True)
class ToolCall:
    """One tool invocation requested by the model."""

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""


@dataclass
class LLMTurn:
    """One assistant turn in provider-neutral form."""

    text: str = ""
    #: Assistant message exactly as the provider expects it back in history.
    assistant_message: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.text or self.tool_calls or self.assistant_message)


class Provider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    @property
    def model(self) -> str: ...

    @property
    def model_fast(self) -> str: ...

    async def stream_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        on_text: TextCallback | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        tool_choice: str | None = None,
    ) -> LLMTurn: ...

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 600,
        model: str | None = None,
        json_mode: bool = False,
    ) -> str: ...

    def tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def format_tools(self, schemas: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(raw: str) -> Any:
    """Pull the first JSON object/array out of a model reply. None if hopeless."""
    if not raw:
        return None
    candidates = [m.group(1) for m in _JSON_BLOCK.finditer(raw)] + [raw]
    for candidate in candidates:
        candidate = candidate.strip()
        for opener, closer in (("[", "]"), ("{", "}")):
            start = candidate.find(opener)
            end = candidate.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(candidate[start:end + 1])
                except json.JSONDecodeError:
                    continue
    return None


class LLMService:
    """Facade over the configured provider (same interface the agent already uses)."""

    def __init__(self, settings: Settings | None = None, provider: Provider | None = None) -> None:
        self.settings = settings or get_settings()
        self._provider: Provider = provider if provider is not None else self._build_provider()

    def _build_provider(self) -> Provider:
        if self.settings.provider == "anthropic":
            from .llm_anthropic import AnthropicProvider

            log.info("LLM provider: anthropic (%s)", self.settings.anthropic_model)
            return AnthropicProvider(self.settings)

        if self.settings.provider == "openrouter":
            from .llm_openrouter import OpenRouterProvider

            log.info("LLM provider: openrouter (%s)", self.settings.openrouter_model)
            return OpenRouterProvider(self.settings)

        from .llm_openai import OpenAIProvider

        log.info("LLM provider: openai (%s)", self.settings.openai_model)
        return OpenAIProvider(self.settings)

    # ------------------------------------------------------------------ identity
    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "name", self.settings.provider)

    @property
    def available(self) -> bool:
        return bool(self._provider.available)

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def model_fast(self) -> str:
        return self._provider.model_fast

    def _require(self) -> None:
        if not self.available:
            key_name = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
            }.get(self.settings.provider, "OPENAI_API_KEY")
            hint = {
                "openai": "create one at https://platform.openai.com/api-keys",
                "anthropic": "create one at https://console.anthropic.com/settings/keys",
                "openrouter": (
                    "free keys: https://openrouter.ai/settings/keys — then run "
                    "host\\set-openrouter-key.ps1 (or add it to .env yourself) and restart JARVIS"
                ),
            }.get(self.settings.provider, "")
            raise LLMNotConfigured(
                f"{key_name} is not configured — {hint}. "
                f"Check the whole path with: python scripts/check_llm.py"
            )

    # ------------------------------------------------------------------ turns
    async def stream_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        on_text: TextCallback | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        tool_choice: str | None = None,
    ) -> LLMTurn:
        self._require()
        return await self._provider.stream_turn(
            messages=messages,
            system=system,
            tools=tools,
            on_text=on_text,
            max_tokens=max_tokens,
            model=model,
            tool_choice=tool_choice,
        )

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 600,
        model: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self._require()
        return await self._provider.complete(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            model=model,
            json_mode=json_mode,
        )

    async def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 600,
        model: str | None = None,
    ) -> Any:
        """Ask the fast model for JSON and parse it defensively."""
        raw = await self.complete(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            model=model or self.model_fast,
            json_mode=True,
        )
        parsed = extract_json(raw)
        if parsed is None:
            log.warning("could not parse JSON from the fast model reply: %r", (raw or "")[:200])
        return parsed

    # ------------------------------------------------------------------ tool plumbing
    def tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._provider.tool_result_messages(results)

    def format_tools(self, schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._provider.format_tools(schemas)


_llm: LLMService | None = None


def get_llm() -> LLMService:
    """Process-wide client (connection pooling comes for free)."""
    global _llm
    if _llm is None:
        _llm = LLMService()
    return _llm


def reset_llm() -> None:
    """Test helper: forget the cached service."""
    global _llm
    _llm = None
