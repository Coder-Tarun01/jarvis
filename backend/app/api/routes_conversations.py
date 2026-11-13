"""Conversation history: list, search, open, rename, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.models import Conversation, Message
from ..core.schemas import ConversationCreate, ConversationUpdate
from ..core.security import require_auth

router = APIRouter(
    prefix="/api/conversations",
    tags=["conversations"],
    dependencies=[Depends(require_auth)],
)


def _summary(db: Session, conversation: Conversation) -> dict:
    data = conversation.to_dict()
    data["message_count"] = (
        db.scalar(
            select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
        )
        or 0
    )
    last = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(1)
    ).first()
    data["preview"] = (last.content or "")[:120] if last else ""
    return data


@router.get("")
def list_conversations(
    q: str | None = Query(default=None, description="Search titles and message bodies"),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(200)
    if q and q.strip():
        like = f"%{q.strip()}%"
        matching = select(Message.conversation_id).where(Message.content.ilike(like))
        stmt = stmt.where(or_(Conversation.title.ilike(like), Conversation.id.in_(matching)))
    return [_summary(db, conversation) for conversation in db.scalars(stmt).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)) -> dict:
    conversation = Conversation(title=(payload.title or "New conversation")[:200])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation.to_dict()


@router.get("/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation.to_dict(include_messages=True)


@router.patch("/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conversation.title = payload.title.strip()[:200]
    db.commit()
    db.refresh(conversation)
    return conversation.to_dict()


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> Response:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
