"""WhatsApp message sending.

Two delivery paths, picked by ``WHATSAPP_MODE`` (default ``auto``):

* ``cloud`` — Meta's WhatsApp Cloud API. This really sends. Needs
  ``WHATSAPP_ACCESS_TOKEN`` + ``WHATSAPP_PHONE_NUMBER_ID``; the access token is a
  temporary/system-user token from *Meta → WhatsApp → API setup*.
* ``link`` — no credentials at all: we resolve the name to a number and hand
  ``whatsapp://send?phone=…&text=…`` to the OS, which opens the WhatsApp desktop app on
  that exact chat with the message already typed. ``web_link()`` stays available as a
  ``wa.me`` fallback.

Recipients are either an alias from ``WHATSAPP_CONTACTS`` (``mom=+91…``), a name from the
local Google contacts cache (``data/contacts_cache.json``, refreshed by
``google_contacts_sync``), a live Google Contacts lookup, or a raw phone number in
international format. Everything is normalised to digits before it reaches Meta or the
link, so ``+91 98765-43210`` and ``0091 98765 43210`` are the same number.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

import httpx

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from ..core.utils import name_matches_tokens
from . import contacts_cache, whatsapp_aliases

log = get_logger("whatsapp")

# WhatsApp rejects longer bodies; 4096 is the documented cap for text messages.
MAX_BODY = 4096
MIN_DIGITS = 8
MAX_DIGITS = 15
TIMEOUT = httpx.Timeout(25.0, connect=10.0)

_NON_DIGITS = re.compile(r"[^0-9]")


class AmbiguousContact(ToolError):
    """More than one contact matched a spoken name — the user has to be specific."""


# --------------------------------------------------------------------------- numbers
def normalise_number(raw: str, country_code: str = "") -> str:
    """'+91 98765-43210' / '0091 98765 43210' / '9876543210' -> '919876543210'.

    ``country_code`` is only used for numbers written without an international
    prefix, so a bare local number still becomes reachable.
    """
    value = (raw or "").strip()
    if not value:
        raise ToolError("a WhatsApp message needs a recipient")

    digits = _NON_DIGITS.sub("", value)
    if not digits:
        raise ToolError(f"'{raw}' does not look like a phone number")

    if value.startswith("+"):
        pass  # already international
    elif digits.startswith("00"):
        digits = digits[2:]
    else:
        code = _NON_DIGITS.sub("", country_code or "")
        # Only rescue numbers short enough to be national ones (<= 10 digits),
        # and never double-prefix one that already carries the country code.
        if code and len(digits) <= 10 and not digits.startswith(code):
            digits = code + digits

    digits = digits.lstrip("0")
    if not (MIN_DIGITS <= len(digits) <= MAX_DIGITS):
        raise ToolError(
            f"'{raw}' is not a usable phone number — include the country code "
            "(e.g. +91 98765 43210) or set WHATSAPP_COUNTRY_CODE."
        )
    return digits


def mask(number: str) -> str:
    """'919876543210' -> '+91******3210' (safe to show in a chat log)."""
    digits = _NON_DIGITS.sub("", number or "")
    if len(digits) <= 4:
        return digits
    return "+" + "*" * (len(digits) - 4) + digits[-4:]


def _alias_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# --------------------------------------------------------------------------- contacts
_warned_entries: set[str] = set()


def contacts(settings: Settings | None = None) -> dict[str, str]:
    """alias -> normalised digits, from WHATSAPP_CONTACTS *and* the live alias file.

    The live file wins when the same name exists in both, so a runtime correction
    beats a stale line in ``.env`` (which needs a restart to change).
    """
    settings = settings or get_settings()
    book: dict[str, str] = {}

    for name, number in settings.whatsapp_contact_map.items():
        try:
            book[name] = normalise_number(number, settings.whatsapp_country_code)
        except ToolError:
            if name not in _warned_entries:  # warn once, not on every turn
                _warned_entries.add(name)
                log.warning("ignoring unusable WHATSAPP_CONTACTS entry '%s'", name)

    for name, number in whatsapp_aliases.load(settings)["aliases"].items():
        try:
            book[name.lower()] = normalise_number(number, settings.whatsapp_country_code)
        except ToolError:
            log.warning("ignoring unusable alias '%s' in the alias file", name)
    return book


def _book_matches(book: dict[str, str], who: str) -> list[tuple[str, str]]:
    """Every alias that could be the spoken name, best-effort and order-tolerant.

    "prashant" -> "Prashant Frd", "frd prashant" -> "Prashant Frd",
    "ravi k" -> "Ravi Kumar". Punctuation and word order do not matter, but a
    two-letter stored word ("F", "Pr") never matches a longer spoken name.
    """
    key = _alias_key(who)
    if not key:
        return []

    exact = [(name, number) for name, number in book.items() if _alias_key(name) == key]
    if exact:
        return exact

    prefix = [(name, number) for name, number in book.items() if _alias_key(name).startswith(key)]
    if prefix:
        return prefix

    return [
        (name, number) for name, number in book.items() if name_matches_tokens(who, name)
    ]


def _from_book(book: dict[str, str], who: str) -> tuple[str, str] | None:
    matches = _book_matches(book, who)
    if not matches:
        return None
    if len(matches) > 1:
        names = ", ".join(sorted(name for name, _ in matches))
        raise AmbiguousContact(f"'{who}' matches several contacts: {names} — say the full name")
    return matches[0][1], matches[0][0]


def resolve_recipient(settings: Settings | None = None, who: str = "") -> tuple[str, str]:
    """Spoken name or number -> (digits, label).

    Sources, in order: WHATSAPP_CONTACTS + the live alias file, a spoken number,
    then the Google contacts cache.
    """
    settings = settings or get_settings()
    who = (who or "").strip()
    if not who:
        raise ToolError("who should I message? Give a contact name or a phone number.")

    book = contacts(settings)

    # 1) configured aliases (env + runtime file), loose matching
    found = _from_book(book, who)
    if found is not None:
        return found

    # 2) the user just spoke a number
    if len(_NON_DIGITS.sub("", who)) >= MIN_DIGITS:
        return normalise_number(who, settings.whatsapp_country_code), who

    # 3) the local Google Contacts cache written by google_contacts_sync
    cached = _from_cache(settings, who)
    if cached is not None:
        return cached

    aliases = len(book)
    cache = contacts_cache.load(settings)
    raise ToolError(
        f"'{who}' is not in WHATSAPP_CONTACTS / aliases ({aliases}), the contacts cache "
        f"({cache['count']}) or Google Contacts. Give me the number once — e.g. "
        f"\"WhatsApp {who} on +91 98765 43210 that I'm running late\" — and I will save it "
        f"as an alias so it resolves on its own next time."
    )


def _from_cache(settings: Settings, who: str) -> tuple[str, str] | None:
    """Resolve a name against data/contacts_cache.json (exact, then prefix)."""
    matches = contacts_cache.lookup(settings, who)
    if not matches:
        return None
    if len(matches) > 1:
        names = ", ".join(sorted(m["name"] for m in matches))
        raise AmbiguousContact(f"'{who}' matches several contacts: {names} — say the full name")
    contact = matches[0]
    for phone in contact.get("phones") or []:
        try:
            return normalise_number(phone, settings.whatsapp_country_code), contact["name"]
        except ToolError:
            continue
    return None


async def resolve_recipient_async(
    settings: Settings | None = None,
    who: str = "",
) -> tuple[str, str, str]:
    """Name or number -> (digits, label, source).

    Order: WHATSAPP_CONTACTS, then the local Google cache, then one live People API
    query whose result is written back to the cache. ``source`` is one of
    ``local`` (env/number/cache) or ``google``.
    """
    settings = settings or get_settings()

    try:
        number, label = resolve_recipient(settings, who)
        return number, label, "local"
    except AmbiguousContact:
        raise  # never guess: a Google lookup would not resolve the ambiguity either
    except ToolError as local_error:
        if not settings.whatsapp_enabled:
            raise

        from . import google  # imported lazily: only needed for the network hop

        try:
            found = await google.search_contacts(settings, query=who, max_results=5)
        except ToolError:
            raise local_error from None

        candidates = [c for c in found.get("contacts") or [] if c.get("phones")]
        if not candidates:
            raise local_error from None
        if len(candidates) > 1:
            names = ", ".join(sorted(c["name"] for c in candidates))
            raise AmbiguousContact(
                f"'{who}' matches several Google contacts: {names} — say the full name"
            ) from None

        contact = candidates[0]
        number = normalise_number(contact["phones"][0], settings.whatsapp_country_code)
        contacts_cache.remember(settings, contact)  # next time it is local
        log.info("resolved '%s' from Google Contacts -> %s", who, mask(number))
        return number, contact["name"], "google"


# --------------------------------------------------------------------------- delivery
def chat_link(number: str, body: str) -> str:
    """`whatsapp://send` deep link: opens the app on that exact chat, text filled in."""
    return f"whatsapp://send?phone={number}&text={quote(body or '', safe='')}"


def web_link(number: str, body: str) -> str:
    """Browser fallback for machines without the WhatsApp protocol handler."""
    return f"https://wa.me/{number}?text={quote(body or '', safe='')}"


def _error_hint(response: httpx.Response, error: dict[str, Any]) -> str:
    code = error.get("code")
    if response.status_code == 401:
        return (
            "the access token was rejected — generate a fresh one in Meta → WhatsApp → "
            "API setup (temporary tokens expire after 24 hours)."
        )
    if response.status_code == 404:
        return "check WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_API_VERSION."
    if response.status_code == 429:
        return "Meta is rate-limiting the number — wait a moment and try again."
    if code == 131030:
        return (
            "that number is not on the allowed list of your test number — add it under "
            "Meta → WhatsApp → API setup, or move the app out of test mode."
        )
    if code == 131047:
        return (
            "the 24-hour customer service window is closed. The recipient has to message "
            "you first, or the text has to be an approved template."
        )
    return ""


async def send_text(
    settings: Settings | None = None,
    *,
    to: str,
    body: str,
    preview_url: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send one text message through the Cloud API. Returns the provider ids."""
    settings = settings or get_settings()
    body = (body or "").strip()
    if not body:
        raise ToolError("the message is empty")
    if len(body) > MAX_BODY:
        raise ToolError(f"the message is {len(body)} characters; WhatsApp allows {MAX_BODY}")

    missing = [
        name.upper()
        for name in ("whatsapp_access_token", "whatsapp_phone_number_id")
        if not getattr(settings, name).strip()
    ]
    if missing:
        raise ToolError(
            "WhatsApp Cloud API is not configured (missing "
            + ", ".join(missing)
            + "). Add the credentials to .env, or set WHATSAPP_MODE=link to hand the "
            "message to WhatsApp instead of sending it directly."
        )

    version = (settings.whatsapp_api_version or "v27.0").strip()
    url = (
        f"{settings.whatsapp_api_base.rstrip('/')}/{version}/"
        f"{settings.whatsapp_phone_number_id.strip()}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": bool(preview_url), "body": body},
    }
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token.strip()}",
        "Content-Type": "application/json",
    }

    own_client = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    response: httpx.Response | None = None
    try:
        for attempt in range(1, 4):
            try:
                response = await http.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                if attempt >= 3:
                    raise ToolError(f"could not reach the WhatsApp API: {exc}") from exc
                await asyncio.sleep(float(attempt))
                continue
            # 429 / 5xx are worth another go; everything else is final.
            if response.status_code != 429 and response.status_code < 500:
                break
            if attempt >= 3:
                break
            await asyncio.sleep(float(attempt) * 1.5)
    finally:
        if own_client:
            await http.aclose()

    assert response is not None
    if response.status_code >= 400:
        try:
            error = (response.json() or {}).get("error") or {}
        except ValueError:
            error = {}
        detail = error.get("error_user_msg") or error.get("message") or (response.text or "")[:300]
        hint = _error_hint(response, error)
        message = f"WhatsApp rejected the message (HTTP {response.status_code}): {detail or 'no detail'}"
        raise ToolError(message + (f" — {hint}" if hint else ""))

    try:
        data = response.json() or {}
    except ValueError:
        data = {}
    sent = (data.get("messages") or [{}])[0]
    contact = (data.get("contacts") or [{}])[0]
    log.info("sent whatsapp message to %s (%s)", mask(to), sent.get("id"))
    return {
        "ok": True,
        "mode": "cloud",
        "to": to,
        "message_id": sent.get("id"),
        "wa_id": contact.get("wa_id"),
    }
