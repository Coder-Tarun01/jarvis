from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MemoryCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    tags: str = Field(default="", max_length=200)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = ""
    when: str | None = None  # natural language due date, e.g. "tomorrow at 9"


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""


class ReminderCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    when: str = Field(min_length=1, max_length=100)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
