"""Local mirror of Google Contacts, used for WhatsApp name -> number lookups.

Google's People API is the source of truth, but sending a WhatsApp message should
not depend on a network round trip. `google_contacts_sync` writes
``data/contacts_cache.json``; the WhatsApp resolver reads it *before* falling back
to a live People API query (and remembers whatever the live query found).

Shape on disk::

    {
      "updated_at": "2026-11-14T02:10:00Z",
      "source": "google",
      "count": 412,
      "contacts": [
        {"name": "Gowri Akka", "phones": ["+91 90592 94845"], "emails": [], "org": ""}
      ]
    }

Only contacts that carry at least one phone number are stored: the file exists to
answer "what is <name>'s number?", nothing else.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.utils import iso, name_matches_tokens, utcnow

log = get_logger("contacts_cache")

MAX_ENTRIES = 5000


def _path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.contacts_cache_path


def _key(name: str) -> str:
    """'Gowri  Akka' / 'gowri-akka' -> 'gowriakka' for tolerant matching."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def load(settings: Settings | None = None) -> dict[str, Any]:
    """The cache as a dict; an empty skeleton when the file is missing or broken."""
    path = _path(settings)
    empty = {"updated_at": None, "source": "none", "count": 0, "contacts": []}
    try:
        if not path.exists():
            return empty
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("contacts cache unreadable (%s) — ignoring it", exc)
        return empty

    contacts = data.get("contacts")
    if not isinstance(contacts, list):
        return empty
    clean = [item for item in contacts if isinstance(item, dict) and item.get("name")]
    return {
        "updated_at": data.get("updated_at"),
        "source": data.get("source") or "google",
        "count": len(clean),
        "contacts": clean,
    }


def save(
    settings: Settings | None = None,
    contacts: list[dict[str, Any]] | None = None,
    *,
    source: str = "google",
) -> dict[str, Any]:
    """Replace the cache atomically. Entries without a phone number are dropped."""
    settings = settings or get_settings()
    path = _path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for contact in contacts or []:
        name = str(contact.get("name") or "").strip()
        phones = [str(p).strip() for p in (contact.get("phones") or []) if str(p).strip()]
        if not name or not phones:
            continue
        key = _key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "name": name,
                "phones": phones,
                "emails": [str(e) for e in (contact.get("emails") or []) if e],
                "org": str(contact.get("org") or ""),
            }
        )
        if len(rows) >= MAX_ENTRIES:
            break

    payload = {
        "updated_at": iso(utcnow()),
        "source": source,
        "count": len(rows),
        "contacts": rows,
    }

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a reader never sees half a file
    log.info("contacts cache written: %d entries -> %s", len(rows), path)
    return payload


def lookup(settings: Settings | None = None, who: str = "") -> list[dict[str, Any]]:
    """Contacts in the cache matching ``who``: exact, prefix, then words in any order."""
    wanted = _key(who)
    if not wanted:
        return []
    contacts = load(settings)["contacts"]

    exact = [c for c in contacts if _key(c["name"]) == wanted]
    if exact:
        return exact

    prefix = [c for c in contacts if _key(c["name"]).startswith(wanted)]
    if prefix:
        return prefix

    words = [w for w in re.split(r"[^a-z0-9]+", (who or "").lower()) if w]
    if len(words) > 1:
        # "frd prashant" and "prashant frd" both find "Prashant Frd"
        return [c for c in contacts if name_matches_tokens(who, c["name"])]
    return []


def remember(settings: Settings | None = None, contact: dict[str, Any] | None = None) -> None:
    """Add one freshly-resolved contact to the cache (best effort, never raises)."""
    if not contact or not contact.get("phones"):
        return
    try:
        data = load(settings)
        key = _key(str(contact.get("name") or ""))
        if not key:
            return
        rows = [c for c in data["contacts"] if _key(c["name"]) != key]
        rows.append(
            {
                "name": str(contact["name"]),
                "phones": [str(p) for p in contact["phones"]],
                "emails": [str(e) for e in (contact.get("emails") or [])],
                "org": str(contact.get("org") or ""),
            }
        )
        save(settings, rows, source=data.get("source") or "google")
    except OSError as exc:  # a read-only data dir must not break a send
        log.warning("could not update the contacts cache: %s", exc)
