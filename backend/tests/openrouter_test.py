"""OpenRouter provider: selection, request shape and streaming (all offline).

The OpenAI SDK is pointed at an ``httpx.MockTransport``, so payload shape,
attribution headers, SSE tool-call accumulation and the JSON-mode fallback are
verified without a key and without spending anyone's free quota.
"""

import asyncio
import json
import os
import sys
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_openrouter_test_")
os.environ["DATA_DIR"] = _TEST_DATA
os.environ["WORKSPACE_DIR"] = os.path.join(_TEST_DATA, "workspace")
os.environ["JARVIS_AUTH_TOKEN"] = "test-token"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import openai  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.errors import LLMNotConfigured  # noqa: E402
from app.services.llm import LLMService, is_retryable  # noqa: E402
from app.services.llm_openrouter import OpenRouterProvider  # noqa: E402

MODEL = "baidu/ernie-5.5-flash-preview:free"
failures = []


def check(label, condition, extra=""):
    print(f"[{'ok  ' if condition else 'FAIL'}] {label} {extra}")
    if not condition:
        failures.append(label)


def make_settings(**overrides):
    """OpenRouter pinned per test, independent of the project .env."""
    base = {
        "llm_provider": "openrouter",
        "openrouter_api_key": "or-test-key",
        "openrouter_model": MODEL,
        "openrouter_model_fast": "",
        "openrouter_max_tokens": 900,
        "openrouter_timeout": 30.0,
        "openrouter_referer": "https://jarvis.local",
        "openrouter_title": "JARVIS",
        "openai_api_key": "",
        "anthropic_api_key": "",
    }
    base.update(overrides)
    return Settings(**base)


# --------------------------------------------------------------------------- SSE builders
def chunk(delta, finish=None):
    return "data: " + json.dumps(
        {
            "id": "gen-mock",
            "object": "chat.completion.chunk",
            "created": 1730000000,
            "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    ) + "\n\n"


def text_turn(text):
    return (
        chunk({"role": "assistant", "content": ""})
        + chunk({"content": text})
        + chunk({}, "stop")
        + "data: [DONE]\n\n"
    )


def tool_turn(name, args_fragments, call_id="call_or_1", preamble="One moment."):
    body = chunk({"role": "assistant", "content": ""}) + chunk({"content": preamble})
    body += chunk(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": ""},
                }
            ]
        }
    )
    for fragment in args_fragments:
        body += chunk({"tool_calls": [{"index": 0, "function": {"arguments": fragment}}]})
    body += chunk({}, "tool_calls") + "data: [DONE]\n\n"
    return body


class Fake:
    """Records requests and replays canned responses."""

    def __init__(self, sse=None, status=200, error=None, reject_json_mode=False):
        self.sse = sse
        self.status = status
        self.error = error
        self.reject_json_mode = reject_json_mode
        self.requests = []
        self.calls = 0

    def handler(self, request):
        self.calls += 1
        self.requests.append(
            {
                "url": str(request.url),
                "path": request.url.path,
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "body": json.loads(request.content or b"{}"),
            }
        )
        if self.reject_json_mode and self.calls == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "response_format is not supported by this model",
                    }
                },
            )
        if self.status != 200:
            return httpx.Response(self.status, json=self.error or {"error": {"message": "boom"}})
        if self.reject_json_mode:
            return httpx.Response(
                200,
                json={
                    "id": "gen-plain",
                    "object": "chat.completion",
                    "model": MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": '{"ok": true}'},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            content=(self.sse or text_turn("hello")).encode(),
            headers={"content-type": "text/event-stream"},
        )


def provider_with(fake):
    """Real provider, mocked transport (same trick as agent_mock_test.py)."""
    provider = OpenRouterProvider(make_settings())
    provider._client = openai.AsyncOpenAI(
        api_key="or-test-key",
        base_url=provider.base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
        default_headers=provider._default_headers(),
        max_retries=0,
    )
    return provider


# --------------------------------------------------------------------------- selection
print("--- provider selection")
settings = make_settings()
check("provider normalised to openrouter", settings.provider == "openrouter", settings.provider)
check("llm_configured reads the OpenRouter key", settings.llm_configured is True)
check("llm_model is the free model", settings.llm_model == MODEL, settings.llm_model)
check("fast model falls back to the same model", settings.llm_model_fast == MODEL, settings.llm_model_fast)
check("llm_max_tokens comes from OPENROUTER_MAX_TOKENS", settings.llm_max_tokens == 900)
check("reasoning_effort is never sent for OpenRouter", settings.llm_reasoning_effort == "")

service = LLMService(settings)
check("factory builds the OpenRouter provider", service.provider_name == "openrouter", service.provider_name)
check("facade reports the free model", service.model == MODEL, service.model)
check("provider is available with a key", service.available is True)

broken = LLMService(make_settings(openrouter_api_key=""))
check("no key -> unavailable", broken.available is False)
try:
    asyncio.run(broken.complete(system="s", prompt="p"))
    check("missing key names OPENROUTER_API_KEY", False)
except LLMNotConfigured as exc:
    check("missing key names OPENROUTER_API_KEY", "OPENROUTER_API_KEY" in str(exc), str(exc)[:80])

check("unknown provider still falls back to openai", Settings(llm_provider="nope").provider == "openai")

# --------------------------------------------------------------------------- request shape
print("\n--- request shape")
provider = OpenRouterProvider(make_settings())
payload = provider._payload(
    messages=[{"role": "user", "content": "hi"}],
    system="you are JARVIS",
    tools=[
        {
            "name": "get_datetime",
            "description": "current time",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
    ],
    max_tokens=None,
    model=None,
    stream=True,
)
check("uses max_tokens", payload.get("max_tokens") == 900, str(payload.get("max_tokens")))
check("never sends max_completion_tokens", "max_completion_tokens" not in payload)
check("never sends reasoning_effort", "reasoning_effort" not in payload)
check("asks for usage/cost", payload.get("extra_body") == {"usage": {"include": True}}, str(payload.get("extra_body")))
check("model is the free one", payload["model"] == MODEL, payload["model"])
check(
    "system message is first",
    payload["messages"][0] == {"role": "system", "content": "you are JARVIS"},
)
check("tools are function-shaped", payload["tools"][0]["function"]["name"] == "get_datetime")
check("tool_choice auto", payload.get("tool_choice") == "auto")
check("stream flag set", payload.get("stream") is True)

json_payload = provider._payload(
    messages=[{"role": "user", "content": "x"}],
    system="",
    tools=None,
    max_tokens=50,
    model=None,
    stream=False,
    json_mode=True,
)
check("json_mode adds response_format", json_payload.get("response_format") == {"type": "json_object"})
check("explicit max_tokens wins", json_payload.get("max_tokens") == 50)

check("base url is openrouter", provider.base_url == "https://openrouter.ai/api/v1", provider.base_url)
check(
    "attribution headers built",
    provider._default_headers() == {"HTTP-Referer": "https://jarvis.local", "X-Title": "JARVIS"},
    str(provider._default_headers()),
)
bare = OpenRouterProvider(make_settings(openrouter_referer="", openrouter_title=""))
check("attribution headers omitted when blank", bare._default_headers() is None)

# --------------------------------------------------------------------------- streaming
print("\n--- streaming")
streamed = []


async def _collect(piece):
    streamed.append(piece)


stream_fake = Fake(sse=text_turn("Dinner is at eight."))
turn = asyncio.run(
    provider_with(stream_fake).stream_turn(
        messages=[{"role": "user", "content": "when is dinner"}],
        system="be brief",
        on_text=_collect,
    )
)
request = stream_fake.requests[0]
check("posts to /api/v1/chat/completions", request["path"] == "/api/v1/chat/completions", request["path"])
check("sends the bearer key", request["headers"].get("authorization") == "Bearer or-test-key")
check("sends X-Title", request["headers"].get("x-title") == "JARVIS", str(request["headers"].get("x-title")))
check("sends HTTP-Referer", request["headers"].get("http-referer") == "https://jarvis.local")
check("body streams", request["body"].get("stream") is True)
check("body uses max_tokens", "max_tokens" in request["body"], str(sorted(request["body"])))
check("body asks for usage/cost", request["body"].get("usage") == {"include": True}, str(request["body"].get("usage")))
check("text assembled from deltas", turn.text == "Dinner is at eight.", turn.text)
check("text streamed to the UI callback", "".join(streamed) == "Dinner is at eight.", "".join(streamed))
check("assistant message is replayable", turn.assistant_message.get("role") == "assistant")
check("model echoed", turn.model == MODEL, turn.model)

print("\n--- streaming tool calls")
tool_fake = Fake(sse=tool_turn("get_datetime", ['{"city"', ': "Delhi"}']))
tool_result = asyncio.run(
    provider_with(tool_fake).stream_turn(
        messages=[{"role": "user", "content": "time?"}],
        system="s",
        tools=[
            {
                "name": "get_datetime",
                "description": "d",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
)
check("one tool call assembled", len(tool_result.tool_calls) == 1, str(tool_result.tool_calls))
check("tool name captured", tool_result.tool_calls[0].name == "get_datetime")
check("arguments stitched from fragments", tool_result.tool_calls[0].input == {"city": "Delhi"}, str(tool_result.tool_calls[0].input))
check("preamble text kept", tool_result.text == "One moment.", tool_result.text)
check("stop reason recorded", tool_result.stop_reason == "tool_calls", str(tool_result.stop_reason))

# --------------------------------------------------------------------------- one-shot calls
print("\n--- complete()")
fake = Fake(reject_json_mode=True)
answer = asyncio.run(provider_with(fake).complete(system="s", prompt="p", json_mode=True))
check("json mode rejected -> plain retry works", answer == '{"ok": true}', answer)
check("two attempts were made", fake.calls == 2, str(fake.calls))
check(
    "first attempt asked for json",
    fake.requests[0]["body"].get("response_format") == {"type": "json_object"},
)
check("retry dropped response_format", "response_format" not in fake.requests[1]["body"])
check("one-shot uses the fast model", fake.requests[0]["body"]["model"] == MODEL)

# --------------------------------------------------------------------------- errors
print("\n--- errors")
retry_fake = Fake(status=429, error={"error": {"code": 429, "message": "rate limited"}})


async def rate_limited():
    return await provider_with(retry_fake).complete(system="s", prompt="p")


try:
    asyncio.run(rate_limited())
    check("429 surfaces as an error", False)
except Exception as exc:  # noqa: BLE001 - the point is the retry policy
    check("429 surfaces as an error", is_retryable(exc), type(exc).__name__)
    check("429 retried before giving up", retry_fake.calls == 3, str(retry_fake.calls))

print("")
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("all openrouter checks passed")
