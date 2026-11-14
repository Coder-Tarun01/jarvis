"""Preflight for the LLM path: which provider, is the key set, does a real call work?

    cd backend
    python scripts/check_llm.py              # completion + one tool call (the full path)
    python scripts/check_llm.py --no-tools   # skip the tool-call probe (cheaper)

It talks to the configured provider for real (a handful of tokens on a free model),
so it is the fastest way to tell "the key is wrong" apart from "the model has no
tool support" or "the free allowance is spent".

Exit codes
    0  everything works
    2  no API key configured
    3  the key was rejected (401)
    4  unknown model / no provider can serve it (404)
    5  rate limited or out of credit (429 / 402 / 403)
    1  anything else
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# backend/scripts/check_llm.py -> backend/  (so `app` imports work)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openai  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.errors import LLMNotConfigured  # noqa: E402
from app.services.llm import LLMService  # noqa: E402
from app.tools.registry import load_tools  # noqa: E402

OK, OTHER, NO_KEY, AUTH, NO_MODEL, LIMIT = 0, 1, 2, 3, 4, 5


def mask(key: str) -> str:
    if not key:
        return "(empty)"
    return f"...{key[-4:]} (len {len(key)})"


def explain(exc: BaseException) -> tuple[int, str]:
    """Map a provider failure to an exit code and a one-line explanation."""
    status = getattr(exc, "status_code", None)
    if isinstance(exc, openai.AuthenticationError) or status == 401:
        return AUTH, "the API key was rejected (401) — delete it and paste it again"
    if isinstance(exc, openai.NotFoundError) or status == 404:
        return NO_MODEL, (
            "unknown model, or no provider serves it (404) — check OPENROUTER_MODEL / OPENAI_MODEL"
        )
    if isinstance(exc, openai.RateLimitError) or status == 429:
        return LIMIT, "rate limited (429) — free tiers allow only a few requests per minute"
    if status in (402, 403):
        return LIMIT, f"out of free credit or blocked ({status}) — free allowances reset daily"
    if isinstance(exc, openai.BadRequestError) or status == 400:
        return OTHER, f"the request was rejected (400): {str(exc)[:180]}"
    return OTHER, f"{type(exc).__name__}: {str(exc)[:180]}"


async def probe(llm: LLMService, with_tools: bool) -> int:
    print(f"provider : {llm.provider_name}")
    print(f"model    : {llm.model}")
    print(f"fast     : {llm.model_fast}")
    print(f"base url : {getattr(llm._provider, 'base_url', '?')}")
    print(f"max tokens: {llm.settings.llm_max_tokens}")

    try:
        answer = await llm.complete(
            system="You are a health check. Answer with one word.",
            prompt="Reply with exactly: ready",
            max_tokens=12,
        )
    except LLMNotConfigured as exc:
        print(f"\nFAIL  {exc}")
        return NO_KEY
    except Exception as exc:  # noqa: BLE001 - mapped to an exit code
        code, why = explain(exc)
        print(f"\nFAIL  {why}")
        return code

    print(f"\nok    completion: {answer.strip()[:120]!r}")

    if not with_tools:
        return OK

    tools = load_tools()
    schema = tools["get_datetime"].schema() if "get_datetime" in tools else None
    if schema is None:
        print("skip  tool probe (get_datetime is not registered)")
        return OK

    try:
        turn = await llm.stream_turn(
            messages=[{"role": "user", "content": "What time is it right now? Use the tool."}],
            system="Use the get_datetime tool; do not guess.",
            tools=[schema],
            max_tokens=200,
        )
    except Exception as exc:  # noqa: BLE001
        code, why = explain(exc)
        print(f"FAIL  tool call: {why}")
        return code

    if turn.tool_calls:
        call = turn.tool_calls[0]
        print(f"ok    tool call: {call.name}({call.input})")
        return OK
    print(f"warn  no tool call returned (text: {turn.text[:120]!r})")
    print("      the model answered without tools - chat still works, tool use may be unreliable")
    return OK


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-tools", action="store_true", help="skip the tool-call probe")
    args = parser.parse_args()

    settings = get_settings()
    key_name = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(settings.provider, "OPENAI_API_KEY")
    print(f"key      : {key_name} = {mask(settings.llm_api_key)}")

    llm = LLMService(settings)
    return asyncio.run(probe(llm, with_tools=not args.no_tools))


if __name__ == "__main__":
    sys.exit(main())
