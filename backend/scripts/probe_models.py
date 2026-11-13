"""Probe the account's OpenAI models for streaming function-tool support.

    cd backend
    python scripts/probe_models.py

Prints a recommendation for OPENAI_MODEL (main) and OPENAI_MODEL_FAST (cheap).
Never prints the API key. Costs a handful of tokens per candidate.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import openai
except ImportError:  # pragma: no cover
    sys.exit("pip install openai")

ROOT = Path(__file__).resolve().parents[2]

MAIN_CANDIDATES = [
    "gpt-6.1-terra",
    "gpt-6.1-sol",
    "gpt-6-sol",
    "gpt-6-luna",
    "chat-latest",
    "gpt-5.6-terra",
    "gpt-5.5",
    "gpt-5.4",
]
FAST_CANDIDATES = ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5-mini", "gpt-4.1-mini"]

TOOL = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Return the current time for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
PROMPT = [{"role": "user", "content": "Call get_time for Paris. Use the tool."}]


def load_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def tool_test(client: "openai.OpenAI", model: str, effort: str | None) -> list[str] | None:
    payload = {
        "model": model,
        "messages": PROMPT,
        "tools": [TOOL],
        "tool_choice": "auto",
        "max_completion_tokens": 80,
    }
    if effort:
        payload["reasoning_effort"] = effort
    try:
        response = client.chat.completions.create(**payload)
    except Exception as exc:  # noqa: BLE001
        print(f"  {model:20} effort={str(effort):6} FAILED {type(exc).__name__}: {str(exc)[:100]}")
        return None
    calls = [call.function.name for call in (response.choices[0].message.tool_calls or [])]
    print(f"  {model:20} effort={str(effort):6} tool_calls={calls}")
    return calls


def stream_test(client: "openai.OpenAI", model: str, effort: str | None) -> bool:
    payload = {
        "model": model,
        "messages": PROMPT,
        "tools": [TOOL],
        "stream": True,
        "max_completion_tokens": 80,
    }
    if effort:
        payload["reasoning_effort"] = effort
    slots: dict[int, str] = {}
    try:
        for chunk in client.chat.completions.create(**payload):
            if not chunk.choices:
                continue
            for delta in getattr(chunk.choices[0].delta, "tool_calls", None) or []:
                slots[delta.index] = slots.get(delta.index, "") + (delta.function.arguments or "")
    except Exception as exc:  # noqa: BLE001
        print(f"  {model:20} stream FAILED {type(exc).__name__}: {str(exc)[:100]}")
        return False
    parsed = [json.loads(slot) for slot in slots.values() if slot.strip()]
    print(f"  {model:20} stream ok, parsed args={parsed}")
    return bool(parsed)


def main() -> int:
    key = load_key()
    if not key:
        print("OPENAI_API_KEY is not set (environment or .env)")
        return 1

    client = openai.OpenAI(api_key=key, timeout=60.0, max_retries=0)
    models = sorted(model.id for model in client.models.list())
    print(f"account can see {len(models)} models")

    print("\nmain candidates (function tools on /chat/completions):")
    main_ok: list[tuple[str, str]] = []
    for model in MAIN_CANDIDATES:
        if model not in models:
            continue
        if tool_test(client, model, "none"):
            main_ok.append((model, "none"))
        elif tool_test(client, model, None):
            main_ok.append((model, ""))

    print("\nstreaming check for the first working candidate:")
    if main_ok:
        stream_test(client, main_ok[0][0], main_ok[0][1] or None)

    print("\nfast candidates:")
    fast_ok = [
        model
        for model in FAST_CANDIDATES
        if model in models and tool_test(client, model, "none")
    ]

    print("\nrecommendation:")
    print("  OPENAI_MODEL=" + (main_ok[0][0] if main_ok else "(none found)"))
    print("  OPENAI_REASONING_EFFORT=" + (main_ok[0][1] if main_ok else ""))
    print("  OPENAI_MODEL_FAST=" + (fast_ok[0] if fast_ok else "(none found)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
