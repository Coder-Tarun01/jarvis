"""Long-term memory CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.schemas import MemoryCreate
from ..core.security import require_auth
from ..memory import store

router = APIRouter(
    prefix="/api/memories", tags=["memories"], dependencies=[Depends(require_auth)]
)


@router.get("")
def list_memories(
    q: str | None = Query(default=None, description="Optional relevance query"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    if q and q.strip():
        memories = store.search(db, q, top_k=limit)
    else:
        memories = store.list_memories(db, limit=limit)
    return {"count": len(memories), "memories": [m.to_dict() for m in memories]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_memory(payload: MemoryCreate, db: Session = Depends(get_db)) -> dict:
    memory = store.remember(db, payload.text, source="manual", tags=payload.tags or "")
    if memory is None:
        raise HTTPException(status_code=400, detail="memory is too short")
    return memory.to_dict()


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: int, db: Session = Depends(get_db)) -> Response:
    if not store.delete_memory(db, memory_id):
        raise HTTPException(status_code=404, detail="memory not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
