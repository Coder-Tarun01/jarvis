"""Reminder REST endpoints (the scheduler fires them over the WebSocket)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.models import Reminder
from ..core.schemas import ReminderCreate
from ..core.security import require_auth
from ..core.utils import human_time, parse_when, utcnow

router = APIRouter(
    prefix="/api/reminders", tags=["reminders"], dependencies=[Depends(require_auth)]
)


@router.get("")
def list_reminders(
    include_fired: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Reminder).order_by(Reminder.due_at.asc()).limit(200)
    if not include_fired:
        stmt = stmt.where(Reminder.fired.is_(False))
    reminders = list(db.scalars(stmt).all())
    return {"count": len(reminders), "reminders": [r.to_dict() for r in reminders]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reminder(payload: ReminderCreate, db: Session = Depends(get_db)) -> dict:
    try:
        due_at = parse_when(payload.when)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if due_at <= utcnow():
        raise HTTPException(status_code=400, detail="that time is in the past")
    reminder = Reminder(text=payload.text.strip()[:500], kind="reminder", due_at=due_at)
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    data = reminder.to_dict()
    data["due_human"] = human_time(reminder.due_at)
    return data


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(reminder_id: int, db: Session = Depends(get_db)) -> Response:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="reminder not found")
    db.delete(reminder)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
