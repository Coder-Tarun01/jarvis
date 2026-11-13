"""Notes: quick capture plus search."""

from __future__ import annotations

from sqlalchemy import or_, select

from ..core.errors import ToolError
from ..core.models import Note
from .base import Tool, ToolContext


def create_note(ctx: ToolContext, title: str, content: str = "") -> dict:
    title = (title or "").strip()
    if not title:
        raise ToolError("a note needs a title")
    note = Note(title=title[:200], content=content or "")
    ctx.db.add(note)
    ctx.db.commit()
    ctx.db.refresh(note)
    return {"ok": True, "note": note.to_dict()}


def search_notes(ctx: ToolContext, query: str, limit: int = 5) -> dict:
    query = (query or "").strip()
    if not query:
        raise ToolError("a search needs a query")
    pattern = f"%{query}%"
    stmt = (
        select(Note)
        .where(or_(Note.title.ilike(pattern), Note.content.ilike(pattern)))
        .order_by(Note.updated_at.desc())
        .limit(max(1, min(limit, 25)))
    )
    notes = list(ctx.db.scalars(stmt).all())
    return {
        "count": len(notes),
        "notes": [
            {
                "id": n.id,
                "title": n.title,
                "excerpt": (n.content or "")[:300],
                "updated_at": n.to_dict()["updated_at"],
            }
            for n in notes
        ],
    }


def read_note(ctx: ToolContext, note_id: int) -> dict:
    note = ctx.db.get(Note, int(note_id))
    if note is None:
        raise ToolError(f"no note with id {note_id}")
    return {"note": note.to_dict()}


def list_notes(ctx: ToolContext, limit: int = 20) -> dict:
    stmt = select(Note).order_by(Note.updated_at.desc()).limit(max(1, min(limit, 100)))
    notes = list(ctx.db.scalars(stmt).all())
    return {
        "count": len(notes),
        "notes": [{"id": n.id, "title": n.title, "updated_at": n.to_dict()["updated_at"]} for n in notes],
    }


def append_to_note(ctx: ToolContext, note_id: int, content: str) -> dict:
    note = ctx.db.get(Note, int(note_id))
    if note is None:
        raise ToolError(f"no note with id {note_id}")
    note.content = (note.content or "") + ("\n" if note.content else "") + (content or "")
    ctx.db.commit()
    ctx.db.refresh(note)
    return {"ok": True, "note": note.to_dict()}


TOOLS = [
    Tool(
        name="create_note",
        description="Save a note (title + body) to the local notes store",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string", "description": "Note body, markdown is fine"},
            },
            "required": ["title"],
        },
        handler=create_note,
    ),
    Tool(
        name="search_notes",
        description="Full-text search across saved notes",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5},
            },
            "required": ["query"],
        },
        handler=search_notes,
    ),
    Tool(
        name="read_note",
        description="Read one note in full by id",
        input_schema={
            "type": "object",
            "properties": {"note_id": {"type": "integer"}},
            "required": ["note_id"],
        },
        handler=read_note,
    ),
    Tool(
        name="list_notes",
        description="List recent notes",
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
        },
        handler=list_notes,
    ),
    Tool(
        name="append_to_note",
        description="Add more text to the end of an existing note",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "integer"},
                "content": {"type": "string"},
            },
            "required": ["note_id", "content"],
        },
        handler=append_to_note,
    ),
]
