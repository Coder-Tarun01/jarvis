"""Bulk import of name -> number pairs into the live alias file.

Why this exists: WhatsApp Desktop *does* keep the chat list locally, but every
store is closed to us — ``%LOCALAPPDATA%\\Packages\\5319275A.WhatsAppDesktop_*\\
LocalState\\sessions\\<id>\\*.db`` is SQLCipher-encrypted (no plaintext SQLite
header), the WebView IndexedDB only holds app logs, and the Windows People store
is typically empty. So there is nothing to scrape; the pairs arrive from sources
that legitimately hold them:

* **contacts** — ``data/contacts_cache.json``, the Google Contacts mirror that
  ``google_contacts_sync`` fills. One call turns every contact that has a phone
  number into an alias.
* **text** — anything pasted or exported: ``Name=+91…``, ``Name,+91…``, TSV,
  ``Name: +91…``, number-first lines, vCard (``FN``/``TEL``) and JSON.

Merging is additive on purpose: an alias you wrote by hand is never replaced by a
bulk take (``overwrite=True`` changes that), and a name that already resolves to
a different number is reported as a conflict instead of silently flipping.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from . import contacts_cache, whatsapp, whatsapp_aliases

log = get_logger("whatsapp_import")

MAX_IMPORT = whatsapp_aliases.MAX_ALIASES
MAX_REPORTED = 20

# a bare phone number: digits with the usual human separators, nothing else
_PHONE_ONLY = re.compile(r"^\+?[\d][\d\s\-().]*$")
# "+91 98765 43210 Prashant" / "9876543210 Ravi"
_NUMBER_FIRST = re.compile(r"^(\+?[\d][\d\s\-().]{5,})\s+([^\d].*)$")
_DELIMITERS = ("=", ",", ";", "\t", "|", ":")
_NUMBER_LABELS = ("tel:", "phone:", "mobile:", "mob:", "cell:", "whatsapp:", "wa:")
_KINDS = ("auto", "contacts", "text")
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)  # letters only, any script


def _is_a_name(name: str) -> bool:
    """'Prashant' yes, '+91 98661 66186' / '100' no — a number is not a name."""
    return bool(_LETTERS.search(name or ""))


# --------------------------------------------------------------------------- parsing
def _clean_name(name: str) -> str:
    """'  "Prashant  Frd" ' -> 'Prashant Frd'."""
    value = str(name or "").replace("\u00a0", " ")
    value = " ".join(value.split())
    return value.strip(" \t\"'<>;,.-")


def _clean_number(value: str) -> str:
    """'TEL;CELL: "+91 98765 43210"' -> '+91 98765 43210'."""
    text = str(value or "").strip().strip("\"'")
    lowered = text.lower()
    for label in _NUMBER_LABELS:
        if lowered.startswith(label):
            text = text[len(label):].strip().strip("\"'")
            break
    return text


def _is_phone(value: str) -> bool:
    text = _clean_number(value)
    if not text or not _PHONE_ONLY.match(text):
        return False
    digits = re.sub(r"[^0-9]", "", text)
    return whatsapp.MIN_DIGITS <= len(digits) <= whatsapp.MAX_DIGITS


def _split_line(line: str) -> tuple[str, str] | None:
    """One line -> (name, number), or None when it is not a pair."""
    text = line.strip()
    if not text:
        return None

    for delimiter in _DELIMITERS:
        index = text.find(delimiter)
        if index <= 0:
            continue
        left, right = text[:index].strip(), text[index + 1:].strip()
        # "Prashant, +91 98765 43210" — the number side decides
        if left and _is_phone(right):
            return _clean_name(left), _clean_number(right)

    match = _NUMBER_FIRST.match(text)
    if match and _is_phone(match.group(1)):
        return _clean_name(match.group(2)), _clean_number(match.group(1))
    return None

def _vcard_field(line: str) -> str:
    """'FN:Uncle Bob' / 'FN=Uncle Bob' / 'TEL;TYPE=CELL:+91…' -> the value part."""
    for separator in (":", "="):
        index = line.find(separator)
        if index > 0:
            return line[index + 1:].strip()
    return ""


def _json_pairs(text: str) -> list[tuple[str, str]] | None:
    """A JSON document ({"Prashant": "+91…"} or [{"name":…,"number":…}]) or None."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None

    pairs: list[tuple[str, str]] = []

    def add(name: Any, number: Any) -> None:
        if name and number is not None:
            pairs.append((_clean_name(str(name)), _clean_number(str(number))))

    if isinstance(data, dict):
        inner = data.get("aliases") if isinstance(data.get("aliases"), dict) else data
        for name, value in inner.items():
            if isinstance(value, (str, int, float)):
                add(name, value)
        return pairs

    for item in data if isinstance(data, list) else []:
        if isinstance(item, str):
            parsed = _split_line(item)
            if parsed:
                pairs.append(parsed)
        elif isinstance(item, dict):
            number = (
                item.get("number")
                or item.get("phone")
                or item.get("phone_number")
                or item.get("mobile")
            )
            phones = item.get("phones")
            if not number and isinstance(phones, list) and phones:
                number = phones[0]
            add(item.get("name") or item.get("display_name") or item.get("fn"), number)
    return pairs


def parse(text: str) -> list[tuple[str, str]]:
    """Best-effort (name, number) pairs out of any pasted or exported list."""
    raw = (text or "").replace("\ufeff", "")
    if not raw.strip():
        return []

    json_pairs = _json_pairs(raw)
    if json_pairs is not None:
        return json_pairs[:MAX_IMPORT]

    pairs: list[tuple[str, str]] = []
    in_vcard = False
    vcard_name = ""
    vcard_numbers: list[str] = []

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        upper = line.upper()

        if upper.startswith("BEGIN:VCARD"):
            in_vcard, vcard_name, vcard_numbers = True, "", []
            continue
        if in_vcard:
            if upper.startswith("END:VCARD"):
                for number in vcard_numbers:
                    if vcard_name and _is_phone(number):
                        pairs.append((vcard_name, number))
                in_vcard, vcard_name, vcard_numbers = False, "", []
            elif upper.startswith("FN"):
                vcard_name = _clean_name(_vcard_field(line))
            elif upper.startswith("N:") and not vcard_name:
                # N:Last;First;Middle;;  -> "First Last"
                parts = [p for p in _vcard_field(line).split(";") if p.strip()]
                vcard_name = _clean_name(" ".join(reversed(parts[:2])))
            elif upper.startswith("TEL"):
                value = _vcard_field(line)
                if value:
                    vcard_numbers.append(_clean_number(value))
            continue

        if not line or line.startswith(("#", "//")):
            continue
        if not any(char.isdigit() for char in line):
            continue  # a header such as "name,number"
        parsed = _split_line(line)
        if parsed:
            pairs.append(parsed)

    return pairs[:MAX_IMPORT]


# --------------------------------------------------------------------------- sources
def from_contacts_cache(
    settings: Settings | None = None, limit: int = 0
) -> list[tuple[str, str]]:
    """Every cached Google contact that has a phone number -> (name, first number)."""
    contacts = contacts_cache.load(settings)["contacts"]
    pairs = [
        (c["name"], c["phones"][0])
        for c in contacts
        if c.get("phones") and _is_a_name(c["name"])
    ]
    return pairs[:limit] if limit and limit > 0 else pairs


# --------------------------------------------------------------------------- merge
def merge(
    settings: Settings | None = None,
    pairs: list[tuple[str, str]] | None = None,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    source: str = "text",
) -> dict[str, Any]:
    """Fold ``pairs`` into the alias file and report every decision."""
    settings = settings or get_settings()
    existing = whatsapp_aliases.load(settings)["aliases"]
    current = {name.lower(): (name, number) for name, number in existing.items()}

    pending: dict[str, tuple[str, str]] = {}  # lower name -> (name to store, digits)
    unchanged = 0
    conflicts: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []

    for name, number in pairs or []:
        clean = _clean_name(name)
        if not clean:
            if len(invalid) < MAX_REPORTED:
                invalid.append({"name": str(name)[:60], "reason": "no name"})
            continue
        if not _is_a_name(clean):
            if len(invalid) < MAX_REPORTED:
                invalid.append(
                    {"name": clean[:40], "reason": "looks like a number, not a name"}
                )
            continue
        try:
            digits = whatsapp.normalise_number(
                _clean_number(number), settings.whatsapp_country_code
            )
        except ToolError as exc:
            if len(invalid) < MAX_REPORTED:
                invalid.append(
                    {"name": clean, "number": str(number)[:40], "reason": str(exc)[:120]}
                )
            continue

        key = clean.lower()
        if key in current:
            stored_name, stored_number = current[key]
            try:
                stored_digits = whatsapp.normalise_number(
                    stored_number, settings.whatsapp_country_code
                )
            except ToolError:
                stored_digits = ""
            if stored_digits == digits:
                unchanged += 1
                continue
            if not overwrite:
                if len(conflicts) < MAX_REPORTED:
                    conflicts.append(
                        {
                            "name": stored_name,
                            "kept": whatsapp.mask(stored_digits or stored_number),
                            "ignored": whatsapp.mask(digits),
                        }
                    )
                continue
            pending[key] = (stored_name, digits)  # keep the spelling already on disk
        else:
            pending[key] = (clean, digits)

    added = sum(1 for key in pending if key not in current)
    updated = len(pending) - added

    if pending and not dry_run:
        merged = dict(existing)
        for key, (name, digits) in pending.items():
            if key in current:
                merged[current[key][0]] = digits
            else:
                merged[name] = digits
        whatsapp_aliases.save_many(settings, merged)
        total = len(merged)
    else:
        total = len(existing) + added

    samples = [
        {"name": name, "number": whatsapp.mask(digits)}
        for name, digits in list(pending.values())[:5]
    ]

    if dry_run:
        message = (
            f"dry run — {added} alias(es) would be added, {updated} updated, "
            f"{unchanged} already correct"
        )
    else:
        message = (
            f"imported {added} new alias(es) from {source}, updated {updated}, "
            f"{unchanged} already correct — {total} aliases in the file"
        )
    if conflicts:
        message += (
            f"; {len(conflicts)} name(s) kept their existing number "
            "(pass overwrite to replace them)"
        )
    if invalid:
        message += f"; {len(invalid)} entr(ies) skipped as unusable"

    log.info(
        "whatsapp bulk import (%s): +%d ~%d =%d /%d conflicts, %d invalid",
        source, added, updated, unchanged, len(conflicts), len(invalid),
    )

    return {
        "ok": True,
        "source": source,
        "parsed": len(pairs or []),
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "invalid": invalid,
        "conflict_count": len(conflicts),
        "invalid_count": len(invalid),
        "total": total,
        "dry_run": dry_run,
        "samples": samples,
        "message": message,
    }


def run(
    settings: Settings | None = None,
    *,
    text: str = "",
    source: str = "auto",
    overwrite: bool = False,
    dry_run: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """Import from a pasted list or the contacts cache, then merge into the aliases."""
    settings = settings or get_settings()
    kind = (source or "auto").strip().lower()
    if kind not in _KINDS:
        raise ToolError("source must be 'auto', 'contacts' or 'text'")

    if kind == "auto":
        kind = "text" if (text or "").strip() else "contacts"

    if kind == "text":
        if not (text or "").strip():
            raise ToolError(
                "paste the contacts to import — one 'Name=+91 98765 43210' per line "
                "(a comma, tab or colon works too)"
            )
        pairs = parse(text)
        label = "the pasted list"
    else:
        pairs = from_contacts_cache(settings, limit=limit)
        label = "the Google contacts cache"
        if not pairs:
            raise ToolError(
                "the Google contacts cache is empty — run google_contacts_sync first, "
                "or paste a list of 'Name=+number' lines"
            )

    if limit and limit > 0:
        pairs = pairs[:limit]
    if not pairs:
        raise ToolError(
            "found no usable name/number pairs — expected e.g. "
            "'Prashant Frd=+91 98765 43210' on each line"
        )

    return merge(settings, pairs, overwrite=overwrite, dry_run=dry_run, source=label)

