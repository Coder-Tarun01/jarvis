"""Anthropic Claude provider — optional fallback, enabled with LLM_PROVIDER=anthropic.

Kept deliberately thin: it implements the same neutral interface as the OpenAI
provider (streamed text, tool calls, tool results) and contains no
prompt-thinking configuration. The ``anthropic`` package is imported lazily so an
OpenAI-only deployment never needs it at runtime.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..core.config import Settings, get_settings
from ..core.errors import LLMNotConfigured
from ..core.logging import get_logger
from ..core.utils import retry_async
from .llm import LLMTurn, TextCallback, ToolCall, is_retryable

log = get_logger("llm.anthropic")


def _blocks_to_params(content: Any) -> list[dict[str, Any]]:
    """SDK content blocks -> request-safe parameter dicts."""
    out: list[dict[str, Any]] = []
    for block in content or []:
        if isinstance(block, dict):
            data = dict(block)
        elif hasattr(block, "model_dump"):
            data = block.model_dump(exclude_none=True)
        else:  # pragma: no cover - defensive
            continue
        btype = data.get("type")
        if btype == "text":
            out.append({"type": "text", "text": data.get("text", "")})
        elif btype == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "id": data.get("id", ""),
                    "name": data.get("name", ""),
                    "input": data.get("input") or {},
                }
            )
        elif btype == "thinking":
            out.append(
                {
                    "type": "thinking",
                    "thinking": data.get("thinking", ""),
                    "signature": data.get("signature", ""),
                }
            )
        elif btype == "redacted_thinking":
            out.append({"type": "redacted_thinking", "data": data.get("data", "")})
    return out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any = None

    # ------------------------------------------------------------------ identity
    @property
    def available(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    @property
    def model(self) -> str:
        return self.settings.anthropic_model

    @property
    def model_fast(self) -> str:
        return self.settings.anthropic_utility_model or self.model

    def _get_client(self) -> Any:
        if not self.available:
            raise LLMNotConfigured(
                "ANTHROPIC_API_KEY is not configured. Set it in .env, or use LLM_PROVIDER=openai."
            )
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise LLMNotConfigured(
                    "The anthropic package is not installed. Run: pip install anthropic"
                ) from exc
            self._client = anthropic.AsyncAnthropic(
                api_key=self.settings.anthropic_api_key,
                timeout=self.settings.anthropic_timeout,
                max_retries=0,
            )
        return self._client

    # ------------------------------------------------------------------ tool formats
    def format_tools(self, schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tools = []
        for schema in schemas or []:
            name = schema.get("name")
            if not name:
                continue
            tools.append(
                {
                    "name": name,
                    "description": schema.get("description", ""),
                    "input_schema": schema.get("input_schema")
                    or {"type": "object", "properties": {}},
                }
            )
        return tools

    def tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        blocks = [
            {
                "type": "tool_result",
                "tool_use_id": str(result.get("tool_use_id") or ""),
                "content": str(result.get("content") or ""),
                "is_error": bool(result.get("is_error")),
            }
            for result in results or []
        ]
        return [{"role": "user", "content": blocks}] if blocks else []

    # ------------------------------------------------------------------ streaming turn
    async def stream_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        on_text: TextCallback | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> LLMTurn:
        client = self._get_client()
        params: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": int(max_tokens or self.settings.anthropic_max_tokens),
            "system": system,
            "messages": messages,
        }
        if tools:
            params["tools"] = self.format_tools(tools)

        attempts = 3
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            state = {"emitted": False}

            async def on_delta(piece: str, _state: dict = state) -> None:
                if not piece:
                    return
                _state["emitted"] = True
                if on_text is not None:
                    await on_text(piece)

            try:
                return await self._stream_once(client, params, on_delta)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if state["emitted"] or not is_retryable(exc) or attempt >= attempts:
                    raise
                delay = min(20.0, 1.5 * (2 ** (attempt - 1)))
                log.warning(
                    "Anthropic stream failed (%s/%s): %s - retrying in %.1fs",
                    attempt, attempts, exc, delay,
                )
                await asyncio.sleep(delay)
        raise last_error or RuntimeError("Anthropic stream failed")

    async def _stream_once(
        self,
        client: Any,
        params: dict[str, Any],
        on_delta: TextCallback,
    ) -> LLMTurn:
        chunks: list[str] = []
        async with client.messages.stream(**params) as stream:
            async for event in stream:
                if getattr(event, "type", "") != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                if getattr(delta, "type", "") != "text_delta":
                    continue
                piece = getattr(delta, "text", "") or ""
                if piece:
                    chunks.append(piece)
                    await on_delta(piece)
            message = await stream.get_final_message()

        blocks = _blocks_to_params(getattr(message, "content", []))
        text = "".join(chunks).strip() or "\n".join(
            block.get("text", "") for block in blocks if block.get("type") == "text"
        ).strip()

        calls = [
            ToolCall(
                id=block.get("id", ""),
                name=block.get("name", ""),
                input=block.get("input") or {},
                raw_arguments="",
            )
            for block in blocks
            if block.get("type") == "tool_use"
        ]

        usage: dict[str, Any] = {}
        raw_usage = getattr(message, "usage", None)
        if raw_usage is not None and hasattr(raw_usage, "model_dump"):
            usage = raw_usage.model_dump()

        return LLMTurn(
            text=text,
            assistant_message={"role": "assistant", "content": blocks},
            tool_calls=calls,
            stop_reason=getattr(message, "stop_reason", None),
            usage=usage,
            model=getattr(message, "model", params["model"]),
        )

    # ------------------------------------------------------------------ one-shot calls
    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 600,
        model: str | None = None,
        json_mode: bool = False,  # noqa: ARG002 - parity with the OpenAI provider
    ) -> str:
        client = self._get_client()
        params: dict[str, Any] = {
            "model": model or self.model_fast,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }

        async def call() -> str:
            message = await client.messages.create(**params)
            blocks = _blocks_to_params(getattr(message, "content", []))
            return "\n".join(
                block.get("text", "") for block in blocks if block.get("type") == "text"
            ).strip()

        return await retry_async(call, attempts=3, label="anthropic.complete", retry_if=is_retryable)
