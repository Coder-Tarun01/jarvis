"""Tool-calling robustness: narrated calls recovered, false claims caught.

Three layers, all offline:
  1. ``tool_text.recover_tool_calls`` — parsing the model's text-channel calls
  2. the provider turning those into real ToolCalls (mock SSE)
  3. the agent's one-shot correction when a reply claims an action it never ran
"""

import asyncio
import json
import os
import sys
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_toolcall_test_")
os.environ["DATA_DIR"] = _TEST_DATA
os.environ["WORKSPACE_DIR"] = os.path.join(_TEST_DATA, "workspace")
os.environ["JARVIS_AUTH_TOKEN"] = "test-token"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import openai  # noqa: E402

from app.core.agent import CORRECTION, UNVERIFIED_REPLY, Agent  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.db import SessionLocal, init_db  # noqa: E402
from app.core.models import Conversation  # noqa: E402
from app.services.llm import LLMTurn, ToolCall  # noqa: E402
from app.services.llm_openrouter import OpenRouterProvider  # noqa: E402
from app.services.tool_text import recover_tool_calls  # noqa: E402

MODEL = "baidu/ernie-5.5-flash-preview:free"
TOOLS = {"open_desktop_app", "whatsapp_send_message", "get_datetime", "add_task"}
failures = []


def check(label, condition, extra=""):
    print(f"[{'ok  ' if condition else 'FAIL'}] {label} {extra}")
    if not condition:
        failures.append(label)


# --------------------------------------------------------------------------- 1. parser
print("--- narrated tool calls are parsed")

calls, cleaned = recover_tool_calls(
    '[used tools] open_desktop_app(app="whatsapp")\nWhatsApp\'s open.', TOOLS
)
check("marker + kwargs form", calls == [("open_desktop_app", {"app": "whatsapp"})], str(calls))
check("call line removed from the reply", cleaned == "WhatsApp's open.", repr(cleaned))

calls, cleaned = recover_tool_calls(
    'open_desktop_app({"app": "antigravity", "arguments": ["--new"]})', TOOLS
)
check(
    "JSON arguments",
    calls == [("open_desktop_app", {"app": "antigravity", "arguments": ["--new"]})],
    str(calls),
)
check("nothing left over", cleaned == "", repr(cleaned))

calls, _ = recover_tool_calls("whatsapp_send_message(to=Thamudu, message=Hello there)", TOOLS)
check(
    "unquoted values",
    calls == [("whatsapp_send_message", {"to": "Thamudu", "message": "Hello there"})],
    str(calls),
)

calls, _ = recover_tool_calls("get_datetime()", TOOLS)
check("empty argument list", calls == [("get_datetime", {})], str(calls))

calls, _ = recover_tool_calls('* add_task(title="buy milk", urgent=true, count=2)', TOOLS)
check(
    "bullets and typed values",
    calls == [("add_task", {"title": "buy milk", "urgent": True, "count": 2})],
    str(calls),
)

calls, text = recover_tool_calls(
    'Sure.\n[used tools] get_datetime()\n[used tools] add_task(title="buy milk")\nDone.',
    TOOLS,
)
check("two calls in one reply", [name for name, _ in calls] == ["get_datetime", "add_task"], str(calls))
check("surrounding prose kept", "Sure." in text and "Done." in text, repr(text))

calls, text = recover_tool_calls("I would use open_desktop_app for that.", TOOLS)
check("prose that mentions a tool is ignored", calls == [] and "I would use" in text, repr(calls))

calls, _ = recover_tool_calls('delete_everything(path="/")', TOOLS)
check("tools that were not offered are ignored", calls == [], str(calls))

calls, _ = recover_tool_calls('open_desktop_app(app="whatsapp"', TOOLS)
check("unbalanced parentheses ignored", calls == [], str(calls))


# --------------------------------------------------------------------------- 2. provider
print("\n--- the provider adopts narrated calls")


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


def text_only_stream(text):
    return (
        chunk({"role": "assistant", "content": ""})
        + chunk({"content": text})
        + chunk({}, "stop")
        + "data: [DONE]\n\n"
    )


def provider_with(sse_text):
    settings = Settings(
        llm_provider="openrouter",
        openrouter_api_key="or-test-key",
        openrouter_model=MODEL,
        openrouter_max_tokens=400,
        openai_api_key="",
        anthropic_api_key="",
    )
    provider = OpenRouterProvider(settings)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=text_only_stream(sse_text).encode(),
            headers={"content-type": "text/event-stream"},
        )
    )
    provider._client = openai.AsyncOpenAI(
        api_key="or-test-key",
        base_url=provider.base_url,
        http_client=httpx.AsyncClient(transport=transport),
        max_retries=0,
    )
    return provider


narrated = '[used tools] open_desktop_app(app="whatsapp")\nWhatsApp\'s open.'
turn = asyncio.run(
    provider_with(narrated).stream_turn(
        messages=[{"role": "user", "content": "open whatsapp"}],
        system="s",
        tools=[
            {
                "name": "open_desktop_app",
                "description": "d",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
)
check(
    "narration became a real tool call",
    [c.name for c in turn.tool_calls] == ["open_desktop_app"],
    str(turn.tool_calls),
)
check("its arguments survived", turn.tool_calls[0].input == {"app": "whatsapp"}, str(turn.tool_calls[0].input))
check("visible text no longer shows the call", "[used tools]" not in turn.text, turn.text)
check("stop reason fixed", turn.stop_reason == "tool_calls", str(turn.stop_reason))
check(
    "history message carries the call",
    turn.assistant_message.get("tool_calls", [{}])[0].get("function", {}).get("name") == "open_desktop_app",
    str(turn.assistant_message)[:120],
)

plain = asyncio.run(
    provider_with("It's 12:21 pm here.").stream_turn(
        messages=[{"role": "user", "content": "time?"}], system="s", tools=None
    )
)
check("ordinary text is left alone", plain.tool_calls == [] and "12:21" in plain.text, plain.text)

# --------------------------------------------------------------------------- 3. agent guard
print("\n--- the agent refuses a false success")


class StubLLM:
    """Answers with a fixed script; records how each turn was asked."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def stream_turn(
        self, *, messages, system, tools=None, on_text=None, max_tokens=None, model=None, tool_choice=None
    ):
        self.calls.append({"system": system, "choice": tool_choice, "history": list(messages)})
        turn = self.turns.pop(0)
        if on_text is not None and turn.text:
            await on_text(turn.text)
        return turn

    def tool_result_messages(self, results):
        return [
            {"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]}
            for r in results
        ]

    def format_tools(self, schemas):
        return schemas


def run_agent(turns, user_text):
    init_db()
    settings = Settings(
        llm_provider="openai",
        openai_api_key="",
        max_tool_iterations=4,
        memory_extraction_enabled=False,
        apps_bridge_enabled=False,
    )
    stub = StubLLM(turns)
    events = []

    async def emit(payload):
        events.append(payload)

    async def confirm(*_args, **_kwargs):
        return True

    db = SessionLocal()
    try:
        conversation = Conversation(title="New conversation")
        db.add(conversation)
        db.commit()
        result = asyncio.run(
            Agent(settings, llm=stub).respond(
                db, conversation.id, user_text, emit=emit, confirm=confirm
            )
        )
        return stub, events, result
    finally:
        db.close()


claim_then_tool = [
    LLMTurn(
        text="Opened, boss.",
        stop_reason="stop",
        assistant_message={"role": "assistant", "content": "Opened, boss."},
    ),
    LLMTurn(
        text="",
        stop_reason="tool_calls",
        assistant_message={"role": "assistant", "content": None},
        tool_calls=[ToolCall(id="c1", name="get_datetime", input={}, raw_arguments="{}")],
    ),
    LLMTurn(
        text="It's open.",
        stop_reason="stop",
        assistant_message={"role": "assistant", "content": "It's open."},
    ),
]
stub, events, result = run_agent(claim_then_tool, "open whatsapp")
check("a claimed action triggers one corrective turn", len(stub.calls) == 3, str(len(stub.calls)))
check("the correction is sent", CORRECTION in stub.calls[1]["system"], stub.calls[1]["system"][-60:])
check(
    "the false claim is not fed back",
    stub.calls[1]["history"][-1]["role"] == "user",
    str(stub.calls[1]["history"][-1]),
)
check("the tool actually ran", [t["name"] for t in result["tools"]] == ["get_datetime"], str(result["tools"]))
check("the honest answer is kept", result["text"] == "It's open.", result["text"])
check("tool events reached the UI", any(e["type"] == "tool_call" for e in events))

claim_only = [
    LLMTurn(
        text="Opened, boss.",
        stop_reason="stop",
        assistant_message={"role": "assistant", "content": "Opened, boss."},
    ),
    LLMTurn(
        text="Sure — done.",
        stop_reason="stop",
        assistant_message={"role": "assistant", "content": "Sure — done."},
    ),
]
stub, events, result = run_agent(claim_only, "open whatsapp")
check("two attempts, then stop", len(stub.calls) == 2, str(len(stub.calls)))
check("false success is replaced", result["text"] == UNVERIFIED_REPLY, result["text"][:60])
check("the user is warned", any(e["type"] == "warning" for e in events))

question = [
    LLMTurn(
        text="I opened WhatsApp earlier.",
        stop_reason="stop",
        assistant_message={"role": "assistant", "content": "I opened WhatsApp earlier."},
    ),
]
stub, _events, result = run_agent(question, "what did you open earlier?")
check("a question does not trigger the correction", len(stub.calls) == 1, str(len(stub.calls)))
check("past-tense answers are left alone", "earlier" in result["text"], result["text"])
check("tool_choice is never forced", all(c["choice"] is None for c in stub.calls))

print("")
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("all tool-calling checks passed")

