"""Todo / task manager backed by the tasks table."""

from __future__ import annotations

from sqlalchemy import select

from ..core.errors import ToolError
from ..core.models import Task
from ..core.utils import parse_when, utcnow
from .base import Tool, ToolContext


def add_task(ctx: ToolContext, title: str, notes: str = "", due: str | None = None) -> dict:
    title = (title or "").strip()
    if not title:
        raise ToolError("a task needs a title")
    due_at = None
    if due:
        try:
            due_at = parse_when(due)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    task = Task(title=title[:300], notes=notes or "", due_at=due_at)
    ctx.db.add(task)
    ctx.db.commit()
    ctx.db.refresh(task)
    return {"ok": True, "task": task.to_dict()}


def list_tasks(ctx: ToolContext, status: str = "open", limit: int = 50) -> dict:
    status = (status or "open").lower()
    stmt = select(Task).order_by(Task.status.asc(), Task.id.desc()).limit(max(1, min(limit, 200)))
    if status in ("open", "done"):
        stmt = stmt.where(Task.status == status)
    tasks = list(ctx.db.scalars(stmt).all())
    return {
        "count": len(tasks),
        "tasks": [t.to_dict() for t in tasks],
    }


def complete_task(ctx: ToolContext, task_id: int) -> dict:
    task = ctx.db.get(Task, int(task_id))
    if task is None:
        raise ToolError(f"no task with id {task_id}")
    task.status = "done"
    task.completed_at = utcnow()
    ctx.db.commit()
    return {"ok": True, "task": task.to_dict()}


def reopen_task(ctx: ToolContext, task_id: int) -> dict:
    task = ctx.db.get(Task, int(task_id))
    if task is None:
        raise ToolError(f"no task with id {task_id}")
    task.status = "open"
    task.completed_at = None
    ctx.db.commit()
    return {"ok": True, "task": task.to_dict()}


def delete_task(ctx: ToolContext, task_id: int) -> dict:
    task = ctx.db.get(Task, int(task_id))
    if task is None:
        raise ToolError(f"no task with id {task_id}")
    snapshot = task.to_dict()
    ctx.db.delete(task)
    ctx.db.commit()
    return {"ok": True, "deleted": snapshot}


TOOLS = [
    Tool(
        name="add_task",
        description="Add an item to the user's todo list",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "What needs doing"},
                "notes": {"type": "string", "description": "Optional detail"},
                "due": {
                    "type": "string",
                    "description": "Optional due date: 'tomorrow at 9', 'in 2 hours', ISO timestamp",
                },
            },
            "required": ["title"],
        },
        handler=add_task,
    ),
    Tool(
        name="list_tasks",
        description="List todo items. status: open (default), done, or all",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "done", "all"], "default": "open"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
        },
        handler=list_tasks,
    ),
    Tool(
        name="complete_task",
        description="Mark a todo item as done by id",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "integer", "description": "Task id from list_tasks"}},
            "required": ["task_id"],
        },
        handler=complete_task,
    ),
    Tool(
        name="reopen_task",
        description="Move a completed todo item back to open",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
        handler=reopen_task,
    ),
    Tool(
        name="delete_task",
        description="Permanently delete a todo item",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
        handler=delete_task,
        requires_confirmation=False,
    ),
]
