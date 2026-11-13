"""Auto-loading tool registry.

Every module in ``app/tools`` that exposes a ``TOOLS`` list is imported at boot.
Broken plugins are logged and skipped — one bad tool never takes JARVIS down.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from ..core.utils import result_to_text
from .base import Tool, ToolContext

log = get_logger("tools")

_SKIP = {"base", "registry"}
_registry: dict[str, Tool] | None = None


def load_tools(force: bool = False) -> dict[str, Tool]:
    global _registry
    if _registry is not None and not force:
        return _registry

    found: dict[str, Tool] = {}
    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        name = module_info.name
        if name in _SKIP or name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__package__}.{name}")
        except Exception as exc:  # noqa: BLE001
            log.exception("tool module '%s' failed to import: %s", name, exc)
            continue
        module_tools = getattr(module, "TOOLS", None) or []
        for tool in module_tools:
            if not isinstance(tool, Tool):  # pragma: no cover - guard rail
                log.warning("ignoring non-Tool export in %s: %r", name, tool)
                continue
            if tool.name in found:
                log.warning("duplicate tool name '%s' in %s (keeping the first)", tool.name, name)
                continue
            found[tool.name] = tool

    _registry = found
    log.info("loaded %d tools: %s", len(found), ", ".join(sorted(found)) or "-")
    return found


def get_tool(name: str) -> Tool | None:
    return load_tools().get(name)


def needs_confirmation(tool: Tool, settings: Settings | None = None) -> bool:
    """Does this tool have to ask before it acts?

    ``CONFIRM_TOOLS`` is authoritative when it is set, so the policy lives in one
    line of ``.env`` instead of being scattered across tool definitions:

      * ``run_command,close_desktop_app`` → only those ask
      * ``*``                            → everything asks (paranoid mode)
      * empty                            → fall back to each tool's own flag
    """
    settings = settings or get_settings()
    configured = settings.confirm_tool_set
    if not configured:
        return tool.requires_confirmation
    if "*" in configured or "all" in configured:
        return True
    return tool.name.strip().lower() in configured


def tool_schemas() -> list[dict[str, Any]]:
    return [tool.schema() for tool in load_tools().values()]


def tool_summaries() -> list[dict[str, Any]]:
    """What the UI shows in the tool drawer."""
    settings = get_settings()
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "requires_confirmation": needs_confirmation(tool, settings),
        }
        for tool in load_tools().values()
    ]


async def execute_tool(name: str, arguments: dict[str, Any] | None, ctx: ToolContext) -> str:
    """Run a tool and always return a string suitable for the model."""
    tool = get_tool(name)
    if tool is None:
        raise ToolError(f"unknown tool '{name}'")

    kwargs = dict(arguments or {})
    try:
        result = tool.handler(ctx, **kwargs)
        if inspect.isawaitable(result):
            result = await result
    except ToolError:
        raise
    except TypeError as exc:
        raise ToolError(f"{name}: bad arguments ({exc})") from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("tool '%s' crashed", name)
        raise ToolError(f"{name} failed: {exc}") from exc

    return result_to_text(result)
