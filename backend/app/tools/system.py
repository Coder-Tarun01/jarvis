"""System actions: open a URL in the user's browser, run a whitelisted command.

Both are external-effect actions, so both are gated behind UI confirmation.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from urllib.parse import urlparse

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.utils import truncate
from .base import Tool, ToolContext

_FORBIDDEN = re.compile(r"[;&|><`$\n\r]")


def open_url(ctx: ToolContext, url: str) -> dict:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ToolError("only absolute http(s) URLs can be opened")
    # The browser performs the actual navigation; the server stays headless.
    return {
        "ok": True,
        "opened": url,
        "client_action": {"action": "open_url", "url": url},
    }


def run_command(ctx: ToolContext, command: str) -> dict:
    settings: Settings = ctx.settings or get_settings()
    command = " ".join((command or "").split())
    if not command:
        raise ToolError("empty command")

    prefixes = settings.allowed_command_list
    if not prefixes:
        raise ToolError("the command whitelist is empty — set ALLOWED_COMMANDS in .env")

    lowered = command.lower()
    if not any(lowered == prefix or lowered.startswith(prefix + " ") for prefix in prefixes):
        raise ToolError(
            "that command is not whitelisted. Allowed prefixes: " + ", ".join(prefixes)
        )
    if _FORBIDDEN.search(command):
        raise ToolError("shell metacharacters (; | & > < ` $) are not allowed in commands")

    argv = shlex.split(command)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(settings.workspace_path),
            capture_output=True,
            text=True,
            timeout=float(settings.command_timeout),
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"'{argv[0]}' is not installed on this machine") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"command timed out after {settings.command_timeout}s") from exc

    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": truncate(completed.stdout or "", 4000),
        "stderr": truncate(completed.stderr or "", 2000),
    }


TOOLS = [
    Tool(
        name="open_url",
        description="Open a web page in the user's browser",
        input_schema={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Absolute http(s) URL"}},
            "required": ["url"],
        },
        handler=open_url,
        requires_confirmation=False,
    ),
    Tool(
        name="run_command",
        description=(
            "Run a shell command from the whitelist (ALLOWED_COMMANDS) inside the workspace "
            "folder. External effect — needs confirmation"
        ),
        input_schema={
            "type": "object",
            "properties": {"command": {"type": "string", "description": "e.g. 'git status'"}},
            "required": ["command"],
        },
        handler=run_command,
        requires_confirmation=True,
        confirmation_hint="This runs a command on your machine.",
    ),
]
