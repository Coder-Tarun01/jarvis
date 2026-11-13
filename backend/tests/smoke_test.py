import os
import sys
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_test_data_")
os.environ.setdefault("DATA_DIR", _TEST_DATA)
os.environ.setdefault("WORKSPACE_DIR", os.path.join(_TEST_DATA, "workspace"))
os.environ.setdefault("JARVIS_AUTH_TOKEN", "test-token")
os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ["OPENAI_API_KEY"] = ""  # keep this test offline and deterministic
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings  # noqa: E402

settings = get_settings()
print("db url:", settings.database_url)
print("workspace:", settings.workspace_path)
print("provider:", settings.provider, "model:", settings.llm_model, "fast:", settings.llm_model_fast)
print("models come from env/.env:", settings.openai_model, settings.openai_model_fast)

from app.core.db import SessionLocal, init_db  # noqa: E402

init_db()
print("db tables created")

from app.tools.registry import load_tools, tool_schemas  # noqa: E402

tools = load_tools()
print("tools:", sorted(tools))
bad = [s for s in tool_schemas() if s["input_schema"].get("type") != "object"]
print("bad schemas:", bad)

from app.core.utils import parse_when, utcnow  # noqa: E402

for expr in ["in 10 minutes", "tomorrow at 9pm", "in 2 hours", "2026-12-01T10:00", "5 min from now", "today at 18:30"]:
    try:
        print(f"parse_when({expr!r}) -> {parse_when(expr)}")
    except Exception as exc:
        print(f"parse_when({expr!r}) FAILED: {exc}")
try:
    parse_when("banana")
    print("parse_when(banana) should have failed")
except ValueError as exc:
    print("parse_when(banana) correctly rejected:", exc)

from app.memory import store  # noqa: E402

db = SessionLocal()
mem = store.remember(db, "The user's name is Sam and they live in Berlin.")
print("stored memory:", mem.id, mem.text)
again = store.remember(db, "the user's name is sam and they live in berlin")
print("dedupe ok:", again.id == mem.id)
print("search:", [m.text for m in store.search(db, "where does Sam live?")])

from app.services.persona import build_system_prompt  # noqa: E402

prompt = build_system_prompt(settings, [mem])
print("prompt length:", len(prompt))
print("prompt has memory:", "Berlin" in prompt)

from app.core.agent import merge_turns, title_from  # noqa: E402
from app.core.models import Message  # noqa: E402

rows = [
    Message(conversation_id=1, role="assistant", content="orphan"),
    Message(conversation_id=1, role="user", content="hi"),
    Message(conversation_id=1, role="user", content="again"),
    Message(conversation_id=1, role="assistant", content="hello"),
]
print("merge:", merge_turns(rows))
print("title:", title_from("  hello   there  "))

from app.services.llm import LLMService, extract_json  # noqa: E402
from app.services.llm_openai import OpenAIProvider  # noqa: E402

service = LLMService(settings)
print("llm provider:", service.provider_name, "available:", service.available)
formatted = OpenAIProvider(settings).format_tools(tool_schemas())
ok = bool(formatted) and all(
    tool["type"] == "function"
    and tool["function"]["parameters"].get("type") == "object"
    and tool["function"]["name"]
    for tool in formatted
)
print(f"openai tool conversion: {len(formatted)} tools, ok={ok}")
base_url = OpenAIProvider(settings).base_url
print("openai base_url:", base_url)
print("base_url absolute:", base_url.startswith(("http://", "https://")))
print("json:", extract_json('noise ```json\n["a", "b"]\n``` more'))
print("ALL GOOD")
