"""Todo / task REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.models import Task
from ..core.schemas import TaskCreate
from ..core.security import require_auth
from ..core.utils import parse_when, utcnow

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_auth)])


@router.get("")
def list_tasks(
    status_filter: str = Query(default="open", alias="status", pattern="^(open|done|all)$"),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Task).order_by(Task.status.asc(), Task.id.desc()).limit(300)
    if status_filter in ("open", "done"):
        stmt = stmt.where(Task.status == status_filter)
    tasks = list(db.scalars(stmt).all())
    return {"count": len(tasks), "tasks": [t.to_dict() for t in tasks]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> dict:
    due_at = None
    if payload.when:
        try:
            due_at = parse_when(payload.when)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    task = Task(title=payload.title.strip()[:300], notes=payload.notes or "", due_at=due_at)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task.to_dict()


@router.patch("/{task_id}/complete")
def complete_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    task.status = "done"
    task.completed_at = utcnow()
    db.commit()
    db.refresh(task)
    return task.to_dict()


@router.patch("/{task_id}/reopen")
def reopen_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    task.status = "open"
    task.completed_at = None
    db.commit()
    db.refresh(task)
    return task.to_dict()


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)) -> Response:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
