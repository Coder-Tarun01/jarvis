"""WebSocket chat: one socket per browser tab, one turn at a time.

Client -> server
  {"type": "user_message", "text": "...", "conversation_id": 3|null}
  {"type": "confirm", "id": "<tool_use_id>", "approved": true|false}
  {"type": "stop"}
  {"type": "ping"}

Server -> client
  hello | state | token | tool_call | tool_result | confirmation_request |
  confirmation_timeout | client_action | assistant_done | memory_added |
  reminder_scheduled | reminder | conversation_created | warning | error | stopped | pong
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.agent import Agent
from ..core.config import get_settings
from ..core.db import SessionLocal
from ..core.errors import LLMNotConfigured, ToolError
from ..core.logging import get_logger
from ..core.models import Conversation
from ..core.security import websocket_authorized
from ..services.hub import hub

router = APIRouter()
log = get_logger("api.chat")

#: Strong references to detached tasks (asyncio only keeps weak refs).
_background_tasks: set[asyncio.Task[Any]] = set()


def _spawn(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _extract_memories(
    websocket: WebSocket,
    agent: Agent,
    user_text: str,
    assistant_text: str,
) -> None:
    """Memory extraction runs after the turn is finished, in its own session."""
    db = SessionLocal()
    try:
        facts = await agent.memorize(db, user_text, assistant_text)
        if facts:
            await hub.send(websocket, {"type": "memory_added", "facts": facts})
    except Exception:  # noqa: BLE001 - never surface background failures
        log.exception("background memory extraction failed")
    finally:
        db.close()


@router.websocket("/ws")
async def chat_socket(websocket: WebSocket) -> None:
    settings = get_settings()
    if not websocket_authorized(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await hub.register(websocket)

    agent = Agent(settings)
    pending: dict[str, asyncio.Future[bool]] = {}
    run_task: asyncio.Task[Any] | None = None

    async def emit(payload: dict[str, Any]) -> None:
        await hub.send(websocket, payload)

    async def confirm(call_id: str, name: str, arguments: dict[str, Any], hint: str) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        pending[call_id] = future
        await emit(
            {
                "type": "confirmation_request",
                "id": call_id,
                "name": name,
                "input": arguments,
                "hint": hint,
                "timeout": settings.confirmation_timeout,
            }
        )
        try:
            return await asyncio.wait_for(future, timeout=settings.confirmation_timeout)
        except asyncio.TimeoutError:
            await emit({"type": "confirmation_timeout", "id": call_id})
            return False
        finally:
            pending.pop(call_id, None)

    async def run_turn(message: dict[str, Any]) -> None:
        text = str(message.get("text") or "").strip()
        if not text:
            await emit({"type": "error", "message": "empty message"})
            return

        db = SessionLocal()
        try:
            conversation = None
            raw_id = message.get("conversation_id")
            if raw_id:
                try:
                    conversation = db.get(Conversation, int(raw_id))
                except (TypeError, ValueError):
                    conversation = None
            if conversation is None:
                conversation = Conversation(title="New conversation")
                db.add(conversation)
                db.commit()
                db.refresh(conversation)
                await emit({"type": "conversation_created", "conversation": conversation.to_dict()})

            result = await agent.respond(db, conversation.id, text, emit=emit, confirm=confirm)
            await emit(
                {
                    "type": "assistant_done",
                    "conversation_id": result["conversation_id"],
                    "title": result["title"],
                    "text": result["text"],
                    "tools": result["tools"],
                    "memories_used": result["memories_used"],
                }
            )
            await emit({"type": "state", "state": "idle"})

            # Detached: the socket must accept the next message immediately.
            _spawn(_extract_memories(websocket, agent, text, result["text"]))
        except asyncio.CancelledError:
            log.info("turn cancelled by client")
            await emit({"type": "stopped"})
        except LLMNotConfigured as exc:
            await emit({"type": "error", "message": str(exc)})
            await emit({"type": "state", "state": "idle"})
        except ToolError as exc:
            await emit({"type": "error", "message": str(exc)})
            await emit({"type": "state", "state": "idle"})
        except Exception as exc:  # noqa: BLE001
            log.exception("turn failed")
            await emit({"type": "error", "message": f"Something went wrong: {exc}"})
            await emit({"type": "state", "state": "idle"})
        finally:
            db.close()

    await emit(
        {
            "type": "hello",
            "provider": settings.provider,
            "model": settings.llm_model,
            "llm_configured": settings.llm_configured,
            "stt_provider": settings.stt_provider,
            "tts_provider": settings.tts_provider,
            "google_enabled": settings.google_enabled,
            "whatsapp_mode": settings.whatsapp_effective_mode,
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await emit({"type": "error", "message": "malformed JSON"})
                continue

            kind = message.get("type")
            if kind == "user_message":
                if run_task is not None and not run_task.done():
                    await emit(
                        {
                            "type": "error",
                            "message": "I'm still working on the last request — send 'stop' first.",
                        }
                    )
                    continue
                run_task = asyncio.create_task(run_turn(message))
            elif kind == "confirm":
                future = pending.get(str(message.get("id")))
                if future is not None and not future.done():
                    future.set_result(bool(message.get("approved")))
            elif kind == "stop":
                if run_task is not None and not run_task.done():
                    run_task.cancel()
                await emit({"type": "stopped"})
            elif kind == "ping":
                await emit({"type": "pong"})
            else:
                await emit({"type": "error", "message": f"unknown message type '{kind}'"})
    except WebSocketDisconnect:
        log.info("client disconnected")
    except Exception:  # noqa: BLE001
        log.exception("websocket loop crashed")
    finally:
        if run_task is not None and not run_task.done():
            run_task.cancel()
        await hub.unregister(websocket)
