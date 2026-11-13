"""Desktop application control (open / close / list) through a host bridge.

The backend runs inside a Linux container, so it cannot touch the Windows
desktop. Instead the tool writes a request into the bind-mounted workspace and a
small PowerShell watcher on the host (``host/app-bridge.ps1``) performs the
action and writes back a response file.

Security posture:
  * only aliases from ``APPS_ALLOWLIST`` can be launched or closed
  * ``APPS_DENYLIST`` processes are never closed (shell, session, services)
  * opening and closing both pass through the normal approval gate
  * the queue lives in the sandboxed workspace, so nothing else is reachable
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from .base import Tool, ToolContext

log = get_logger("tools.desktop_apps")

BUS_DIRNAME = ".appbridge"
POLL_SECONDS = 0.12
# Spoken names often carry the vendor: "Google Antigravity" -> "antigravity".
VENDOR_PREFIXES = ("google", "microsoft", "ms", "the")
# ...and filler words: "the Antigravity app" -> "antigravity".
FILLER_WORDS = ("the", "app", "apps", "application", "desktop", "program", "ide")


def _settings_of(ctx: ToolContext) -> Settings:
    return ctx.settings or get_settings()


def _bus_paths(settings: Settings) -> tuple[Path, Path]:
    root = settings.workspace_path / BUS_DIRNAME
    return root / "req", root / "res"


def _name_key(text: str) -> str:
    """Lowercase, drop punctuation/extensions and collapse spaces."""
    value = (text or "").strip().lower()
    for char in ("_", "-", ".", ":", "®", "™", "\\", "/"):
        value = value.replace(char, " ")
    value = " ".join(value.split())
    if value.endswith(" exe"):
        value = value[: -len(" exe")].strip()
    return value


def _keys_for(text: str) -> set[str]:
    """All the ways a human might say this name."""
    key = _name_key(text)
    if not key:
        return set()
    keys = {key, key.replace(" ", "")}
    parts = key.split(" ")
    if len(parts) > 1 and parts[0] in VENDOR_PREFIXES:
        rest = " ".join(parts[1:])
        keys.add(rest)
        keys.add(rest.replace(" ", ""))
    trimmed = [word for word in parts if word not in FILLER_WORDS]
    if trimmed and trimmed != parts:
        variant = " ".join(trimmed)
        keys.add(variant)
        keys.add(variant.replace(" ", ""))
    return {item for item in keys if item}


def _resolve_app(settings: Settings, name: str) -> tuple[str, str, str] | None:
    """Map a spoken name to (alias, target, process-name)."""
    wanted = _keys_for(name)
    if not wanted:
        return None

    for alias, (target, process) in settings.apps_allowed.items():
        leaf = target.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        candidates = _keys_for(alias) | _keys_for(leaf) | _keys_for(process)
        if wanted & candidates:
            return alias, target, process
    return None


def _process_name(target: str, process: str, alias: str) -> str:
    if process:
        return process
    stem = target.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return stem or alias


def _alias_hint(settings: Settings) -> str:
    return ", ".join(sorted(settings.apps_allowed)) or "(allowlist is empty)"


async def _bridge_call(
    settings: Settings,
    action: str,
    *,
    app: str = "",
    arguments: list[str] | None = None,
    force: bool = False,
    uri: str = "",
    press_enter: bool = False,
    delay_ms: int = 0,
    window_title: str = "",
    window_process: str = "",
    timeout: float | None = None,
) -> dict:
    """Drop a request in the queue and wait for the host to answer it."""
    if not settings.apps_bridge_enabled:
        raise ToolError(
            "desktop app control is disabled. Set APPS_BRIDGE_ENABLED=true in .env and restart."
        )

    req_dir, res_dir = _bus_paths(settings)
    try:
        req_dir.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolError(f"workspace is not writable for the app bridge: {exc}") from exc

    request_id = uuid.uuid4().hex
    request_file = req_dir / f"{request_id}.json"
    response_file = res_dir / f"{request_id}.json"

    payload = {
        "id": request_id,
        "action": action,
        "app": app,
        "args": list(arguments or []),
        "force": bool(force),
        "uri": uri,
        "press_enter": bool(press_enter),
        "delay_ms": int(delay_ms or 0),
        "window_title": window_title,
        "window_process": window_process,
        "requested_at": time.time(),
    }

    deadline = time.monotonic() + float(timeout or settings.apps_bridge_timeout)
    try:
        request_file.write_text(json.dumps(payload), encoding="utf-8")
        while time.monotonic() < deadline:
            if response_file.exists():
                try:
                    # PowerShell's Set-Content writes a UTF-8 BOM.
                    response = json.loads(response_file.read_text(encoding="utf-8-sig"))
                    return response if isinstance(response, dict) else {}
                except (json.JSONDecodeError, OSError):
                    pass  # still being written
            await asyncio.sleep(POLL_SECONDS)
    finally:
        for path in (request_file, response_file):
            try:
                path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover
                pass

    raise ToolError(
        "the desktop bridge did not answer in time. Start it on the host with "
        "host\\start-bridge.cmd (keep the window open) and try again."
    )


async def open_desktop_app(
    ctx: ToolContext,
    app: str,
    arguments: list[str] | None = None,
) -> dict:
    settings = _settings_of(ctx)
    resolved = _resolve_app(settings, app)
    if resolved is None:
        raise ToolError(
            f"'{app}' is not in the app allowlist. Available: {_alias_hint(settings)}. "
            "Add it to APPS_ALLOWLIST in .env to make it available."
        )
    alias, target, process = resolved

    result = await _bridge_call(settings, "open", app=alias, arguments=arguments)
    if not result.get("ok"):
        raise ToolError(str(result.get("message") or "the bridge could not launch it"))

    log.info("opened %s (target=%s, pids=%s)", alias, target, result.get("pids"))
    return {
        "ok": True,
        "app": alias,
        "target": target,
        "pids": result.get("pids") or [],
        "message": result.get("message") or f"launched {alias}",
    }


async def close_desktop_app(ctx: ToolContext, app: str, force: bool = False) -> dict:
    settings = _settings_of(ctx)
    resolved = _resolve_app(settings, app)
    if resolved is None:
        raise ToolError(
            f"'{app}' is not in the app allowlist, so I will not close it. "
            f"Available: {_alias_hint(settings)}."
        )
    alias, target, process = resolved
    process_name = _process_name(target, process, alias)

    if process_name.lower() in settings.apps_denied:
        raise ToolError(
            f"'{process_name}' is protected (APPS_DENYLIST) and will not be closed."
        )

    result = await _bridge_call(settings, "close", app=alias, force=force)
    if not result.get("ok"):
        raise ToolError(str(result.get("message") or f"the bridge could not close {alias}"))

    log.info("close %s -> %s", alias, result.get("message"))
    return {
        "ok": True,
        "app": alias,
        "process": process_name,
        "closed": result.get("closed", 0),
        "forced": bool(result.get("forced", False)),
        "message": result.get("message") or f"closed {alias}",
    }


async def list_desktop_apps(ctx: ToolContext) -> dict:
    settings = _settings_of(ctx)
    result = await _bridge_call(settings, "list", timeout=min(6.0, settings.apps_bridge_timeout))
    if not result.get("ok"):
        raise ToolError(str(result.get("message") or "the bridge could not list windows"))

    windows = result.get("apps") or []
    allowed = settings.apps_allowed
    for window in windows:
        name = str(window.get("process") or "").lower()
        window["allowlisted"] = any(
            alias == name or _process_name(target, process, alias).lower() == name
            for alias, (target, process) in allowed.items()
        )
    return {
        "ok": True,
        "count": len(windows),
        "windows": windows,
        "message": f"{len(windows)} window(s) open",
    }


TOOLS = [
    Tool(
        name="open_desktop_app",
        description=(
            "Launch a desktop application on the user's Windows machine. "
            "Use a short app name such as one of: " + _alias_hint(get_settings())
        ),
        input_schema={
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "App alias, e.g. 'notepad', 'chrome', 'code', 'settings'",
                },
                "arguments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional command-line arguments / file to open",
                },
            },
            "required": ["app"],
        },
        handler=open_desktop_app,
        requires_confirmation=get_settings().apps_require_confirmation,
        confirmation_hint="This launches an application on your desktop.",
    ),
    Tool(
        name="close_desktop_app",
        description=(
            "Close a running desktop application by alias: asks it to quit first, then "
            "terminates whatever is left. May discard unsaved work"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App alias, e.g. 'notepad', 'chrome'"},
                "force": {
                    "type": "boolean",
                    "description": "Force-quit if the app ignores the polite close request",
                    "default": False,
                },
            },
            "required": ["app"],
        },
        handler=close_desktop_app,
        requires_confirmation=True,
        confirmation_hint="This closes a running application and may discard unsaved work.",
    ),
    Tool(
        name="list_desktop_apps",
        description="List the windows currently open on the user's desktop",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=list_desktop_apps,
    ),
]
