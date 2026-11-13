"""Tool primitives.

A tool is a plain object with a name, a JSON schema and a handler.
Handlers receive a ``ToolContext`` and the validated-ish arguments as kwargs;
they may be sync (DB work) or async (network work) — the registry handles both.

To add a tool: drop a new module into this package that exposes
``TOOLS = [Tool(...)]``. It is picked up on the next start, no wiring needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

Handler = Callable[..., Any]
Notifier = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class ToolContext:
    """Everything a handler is allowed to touch."""

    db: Session
    conversation_id: int | None = None
    notify: Notifier | None = None
    settings: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    async def push(self, payload: dict[str, Any]) -> None:
        """Send an unsolicited event to the browser (toast, notification, ...)."""
        if self.notify is not None:
            await self.notify(payload)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    requires_confirmation: bool = False
    confirmation_hint: str = ""

    def schema(self) -> dict[str, Any]:
        """Anthropic tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def __post_init__(self) -> None:
        if not self.description.endswith("."):
            self.description += "."
        if self.input_schema.get("type") != "object":  # pragma: no cover - guard rail
            raise ValueError(f"tool {self.name}: input_schema must be an object schema")
