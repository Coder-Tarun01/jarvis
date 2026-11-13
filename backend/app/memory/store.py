"""Long-term memory: store, de-duplicate and rank durable facts.

Retrieval is deliberately simple and dependency-free: token-set similarity
(a cosine-style score over stop-word-filtered word sets). For a single user's
memory list (hundreds of facts) this beats the latency and cost of embeddings.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..core.models import Memory
from ..core.utils import utcnow

log = get_logger("memory")

_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "had",
    "has", "have", "he", "her", "his", "i", "if", "in", "is", "it", "its", "me",
    "my", "of", "on", "or", "our", "she", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "was", "we", "were", "what", "when",
    "which", "who", "will", "with", "you", "your", "am", "do", "does", "did",
    "so", "not", "no", "yes", "just", "can", "could", "would", "should", "about",
}


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split()).strip(" .!?")


def tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOPWORDS and len(w) > 1}


def remember(db: Session, text: str, source: str = "chat", tags: str = "") -> Memory | None:
    """Store a fact unless it is (nearly) a duplicate. Returns the stored row."""
    cleaned = " ".join((text or "").split()).strip(" .!?")
    if len(cleaned) < 3:
        return None

    wanted = tokens(cleaned)
    for existing in db.scalars(select(Memory)).all():
        if normalize(existing.text) == normalize(cleaned):
            return existing
        current = tokens(existing.text)
        if wanted and current:
            overlap = len(wanted & current) / max(len(wanted), len(current))
            if overlap >= 0.8:
                return existing

    memory = Memory(text=cleaned, source=source, tags=tags)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    log.info("remembered: %s", cleaned)
    return memory


def search(
    db: Session,
    query: str,
    top_k: int = 6,
    min_score: float = 0.12,
) -> list[Memory]:
    """Rank memories against a query; touches last_used_at on the winners."""
    query_tokens = tokens(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, Memory]] = []
    for memory in db.scalars(select(Memory)).all():
        memory_tokens = tokens(memory.text) | tokens(memory.tags)
        if not memory_tokens:
            continue
        overlap = len(query_tokens & memory_tokens)
        if not overlap:
            continue
        score = overlap / ((len(query_tokens) ** 0.5) * (len(memory_tokens) ** 0.5))
        if score >= min_score:
            scored.append((score, memory))

    scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
    winners = [memory for _, memory in scored[:top_k]]

    if winners:
        now = utcnow()
        for memory in winners:
            memory.last_used_at = now
        db.commit()
    return winners


def list_memories(db: Session, limit: int = 200) -> list[Memory]:
    return list(db.scalars(select(Memory).order_by(Memory.id.desc()).limit(limit)).all())


def delete_memory(db: Session, memory_id: int) -> bool:
    memory = db.get(Memory, memory_id)
    if memory is None:
        return False
    db.delete(memory)
    db.commit()
    return True


def format_for_prompt(memories: Sequence[Memory]) -> str:
    """Compact bullet list for the system prompt."""
    if not memories:
        return ""
    lines = [f"- {m.text}" for m in memories]
    return "\n".join(lines)


def all_texts(db: Session) -> Iterable[str]:
    return (m.text for m in db.scalars(select(Memory)).all())
