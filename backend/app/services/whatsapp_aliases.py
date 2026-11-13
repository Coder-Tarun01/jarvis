"""Runtime-editable WhatsApp aliases (``data/whatsapp_aliases.json``).

``WHATSAPP_CONTACTS`` in ``.env`` is the static list — editing it needs a container
restart. This file is the live half: ``whatsapp_save_contact`` writes it, the resolver
reads it, and a change is effective on the very next message.

Shape on disk::

    {"updated_at": "2026-11-14T03:20:00Z",
     "aliases": {"prashant frd": "+91 98765 43210"}}

Aliases are plain name -> number pairs; the resolver normalises the numbers and
applies the same loose matching it uses everywhere else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.utils import iso, utcnow

log = get_logger("whatsapp_aliases")

MAX_ALIASES = 2000


def _path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.whatsapp_aliases_path


def _clean_name(name: str) -> str:
    return " ".join((name or "").split()).strip()


def load(settings: Settings | None = None) -> dict[str, Any]:
    """{"updated_at": ..., "aliases": {name: number}} — empty when missing/broken."""
    path = _path(settings)
    empty: dict[str, Any] = {"updated_at": None, "aliases": {}}
    try:
        if not path.exists():
            return empty
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("alias file unreadable (%s) — ignoring it", exc)
        return empty

    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        return empty
    clean = {
        _clean_name(name): str(number)
        for name, number in aliases.items()
        if _clean_name(name) and str(number).strip()
    }
    return {"updated_at": data.get("updated_at"), "aliases": clean}


def _save(settings: Settings, aliases: dict[str, str]) -> dict[str, Any]:
    path = _path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": iso(utcnow()),
        "count": len(aliases),
        "aliases": dict(sorted(aliases.items())[:MAX_ALIASES]),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    log.info("whatsapp aliases written: %d entry(ies) -> %s", len(aliases), path)
    return payload


def save_many(settings: Settings | None = None, aliases: dict[str, str] | None = None) -> dict[str, Any]:
    """Upsert many name -> number pairs with a single atomic write.

    Used by the bulk importer: one write for the whole batch instead of one per
    contact. Names are matched case-insensitively, so a bulk import never leaves
    both ``Prashant`` and ``prashant`` behind.
    """
    settings = settings or get_settings()
    current = dict(load(settings)["aliases"])

    incoming: dict[str, str] = {}
    for name, number in (aliases or {}).items():
        clean = _clean_name(name)
        value = str(number or "").strip()
        if clean and value:
            incoming[clean] = value

    lowered = {name.lower() for name in incoming}
    for existing in list(current):
        if existing.lower() in lowered and existing not in incoming:
            del current[existing]  # the new spelling replaces an old case variant
    current.update(incoming)

    _save(settings, current)
    return {"count": len(current), "aliases": current}


def save(settings: Settings | None = None, *, name: str, number: str) -> dict[str, Any]:
    """Add or replace one alias. Returns the stored entry."""
    settings = settings or get_settings()
    clean = _clean_name(name)
    if not clean:
        raise ValueError("an alias needs a name")

    stored = save_many(settings, {clean: (number or "").strip()})
    return {"name": clean, "number": stored["aliases"][clean], "count": stored["count"]}


def remove(settings: Settings | None = None, *, name: str) -> bool:
    settings = settings or get_settings()
    clean = _clean_name(name).lower()
    aliases = dict(load(settings)["aliases"])
    remaining = {k: v for k, v in aliases.items() if k.lower() != clean}
    if len(remaining) == len(aliases):
        return False
    _save(settings, remaining)
    return True
