"""The agent loop.

user message
  -> save message, retrieve relevant memories
  -> build system prompt (persona + clock + memories)
  -> the configured LLM provider with tools (streaming text to the browser)
  -> execute tool calls (confirmation-gated where required)
  -> stream the final answer
  -> persist the answer, then extract durable facts into long-term memory
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from ..core.models import Conversation, Message
from ..core.utils import truncate, utcnow
from ..memory import extractor, store
from ..services.llm import LLMService, ToolCall, get_llm
from ..services.persona import build_system_prompt
from ..tools.base import ToolContext
from ..tools.registry import execute_tool, get_tool, needs_confirmation, tool_schemas

log = get_logger("agent")

Emit = Callable[[dict[str, Any]], Awaitable[None]]
Confirmer = Callable[[str, str, dict[str, Any], str], Awaitable[bool]]

#: Words that mean "the model says it already did something".
_ACTION_CLAIM = re.compile(
    r"\b(opened|launched|started|closed|quit|sent|messaged|texted|added|created|"
    r"scheduled|reminded|saved|deleted|removed|updated|imported|searched|drafted|"
    r"booked|set up|turned (?:on|off)|switched|done|finished|completed|all set)\b",
    re.IGNORECASE,
)
#: Polite lead-ins in front of an instruction: "can you open …", "jarvis, please add …"
_POLITE_LEAD = re.compile(
    r"^(?:hey\s+|ok\s+|yo\s+)?(?:jarvis\b[,:]?\s*)?(?:please\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?",
    re.IGNORECASE,
)
#: Verbs that make a sentence an instruction rather than a question.
_ACTION_VERBS = {
    "open", "launch", "start", "run", "close", "quit", "kill", "stop",
    "send", "message", "text", "whatsapp", "mail", "email", "draft",
    "add", "create", "new", "schedule", "remind", "set", "save",
    "delete", "remove", "update", "rename", "import", "export",
    "search", "find", "look", "google", "read", "show", "list",
    "turn", "switch", "play", "write", "note", "remember", "sync",
}


def asks_for_action(text: str) -> bool:
    """True when the message *instructs* the assistant to do something.

    Questions are excluded on purpose: "what did you open?" must not trigger a
    corrective turn that could make the model run a fresh action.
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return False
    lead = _POLITE_LEAD.match(cleaned)
    remainder = cleaned[lead.end():] if lead else cleaned
    head = (remainder.split(maxsplit=1) or [""])[0].strip(".,!?;:").lower()
    return head in _ACTION_VERBS


#: Sent once, when a turn claimed an action without calling a tool.
CORRECTION = """## Correction
Your previous reply described an action but no tool ran, so nothing happened.
If the user asked you to do something, call the matching tool now with its arguments.
If it was only a question, answer it plainly without claiming any action.
Never write tool calls as text (no "[used tools] ..."), and never say you did
something unless a tool result confirms it."""

#: Last resort: keep a false success out of the transcript.
UNVERIFIED_REPLY = (
    "I didn't actually do that — I answered without calling a tool, so nothing "
    "changed. Ask me again and I'll run it for real."
)


def title_from(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "New conversation"
    return cleaned[:60] + ("…" if len(cleaned) > 60 else "")


def merge_turns(rows: list[Message]) -> list[dict[str, Any]]:
    """Build a provider-neutral message list (alternating roles, starts with user)."""
    merged: list[dict[str, Any]] = []
    for row in rows:
        if row.role not in ("user", "assistant"):
            continue
        content = (row.content or "").strip()
        if not content:
            continue
        if merged and merged[-1]["role"] == row.role:
            merged[-1]["content"] += "\n\n" + content
        else:
            merged.append({"role": row.role, "content": content})
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


class Agent:
    def __init__(self, settings: Settings | None = None, llm: LLMService | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or get_llm()

    # ------------------------------------------------------------------ public
    async def respond(
        self,
        db: Session,
        conversation_id: int,
        user_text: str,
        *,
        emit: Emit,
        confirm: Confirmer,
    ) -> dict[str, Any]:
        settings = self.settings
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise ToolError(f"conversation {conversation_id} not found")

        db.add(Message(conversation_id=conversation_id, role="user", content=user_text))
        if conversation.title in ("", "New conversation"):
            conversation.title = title_from(user_text)
        conversation.updated_at = utcnow()
        db.commit()

        memories = store.search(
            db, user_text, settings.memory_top_k, settings.memory_min_score
        )
        system = build_system_prompt(settings, memories)
        history = merge_turns(self._recent_messages(db, conversation_id))
        tools = tool_schemas()
        ctx = ToolContext(
            db=db,
            conversation_id=conversation_id,
            notify=emit,
            settings=settings,
        )

        await emit({"type": "state", "state": "thinking"})
        tool_notes: list[dict[str, Any]] = []
        final_text = ""
        corrective = False
        corrective_used = False

        for iteration in range(1, settings.max_tool_iterations + 1):
            current_system = system + ("\n\n" + CORRECTION if corrective else "")
            corrective = False
            turn = await self.llm.stream_turn(
                messages=history,
                system=current_system,
                tools=tools,
                on_text=self._token_emitter(emit),
            )
            if turn.assistant_message:
                history.append(turn.assistant_message)
            if turn.text:
                final_text = turn.text

            if not turn.tool_calls:
                if not turn.text:
                    log.warning(
                        "model returned an empty turn (stop_reason=%s)", turn.stop_reason
                    )
                    break

                # A small/free model can *narrate* an action instead of calling a tool
                # ("Opened, boss"). Give it exactly one chance to correct itself, then
                # refuse to leave a false success in the transcript.
                if (
                    iteration == 1
                    and tools
                    and not corrective_used
                    and _ACTION_CLAIM.search(turn.text)
                    and asks_for_action(user_text)
                ):
                    log.warning(
                        "first turn claimed an action without a tool call; asking once for the tool"
                    )
                    if turn.assistant_message and history and history[-1] is turn.assistant_message:
                        history.pop()  # do not feed the claim back to the model
                    corrective_used = True
                    corrective = True
                    await emit({"type": "state", "state": "thinking"})
                    continue

                if corrective_used and not tool_notes and _ACTION_CLAIM.search(turn.text):
                    log.warning("still no tool call after the correction; replacing the claim")
                    final_text = UNVERIFIED_REPLY
                    await emit({"type": "warning", "message": UNVERIFIED_REPLY})
                break

            log.info("iteration %s: %s tool call(s)", iteration, len(turn.tool_calls))
            results: list[dict[str, Any]] = []
            for call in turn.tool_calls:
                output, is_error = await self._run_tool(ctx, call, emit, confirm, tool_notes)
                results.append(
                    {
                        "tool_use_id": call.id,
                        "content": output,
                        "is_error": is_error,
                    }
                )
            history.extend(self.llm.tool_result_messages(results))
        else:
            await emit(
                {
                    "type": "warning",
                    "message": "I stopped after the maximum number of tool calls. Ask me to continue.",
                }
            )

        if final_text.strip():
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=final_text.strip(),
                )
            )
            conversation.updated_at = utcnow()
            db.commit()

        return {
            "conversation_id": conversation_id,
            "title": conversation.title,
            "text": final_text.strip(),
            "tools": tool_notes,
            "memories_used": [m.text for m in memories],
            "updated_at": conversation.updated_at,
        }

    async def memorize(self, db: Session, user_text: str, assistant_text: str) -> list[str]:
        """Best-effort fact extraction; never breaks a turn."""
        try:
            return await extractor.extract_and_store(
                db, self.llm, user_text, assistant_text, self.settings
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("memory extraction failed")
            return []

    # ------------------------------------------------------------------ internals
    def _recent_messages(self, db: Session, conversation_id: int) -> list[Message]:
        limit = max(2, int(self.settings.history_limit))
        rows = list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc())
                .limit(limit)
            ).all()
        )
        rows.reverse()
        return rows

    @staticmethod
    def _token_emitter(emit: Emit) -> Callable[[str], Awaitable[None]]:
        async def on_text(chunk: str) -> None:
            await emit({"type": "token", "text": chunk})

        return on_text

    async def _run_tool(
        self,
        ctx: ToolContext,
        call: ToolCall,
        emit: Emit,
        confirm: Confirmer,
        notes: list[dict[str, Any]],
    ) -> tuple[str, bool]:
        name = call.name
        arguments = call.input or {}
        call_id = call.id

        await emit({"type": "tool_call", "id": call_id, "name": name, "input": arguments})

        tool = get_tool(name)
        if tool is None:
            message = f"unknown tool '{name}'"
            await emit(
                {"type": "tool_result", "id": call_id, "name": name, "ok": False, "summary": message}
            )
            notes.append({"name": name, "ok": False, "summary": message})
            return message, True

        if needs_confirmation(tool, self.settings):
            hint = tool.confirmation_hint or "This action has effects outside JARVIS."
            approved = await confirm(call_id, name, arguments, hint)
            if not approved:
                message = "The user declined this action. Do not retry it; suggest an alternative."
                await emit(
                    {
                        "type": "tool_result",
                        "id": call_id,
                        "name": name,
                        "ok": False,
                        "summary": "denied by user",
                    }
                )
                notes.append({"name": name, "ok": False, "summary": "denied by user"})
                return message, False

        try:
            output = await execute_tool(name, arguments, ctx)
        except ToolError as exc:
            message = f"{name} failed: {exc}"
            await emit(
                {"type": "tool_result", "id": call_id, "name": name, "ok": False, "summary": str(exc)}
            )
            notes.append({"name": name, "ok": False, "summary": str(exc)})
            return message, True

        summary = truncate(output.replace("\n", " "), 240)
        await emit(
            {"type": "tool_result", "id": call_id, "name": name, "ok": True, "summary": summary}
        )
        notes.append({"name": name, "ok": True, "summary": summary})

        client_action = self._client_action(output)
        if client_action is not None:
            await emit({"type": "client_action", **client_action})

        return output, False

    @staticmethod
    def _client_action(output: str) -> dict[str, Any] | None:
        """Tools may return {"client_action": {...}} to ask the browser to do something."""
        if not output.lstrip().startswith("{"):
            return None
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and isinstance(data.get("client_action"), dict):
            return data["client_action"]
        return None
