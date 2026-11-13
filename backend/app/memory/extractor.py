"""Pull durable facts out of a finished turn and store them in long-term memory."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..services.llm import LLMService
from . import store

log = get_logger("memory.extractor")

SYSTEM = (
    "You maintain a long-term memory file for a personal assistant. "
    "You only output JSON and you never invent facts."
)

PROMPT = """Conversation snippet:

USER: {user}

ASSISTANT: {assistant}

Extract only DURABLE facts about the user that are worth remembering for months:
identity, preferences, routines, relationships, ongoing projects, hard constraints,
important dates. Ignore transient chit-chat, one-off questions and anything the
assistant said about itself.

Return a JSON array of short third-person statements, e.g.
["The user's name is Sam.", "The user prefers metric units.", "The user's sister is called Mia."]
Return [] if there is nothing durable."""

_REMEMBER = re.compile(r"remember(?: that)?[:,]?\s+(.+)", re.I | re.S)


def heuristic_facts(user_text: str) -> list[str]:
    """Cheap fallback so explicit 'remember that…' never gets lost."""
    text = " ".join((user_text or "").split())
    if not text:
        return []
    match = _REMEMBER.search(text)
    if match:
        fact = match.group(1).strip().strip('."')
        if len(fact) > 3:
            return [fact[0].upper() + fact[1:]]
    lowered = text.lower()
    if lowered.startswith(("my name is ", "i am ", "i'm ", "call me ")):
        return [text]
    return []


async def extract_and_store(
    db: Session,
    llm: LLMService,
    user_text: str,
    assistant_text: str,
    settings: Settings | None = None,
) -> list[str]:
    settings = settings or get_settings()
    facts: list[str] = []

    if settings.memory_extraction_enabled and llm.available:
        try:
            data = await llm.complete_json(
                system=SYSTEM,
                prompt=PROMPT.format(
                    user=user_text[:4000],
                    assistant=(assistant_text or "")[:2000],
                ),
                max_tokens=500,
                # background work always uses the cheap model
                model=llm.model_fast,
            )
            if isinstance(data, list):
                facts = [str(item) for item in data if isinstance(item, (str, int, float))]
            elif isinstance(data, dict):
                maybe = data.get("facts") or data.get("memories") or []
                if isinstance(maybe, list):
                    facts = [str(item) for item in maybe if isinstance(item, (str, int, float))]
        except Exception as exc:  # noqa: BLE001 - memory is best-effort
            log.warning("LLM memory extraction failed: %s", exc)

    if not facts:
        facts = heuristic_facts(user_text)

    saved: list[str] = []
    for fact in facts:
        fact = " ".join(str(fact).split()).strip(" .")
        if 3 <= len(fact) <= 400:
            memory = store.remember(db, fact, source="auto")
            if memory is not None:
                saved.append(memory.text)
    if saved:
        log.info("extracted %d memory fact(s)", len(saved))
    return saved
