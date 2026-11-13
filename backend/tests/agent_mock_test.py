"""End-to-end agent test against a mocked OpenAI endpoint (no API key required).

Replays real Chat Completions SSE frames through the openai SDK so streaming,
tool-call delta accumulation and the confirmation gate are exercised for real.
"""

import asyncio
import json
import os
import sys
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_mock_test_")
os.environ["DATA_DIR"] = _TEST_DATA
os.environ["WORKSPACE_DIR"] = os.path.join(_TEST_DATA, "workspace")
os.environ["JARVIS_AUTH_TOKEN"] = "test-token"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = "sk-test-mock-key-for-tests"
os.environ["OPENAI_MODEL"] = "gpt-6.1-terra"
os.environ["OPENAI_MODEL_FAST"] = "gpt-5.4-mini"
os.environ["OPENAI_REASONING_EFFORT"] = "none"
os.environ["ANTHROPIC_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import openai  # noqa: E402

from app.core.agent import Agent  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal, init_db  # noqa: E402
from app.core.models import Conversation  # noqa: E402
from app.services.llm import LLMService  # noqa: E402
from app.services.llm_openai import OpenAIProvider  # noqa: E402

MODEL = "gpt-6.1-terra"
failures = []


def check(label, condition, extra=""):
    print(f"[{'ok  ' if condition else 'FAIL'}] {label} {extra}")
    if not condition:
        failures.append(label)


# --------------------------------------------------------------------------- SSE builders
def chunk(delta, finish=None):
    return "data: " + json.dumps(
        {
            "id": "chatcmpl-mock",
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


def tool_turn(name, args, call_id="call_1", preamble="One moment."):
    return (
        chunk({"role": "assistant", "content": ""})
        + chunk({"content": preamble})
        + chunk(
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
        # arguments arrive in fragments, exactly like the real API
        + chunk({"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(args)[:9]}}]})
        + chunk({"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(args)[9:]}}]})
        + chunk({}, "tool_calls")
        + "data: [DONE]\n\n"
    )


class FakeOpenAI:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def handler(self, request):
        self.requests.append(json.loads(request.content))
        sse = self.script.pop(0) if self.script else text_turn("Nothing left to say.")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse.encode("utf-8"),
        )


def make_llm(fake):
    settings = get_settings()
    service = LLMService(settings)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    # base_url must be explicit: the SDK would otherwise read the (blank)
    # OPENAI_BASE_URL from the environment and build relative URLs.
    service._provider._client = openai.AsyncOpenAI(
        api_key="sk-test-mock-key-for-tests",
        base_url=service._provider.base_url,
        http_client=http_client,
        max_retries=0,
    )
    return service


def _new_conversation(title):
    db = SessionLocal()
    conversation = Conversation(title=title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return db, conversation


async def scenario_tool_call():
    fake = FakeOpenAI([tool_turn("get_datetime", {}, "call_1"), text_turn("It is 3pm, boss.")])
    agent = Agent(get_settings(), make_llm(fake))
    db, conversation = _new_conversation("tool")

    events = []

    async def emit(payload):
        events.append(payload)

    async def confirm(*_args):
        raise AssertionError("get_datetime must not require confirmation")

    result = await agent.respond(db, conversation.id, "what time is it?", emit=emit, confirm=confirm)
    db.close()

    kinds = [event["type"] for event in events]
    check("provider is openai", agent.llm.provider_name == "openai", agent.llm.provider_name)
    check("streamed tokens", kinds.count("token") >= 2, str(kinds))
    check("tool_call emitted", "tool_call" in kinds)
    check("tool_result ok", any(e["type"] == "tool_result" and e["ok"] for e in events))
    check("final text", result["text"] == "It is 3pm, boss.", result["text"])
    check("two model calls", len(fake.requests) == 2, str(len(fake.requests)))

    first = fake.requests[0]
    check("system message first", first["messages"][0]["role"] == "system")
    check("openai model used", first["model"] == MODEL, first["model"])
    check("max_completion_tokens set", "max_completion_tokens" in first, str(first.get("max_completion_tokens")))
    check("reasoning_effort=none sent", first.get("reasoning_effort") == "none", str(first.get("reasoning_effort")))
    tool_def = (first.get("tools") or [{}])[0]
    check(
        "tools converted to function format",
        tool_def.get("type") == "function"
        and tool_def["function"]["name"] == "get_datetime"
        and tool_def["function"]["parameters"]["type"] == "object",
        str(tool_def)[:160],
    )

    second = fake.requests[1]
    assistant = second["messages"][-2]
    tool_message = second["messages"][-1]
    check(
        "assistant tool_calls echoed back",
        assistant["role"] == "assistant"
        and assistant["tool_calls"][0]["id"] == "call_1"
        and assistant["tool_calls"][0]["function"]["name"] == "get_datetime",
        str(assistant)[:160],
    )
    check(
        "tool result sent as role=tool",
        tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_1",
        str(tool_message)[:160],
    )


async def scenario_denied():
    fake = FakeOpenAI(
        [
            tool_turn("run_command", {"command": "git status"}, "call_2"),
            text_turn("Understood, I won't run it."),
        ]
    )
    agent = Agent(get_settings(), make_llm(fake))
    db, conversation = _new_conversation("denied")

    asked = []

    async def emit(_payload):
        return None

    async def confirm(call_id, name, arguments, hint):
        asked.append((call_id, name, arguments, hint))
        return False

    result = await agent.respond(db, conversation.id, "run git status", emit=emit, confirm=confirm)
    db.close()

    check("confirmation requested once", len(asked) == 1 and asked[0][1] == "run_command", str(asked))
    tool_message = fake.requests[1]["messages"][-1]
    check(
        "denial fed back to the model",
        tool_message["role"] == "tool" and "declined" in tool_message["content"].lower(),
        str(tool_message)[:160],
    )
    check("final answer after denial", "won't run" in result["text"], result["text"])


def scenario_bad_arguments():
    """A malformed argument fragment must not crash the provider."""
    turn = OpenAIProvider._turn_from_state(
        ["thinking"],
        {0: {"id": "call_x", "name": "get_datetime", "arguments": '{"city": '}},
        "tool_calls",
        MODEL,
    )
    check("bad JSON tolerated", turn.tool_calls and turn.tool_calls[0].input == {}, str(turn.tool_calls))
    check("raw arguments preserved", turn.tool_calls[0].raw_arguments == '{"city": ')


async def main():
    init_db()
    await scenario_tool_call()
    await scenario_denied()
    scenario_bad_arguments()


asyncio.run(main())

print("")
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("AGENT MOCK TEST PASSED")
