"""Desktop-app bridge tests.

Two layers:
  * offline: allowlist/denylist parsing, approval policy, error paths, and a
    simulated host watcher that exercises the request/response file protocol
    (including PowerShell's UTF-8 BOM on responses).
  * live: set APPS_LIVE=1 with the real bridge running on the host to check the
    actual round trip against /app/workspace.
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
import time

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_apps_test_")
os.environ["DATA_DIR"] = _TEST_DATA
os.environ["WORKSPACE_DIR"] = os.path.join(_TEST_DATA, "workspace")
os.environ["JARVIS_AUTH_TOKEN"] = "test-token"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = ""
os.environ["APPS_BRIDGE_ENABLED"] = "true"
os.environ["APPS_BRIDGE_TIMEOUT"] = "12"
os.environ["APPS_ALLOWLIST"] = (
    "notepad=notepad.exe;calculator=calc.exe|CalculatorApp;explorer=explorer.exe;"
    "antigravity=%LOCALAPPDATA%/Programs/Antigravity IDE/Antigravity IDE.exe|Antigravity IDE;"
    "settings=ms-settings:"
)
os.environ["APPS_DENYLIST"] = "explorer,winlogon,csrss,lsass,svchost,services,dwm,wininit,smss"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.errors import ToolError  # noqa: E402
from app.tools import ToolContext, load_tools  # noqa: E402
from app.tools.desktop_apps import BUS_DIRNAME, _process_name, _resolve_app  # noqa: E402
from app.tools.registry import needs_confirmation  # noqa: E402

settings = get_settings()
_loaded = load_tools()
tools = _loaded if isinstance(_loaded, dict) else {tool.name: tool for tool in _loaded}

failures = []


def check(label, condition, extra=""):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


def variant(**overrides):
    if hasattr(settings, "model_copy"):
        return settings.model_copy(update=overrides)
    return settings.copy(update=overrides)  # pragma: no cover - pydantic v1


def ctx_for(cfg=None):
    return ToolContext(db=None, settings=cfg or settings)


def call(tool_name, cfg=None, **kwargs):
    tool = tools[tool_name]
    return asyncio.run(tool.handler(ctx_for(cfg), **kwargs))


def expect_error(label, needle, tool_name, cfg=None, **kwargs):
    try:
        asyncio.run(tools[tool_name].handler(ctx_for(cfg), **kwargs))
    except ToolError as exc:
        check(label, needle.lower() in str(exc).lower(), f"({exc})")
    except Exception as exc:  # pragma: no cover - unexpected type
        check(label, False, f"(unexpected {type(exc).__name__}: {exc})")
    else:
        check(label, False, "(no error raised)")


# ------------------------------------------------------------------ registry
print("--- tool registration")
check("open_desktop_app registered", "open_desktop_app" in tools)
check("close_desktop_app registered", "close_desktop_app" in tools)
check("list_desktop_apps registered", "list_desktop_apps" in tools)

# Approval policy: only the irreversible tools ask (CONFIRM_TOOLS is authoritative).
policy = Settings(confirm_tools="run_command,close_desktop_app,whatsapp_send_message")
check("open runs without asking", needs_confirmation(tools["open_desktop_app"], policy) is False)
check("close asks first", needs_confirmation(tools["close_desktop_app"], policy) is True)
check("list is read-only", needs_confirmation(tools["list_desktop_apps"], policy) is False)
check(
    "'*' gates everything",
    needs_confirmation(tools["list_desktop_apps"], Settings(confirm_tools="*")) is True,
)
check(
    "empty list falls back to the tool flags",
    needs_confirmation(tools["open_desktop_app"], Settings(confirm_tools="")) is False
    and needs_confirmation(tools["close_desktop_app"], Settings(confirm_tools="")) is True,
)
check(
    "open description advertises aliases",
    "notepad" in tools["open_desktop_app"].description,
    tools["open_desktop_app"].description[-60:],
)

# ------------------------------------------------------------------ config
print("--- allowlist / denylist parsing")
allowed = settings.apps_allowed
check(
    "aliases parsed",
    set(allowed) == {"notepad", "calculator", "explorer", "antigravity", "settings"},
    str(sorted(allowed)),
)
check("target parsed", allowed["notepad"][0] == "notepad.exe")
check("process override parsed", allowed["calculator"][1] == "CalculatorApp")
check("denylist parsed", {"explorer", "winlogon", "csrss"} <= settings.apps_denied)
check("resolve alias (case insensitive)", (_resolve_app(settings, "NotePad") or ("",))[0] == "notepad")
check("resolve exe name", (_resolve_app(settings, "CALC.EXE") or ("",))[0] == "calculator")
check("resolve unknown app", _resolve_app(settings, "winword") is None)
check("resolve empty app", _resolve_app(settings, "  ") is None)

# --- spoken names must survive phrasing -------------------------------------
check(
    "resolve 'Google Antigravity'",
    (_resolve_app(settings, "Google Antigravity") or ("",))[0] == "antigravity",
)
check(
    "resolve 'antigravity IDE'",
    (_resolve_app(settings, "antigravity IDE") or ("",))[0] == "antigravity",
)
check(
    "resolve 'Antigravity-IDE.exe'",
    (_resolve_app(settings, "Antigravity-IDE.exe") or ("",))[0] == "antigravity",
)
check(
    "resolve 'Antigravity.IDE'",
    (_resolve_app(settings, "Antigravity.IDE") or ("",))[0] == "antigravity",
)
check(
    "resolve 'the Antigravity app'",
    (_resolve_app(settings, "the Antigravity app") or ("",))[0] == "antigravity",
)
check(
    "antigravity process name",
    _process_name(
        "%LOCALAPPDATA%/Programs/Antigravity IDE/Antigravity IDE.exe", "Antigravity IDE", "antigravity"
    )
    == "Antigravity IDE",
)
check(
    "process name derived from a spaced exe",
    _process_name("%LOCALAPPDATA%/Programs/Antigravity IDE/Antigravity IDE.exe", "", "antigravity")
    == "Antigravity IDE",
)
check(
    "resolve 'Settings' (URI target)",
    (_resolve_app(settings, "Settings") or ("",))[0] == "settings",
)

# ------------------------------------------------------------------ guards
print("--- refusals")
expect_error("unknown app on open", "not in the app allowlist", "open_desktop_app", app="winword")
expect_error("unknown app on close", "will not close", "close_desktop_app", app="winword")
expect_error("protected process is never closed", "protected", "close_desktop_app", app="explorer")
expect_error(
    "bridge can be disabled",
    "disabled",
    "open_desktop_app",
    cfg=variant(apps_bridge_enabled=False),
    app="notepad",
)
expect_error(
    "silent bridge times out with guidance",
    "desktop bridge did not answer",
    "open_desktop_app",
    cfg=variant(apps_bridge_timeout=1.2),
    app="notepad",
)

# ------------------------------------------------------- simulated host bridge
print("--- file protocol round trip (simulated host)")


def run_with_fake_bridge(label, expected_action, tool_name, **kwargs):
    req_dir = settings.workspace_path / BUS_DIRNAME / "req"
    res_dir = settings.workspace_path / BUS_DIRNAME / "res"
    req_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    seen = {}

    def worker():
        deadline = time.time() + 6
        while time.time() < deadline and not seen:
            for path in sorted(req_dir.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                seen.update(payload)
                response = {
                    "ok": True,
                    "id": payload.get("id"),
                    "action": payload.get("action"),
                    "app": payload.get("app"),
                    "pids": [4242],
                    "closed": 1,
                    "forced": bool(payload.get("force")),
                    "message": f"simulated {payload.get('action')} of {payload.get('app')}",
                    "apps": [{"process": "Notepad", "id": 4242, "title": "Untitled - Notepad"}],
                }
                # PowerShell's Set-Content writes a BOM; the backend must cope.
                (res_dir / path.name).write_text(json.dumps(response), encoding="utf-8-sig")
                path.unlink()
                return
            time.sleep(0.05)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    result = call(tool_name, **kwargs)
    thread.join(timeout=6)
    check(f"{label}: request reached the host", bool(seen), str(seen.get("action")))
    check(
        f"{label}: action is {expected_action}",
        seen.get("action") == expected_action,
        str(seen.get("action")),
    )
    check(
        f"{label}: BOM response parsed",
        isinstance(result, dict) and result.get("ok") is True,
        str(result)[:90],
    )
    leftovers = [p.name for p in req_dir.glob("*.json")] + [p.name for p in res_dir.glob("*.json")]
    check(f"{label}: queue cleaned up", not leftovers, str(leftovers))
    return seen, result


seen, result = run_with_fake_bridge("open", "open", "open_desktop_app", app="notepad")
check("open: alias normalised", seen.get("app") == "notepad", str(seen.get("app")))
check("open: no args by default", seen.get("args") == [], str(seen.get("args")))
check("open: result exposes pids", result.get("pids") == [4242], str(result.get("pids")))
check(
    "open: bridge message passed through",
    "notepad" in str(result.get("message", "")).lower(),
    str(result.get("message")),
)

seen, _ = run_with_fake_bridge(
    "open-with-args", "open", "open_desktop_app", app="notepad", arguments=["C:\\temp\\note.txt"]
)
check("open: arguments forwarded", seen.get("args") == ["C:\\temp\\note.txt"], str(seen.get("args")))

seen, result = run_with_fake_bridge("close-force", "close", "close_desktop_app", app="notepad", force=True)
check("close: force forwarded", seen.get("force") is True, str(seen.get("force")))
check("close: process resolved", result.get("process") == "notepad", str(result.get("process")))
check("close: reports count", result.get("closed") == 1, str(result.get("closed")))

seen, result = run_with_fake_bridge("list", "list", "list_desktop_apps")
check("list: reports windows", result.get("count") == 1, str(result.get("count")))
check(
    "list: flags allowlisted windows",
    result.get("windows", [{}])[0].get("allowlisted") is True,
    str(result.get("windows")),
)

# ------------------------------------------------------------------ live bridge
if os.environ.get("APPS_LIVE") == "1":
    print("--- live bridge (host)")
    live_cfg = variant(workspace_dir="/app/workspace", apps_bridge_timeout=6.0)
    try:
        live = call("list_desktop_apps", cfg=live_cfg)
    except ToolError as exc:
        check("live bridge answers", False, f"({exc})")
    else:
        check("live bridge answers", live.get("ok") is True, f"({live.get('count')} windows)")
else:
    print("[skip] live bridge check (set APPS_LIVE=1 with host/app-bridge.ps1 running)")

print()
if failures:
    print(f"FAILED {len(failures)} check(s):")
    for name in failures:
        print("  -", name)
    sys.exit(1)
print("all desktop-app bridge checks passed")
