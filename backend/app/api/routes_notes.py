"""Notes REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.models import Note
from ..core.schemas import NoteCreate
from ..core.security import require_auth

router = APIRouter(prefix="/api/notes", tags=["notes"], dependencies=[Depends(require_auth)])


@router.get("")
def list_notes(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Note).order_by(Note.updated_at.desc()).limit(limit)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = select(Note).where(
            or_(Note.title.ilike(like), Note.content.ilike(like))
        ).order_by(Note.updated_at.desc()).limit(limit)
    notes = list(db.scalars(stmt).all())
    return {"count": len(notes), "notes": [n.to_dict() for n in notes]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, db: Session = Depends(get_db)) -> dict:
    note = Note(title=payload.title.strip()[:200], content=payload.content or "")
    db.add(note)
    db.commit()
    db.refresh(note)
    return note.to_dict()


@router.get("/{note_id}")
def get_note(note_id: int, db: Session = Depends(get_db)) -> dict:
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return note.to_dict()


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, db: Session = Depends(get_db)) -> Response:
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    db.delete(note)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
