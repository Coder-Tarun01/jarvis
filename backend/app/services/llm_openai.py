"""OpenAI Chat Completions provider (default).

Design notes
------------
* Streaming text goes straight to the UI callback, so the WebSocket contract does
  not change.
* Tool calls arrive as deltas: ``index`` identifies the slot, ``id``/``name`` land
  in the first chunk and ``function.arguments`` streams in fragments. We
  accumulate per index and ``json.loads`` the result safely (a malformed
  fragment yields empty arguments rather than a crash).
* Results go back as ``role="tool"`` messages carrying ``tool_call_id``.
* Retries use jittered backoff on 408/409/429/5xx and connection errors, and are
  never attempted once text has already been streamed to the browser.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import openai
from openai import AsyncOpenAI

from ..core.config import Settings, get_settings
from ..core.errors import LLMNotConfigured
from ..core.logging import get_logger
from ..core.utils import retry_async
from .llm import LLMTurn, TextCallback, ToolCall, is_retryable

log = get_logger("llm.openai")

#: Tool output larger than this is clipped before it reaches the model.
MAX_TOOL_CONTENT = 20000

#: Explicit default: the SDK reads OPENAI_BASE_URL from the environment, and an
#: empty value (compose injects `OPENAI_BASE_URL=`) would otherwise poison it.
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: AsyncOpenAI | None = None

    # ------------------------------------------------------------------ identity
    @property
    def available(self) -> bool:
        return bool(self.settings.openai_api_key)

    @property
    def model(self) -> str:
        return self.settings.openai_model

    @property
    def model_fast(self) -> str:
        return self.settings.openai_model_fast or self.model

    @property
    def base_url(self) -> str:
        """Always an absolute http(s) URL, even when OPENAI_BASE_URL is blank."""
        raw = (self.settings.openai_base_url or "").strip()
        if not raw:
            return DEFAULT_BASE_URL
        if not raw.lower().startswith(("http://", "https://")):
            raw = "https://" + raw
        return raw.rstrip("/")

    def _get_client(self) -> AsyncOpenAI:
        if not self.available:
            raise LLMNotConfigured(
                "OPENAI_API_KEY is not configured. Put it in .env and restart JARVIS."
            )
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.base_url,
                timeout=self.settings.openai_timeout,
                max_retries=0,  # this module owns the backoff policy
            )
        return self._client

    # ------------------------------------------------------------------ tool formats
    def format_tools(self, schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Registry schemas (name/description/input_schema) -> OpenAI function tools."""
        tools: list[dict[str, Any]] = []
        for schema in schemas or []:
            name = schema.get("name")
            if not name:
                continue
            parameters = schema.get("input_schema") or {"type": "object", "properties": {}}
            if parameters.get("type") != "object":
                parameters = {"type": "object", "properties": {}}
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": schema.get("description", ""),
                        "parameters": parameters,
                    },
                }
            )
        return tools

    def tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for result in results or []:
            content = str(result.get("content") or "")
            if result.get("is_error"):
                content = f"ERROR: {content}"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(result.get("tool_use_id") or ""),
                    "content": content[:MAX_TOOL_CONTENT],
                }
            )
        return messages

    # ------------------------------------------------------------------ request building
    def _payload(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
        max_tokens: int | None,
        model: str | None,
        stream: bool,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + list(messages),
            "max_completion_tokens": int(max_tokens or self.settings.openai_max_tokens),
        }
        if stream:
            payload["stream"] = True
        if tools:
            payload["tools"] = self.format_tools(tools)
            payload["tool_choice"] = "auto"
        effort = (self.settings.openai_reasoning_effort or "").strip()
        if effort:
            payload["reasoning_effort"] = effort
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

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
        payload = self._payload(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            model=model,
            stream=True,
        )

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
                return await self._stream_once(client, payload, on_delta)
            except openai.BadRequestError as exc:
                message = str(exc).lower()
                if payload.get("reasoning_effort") and "reasoning_effort" in message:
                    log.warning(
                        "model rejected reasoning_effort=%s; retrying without it",
                        payload["reasoning_effort"],
                    )
                    payload.pop("reasoning_effort", None)
                    continue
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if state["emitted"] or not is_retryable(exc) or attempt >= attempts:
                    raise
                delay = min(20.0, 1.5 * (2 ** (attempt - 1)))
                log.warning(
                    "OpenAI stream failed (%s/%s): %s - retrying in %.1fs",
                    attempt, attempts, exc, delay,
                )
                await asyncio.sleep(delay)
        raise last_error or RuntimeError("OpenAI stream failed")

    async def _stream_once(
        self,
        client: AsyncOpenAI,
        payload: dict[str, Any],
        on_delta: TextCallback,
    ) -> LLMTurn:
        text_parts: list[str] = []
        slots: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        model_name = str(payload.get("model", ""))

        stream = await client.chat.completions.create(**payload)
        async for chunk in stream:
            model_name = getattr(chunk, "model", None) or model_name
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]

            delta = getattr(choice, "delta", None)
            if delta is not None:
                piece = getattr(delta, "content", None)
                if piece:
                    text_parts.append(piece)
                    await on_delta(piece)

                for tool_delta in getattr(delta, "tool_calls", None) or []:
                    index = int(getattr(tool_delta, "index", 0) or 0)
                    slot = slots.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if getattr(tool_delta, "id", None):
                        slot["id"] = tool_delta.id
                    function = getattr(tool_delta, "function", None)
                    if function is not None:
                        if getattr(function, "name", None):
                            slot["name"] = function.name
                        if getattr(function, "arguments", None):
                            slot["arguments"] += function.arguments

            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason

        return self._turn_from_state(text_parts, slots, finish_reason, model_name)

    @staticmethod
    def _turn_from_state(
        text_parts: list[str],
        slots: dict[int, dict[str, str]],
        finish_reason: str | None,
        model_name: str,
    ) -> LLMTurn:
        text = "".join(text_parts).strip()
        calls: list[ToolCall] = []

        for index in sorted(slots):
            slot = slots[index]
            raw = slot.get("arguments") or ""
            arguments: dict[str, Any] = {}
            if raw.strip():
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    log.warning(
                        "tool %s sent unparseable arguments (%s): %s",
                        slot.get("name") or index, exc, raw[:200],
                    )
                    parsed = None
                if isinstance(parsed, dict):
                    arguments = parsed
                elif parsed is not None:
                    arguments = {"value": parsed}
            if not slot.get("name"):
                continue
            calls.append(
                ToolCall(
                    id=slot.get("id") or f"call_{index}",
                    name=slot["name"],
                    input=arguments,
                    raw_arguments=raw,
                )
            )

        assistant_message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            assistant_message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw_arguments or json.dumps(call.input),
                    },
                }
                for call in calls
            ]

        return LLMTurn(
            text=text,
            assistant_message=assistant_message,
            tool_calls=calls,
            stop_reason=finish_reason,
            usage={},
            model=model_name,
        )

    # ------------------------------------------------------------------ one-shot calls
    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 600,
        model: str | None = None,
        json_mode: bool = False,
    ) -> str:
        client = self._get_client()
        payload = self._payload(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            tools=None,
            max_tokens=max_tokens,
            model=model or self.model_fast,
            stream=False,
            json_mode=json_mode,
        )

        async def call() -> str:
            try:
                response = await client.chat.completions.create(**payload)
            except openai.BadRequestError as exc:
                if payload.get("response_format"):
                    log.warning("model rejected JSON mode (%s); retrying as plain text", exc)
                    payload.pop("response_format", None)
                    response = await client.chat.completions.create(**payload)
                else:
                    raise
            message = response.choices[0].message
            return (message.content or "").strip()

        return await retry_async(
            call, attempts=3, label=f"openai.complete[{payload['model']}]", retry_if=is_retryable
        )
