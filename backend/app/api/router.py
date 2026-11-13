"""All HTTP + WebSocket routes in one place."""

from fastapi import APIRouter

from . import (
    routes_chat,
    routes_conversations,
    routes_memories,
    routes_notes,
    routes_reminders,
    routes_speech,
    routes_system,
    routes_tasks,
)

api_router = APIRouter()
api_router.include_router(routes_system.router)
api_router.include_router(routes_conversations.router)
api_router.include_router(routes_memories.router)
api_router.include_router(routes_tasks.router)
api_router.include_router(routes_notes.router)
api_router.include_router(routes_reminders.router)
api_router.include_router(routes_speech.router)
api_router.include_router(routes_chat.router)

__all__ = ["api_router"]
