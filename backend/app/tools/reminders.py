"""Reminders and timers. The scheduler polls the DB and pushes browser notifications."""

from __future__ import annotations

from sqlalchemy import select

from ..core.errors import ToolError
from ..core.models import Reminder
from ..core.utils import human_time, iso, parse_when, utcnow
from .base import Tool, ToolContext


def _create(ctx: ToolContext, text: str, when: str, kind: str) -> Reminder:
    text = (text or "").strip()
    if not text:
        raise ToolError("tell me what to remind you about")
    try:
        due_at = parse_when(when)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if due_at <= utcnow():
        raise ToolError("that time is already in the past — pick a future time")

    reminder = Reminder(text=text[:500], kind=kind, due_at=due_at)
    ctx.db.add(reminder)
    ctx.db.commit()
    ctx.db.refresh(reminder)
    return reminder


async def set_reminder(ctx: ToolContext, text: str, when: str) -> dict:
    reminder = _create(ctx, text, when, "reminder")
    payload = {
        "type": "reminder_scheduled",
        "id": reminder.id,
        "text": reminder.text,
        "kind": reminder.kind,
        "due_at": iso(reminder.due_at),
        "due_human": human_time(reminder.due_at),
    }
    await ctx.push(payload)
    return {"ok": True, "reminder": reminder.to_dict(), "due": human_time(reminder.due_at)}


async def set_timer(ctx: ToolContext, duration: str, label: str = "Timer") -> dict:
    reminder = _create(ctx, label or "Timer", duration, "timer")
    await ctx.push(
        {
            "type": "reminder_scheduled",
            "id": reminder.id,
            "text": reminder.text,
            "kind": reminder.kind,
            "due_at": iso(reminder.due_at),
            "due_human": human_time(reminder.due_at),
        }
    )
    return {"ok": True, "timer": reminder.to_dict(), "fires_at": human_time(reminder.due_at)}


def list_reminders(ctx: ToolContext, include_fired: bool = False, limit: int = 20) -> dict:
    stmt = select(Reminder).order_by(Reminder.due_at.asc()).limit(max(1, min(limit, 100)))
    if not include_fired:
        stmt = stmt.where(Reminder.fired.is_(False))
    reminders = list(ctx.db.scalars(stmt).all())
    return {
        "count": len(reminders),
        "now": human_time(utcnow()),
        "reminders": [r.to_dict() for r in reminders],
    }


def cancel_reminder(ctx: ToolContext, reminder_id: int) -> dict:
    reminder = ctx.db.get(Reminder, int(reminder_id))
    if reminder is None:
        raise ToolError(f"no reminder with id {reminder_id}")
    snapshot = reminder.to_dict()
    ctx.db.delete(reminder)
    ctx.db.commit()
    return {"ok": True, "cancelled": snapshot}


TOOLS = [
    Tool(
        name="set_reminder",
        description=(
            "Create a reminder that pops up in the browser at a future time. "
            "Use natural language for 'when', e.g. 'in 20 minutes', 'tomorrow at 9:30'"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to remind the user about"},
                "when": {"type": "string", "description": "When it should fire"},
            },
            "required": ["text", "when"],
        },
        handler=set_reminder,
    ),
    Tool(
        name="set_timer",
        description="Start a countdown timer, e.g. duration='10 minutes'",
        input_schema={
            "type": "object",
            "properties": {
                "duration": {"type": "string", "description": "e.g. '90 seconds', '10 minutes'"},
                "label": {"type": "string", "description": "What the timer is for"},
            },
            "required": ["duration"],
        },
        handler=set_timer,
    ),
    Tool(
        name="list_reminders",
        description="List pending reminders and timers",
        input_schema={
            "type": "object",
            "properties": {
                "include_fired": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
        },
        handler=list_reminders,
    ),
    Tool(
        name="cancel_reminder",
        description="Cancel a pending reminder or timer by id",
        input_schema={
            "type": "object",
            "properties": {"reminder_id": {"type": "integer"}},
            "required": ["reminder_id"],
        },
        handler=cancel_reminder,
    ),
]
