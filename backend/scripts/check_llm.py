"""Preflight for the LLM path: which provider, is the key set, does a real call work?

    cd backend
    python scripts/check_llm.py              # completion + one tool call (the full path)
    python scripts/check_llm.py --no-tools   # skip the tool-call probe (cheaper)
    python scripts/check_llm.py --tools      # do actions come back as real tool calls?
    python scripts/check_llm.py --models     # free OpenRouter models that support tools

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
            "unknown model, or no provider serves it (404) — check OPENROUTER_MODEL / "
            "OPENAI_MODEL; 'python scripts/check_llm.py --models' lists the free ones "
            "(note the ':free' suffix)"
        )
    if isinstance(exc, openai.RateLimitError) or status == 429:
        return LIMIT, "rate limited (429) — free tiers allow only a few requests per minute"
    if status in (402, 403):
        return LIMIT, f"out of free credit or blocked ({status}) — free allowances reset daily"
    if isinstance(exc, openai.BadRequestError) or status == 400:
        return OTHER, f"the request was rejected (400): {str(exc)[:180]}"
    return OTHER, f"{type(exc).__name__}: {str(exc)[:180]}"


def list_free_models(settings) -> int:
    """Print the free OpenRouter models that can call tools (model slugs change often)."""
    import httpx

    headers = (
        {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    )
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/models", headers=headers, timeout=30.0
        )
        response.raise_for_status()
        data = response.json()["data"]
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  could not fetch the model list: {exc}")
        return OTHER

    rows = []
    for model in data:
        pricing = model.get("pricing") or {}
        if str(pricing.get("prompt")) not in ("0", "0.0"):
            continue
        if "tools" not in (model.get("supported_parameters") or []):
            continue
        rows.append((model["id"], model.get("context_length") or 0))
    rows.sort(key=lambda row: -row[1])

    print(f"free models that support tool calls ({len(rows)}):")
    for model_id, context in rows:
        marker = "   <- configured" if model_id == settings.openrouter_model else ""
        print(f"  {model_id:<52} ctx={context}{marker}")
    print("\nput one of these in OPENROUTER_MODEL (the ':free' suffix is part of the id)")
    return OK


TOOL_PROBES: tuple[tuple[str, str], ...] = (
    ("open whatsapp", "open_desktop_app"),
    ("open anti-gravity", "open_desktop_app"),
    ("what is the time right now?", "get_datetime"),
    ("add a task to buy milk", "add_task"),
    ("send a whatsapp to Thamudu saying hello", "whatsapp_send_message"),
)


async def probe_tools(llm: LLMService) -> int:
    """Ask for real actions and report whether a *structured* tool call came back."""
    from app.services.persona import build_system_prompt
    from app.tools.registry import tool_schemas

    system = build_system_prompt(llm.settings)
    tools = tool_schemas()
    good = 0
    print(f"\ntool-calling probes ({len(tools)} tools offered, tool_choice=auto):")
    for prompt, expected in TOOL_PROBES:
        try:
            turn = await llm.stream_turn(
                messages=[{"role": "user", "content": prompt}],
                system=system,
                tools=tools,
                max_tokens=400,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {prompt!r}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        if turn.tool_calls:
            names = ", ".join(call.name for call in turn.tool_calls)
            hit = any(expected == call.name for call in turn.tool_calls)
            good += 1
            print(f"  ok    {prompt!r} -> {names}{'' if hit else f'  (expected {expected})'}")
        else:
            print(f"  warn  {prompt!r} -> NO TOOL CALL, said: {turn.text[:90]!r}")

    print(f"\n{good}/{len(TOOL_PROBES)} action prompts produced a tool call")
    if good < len(TOOL_PROBES):
        print(
            "text-only answers here are narration, not execution — keep the persona rules "
            "that forbid claiming an action, or switch to a model with steadier tool use"
        )
    return OK if good == len(TOOL_PROBES) else OTHER


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
    parser.add_argument(
        "--models",
        action="store_true",
        help="list the free OpenRouter models that support tool calls, then exit",
    )
    parser.add_argument(
        "--tools",
        action="store_true",
        help="run the tool-calling probes (actions must come back as structured calls)",
    )
    args = parser.parse_args()

    settings = get_settings()
    key_name = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(settings.provider, "OPENAI_API_KEY")
    print(f"key      : {key_name} = {mask(settings.llm_api_key)}")

    if args.models:
        return list_free_models(settings)

    llm = LLMService(settings)
    if args.tools:
        return asyncio.run(probe_tools(llm))
    return asyncio.run(probe(llm, with_tools=not args.no_tools))


if __name__ == "__main__":
    sys.exit(main())
