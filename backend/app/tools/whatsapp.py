"""WhatsApp messaging tools.

``whatsapp_send_message`` has two delivery paths (see ``services/whatsapp.py``):

* ``link`` (default) — resolve the name to a number, then hand the composed text to
  the WhatsApp desktop app through a ``whatsapp://send?phone=…&text=…`` URI, which
  opens that exact chat with the message pre-filled. No credentials needed.
* ``cloud`` — real sends through Meta's Cloud API.

Names resolve from ``WHATSAPP_CONTACTS`` and the live alias file
(``data/whatsapp_aliases.json``), then the local Google contacts cache
(``data/contacts_cache.json``), then one live People API query whose result is
written back to the cache — so a name is enough, no phone number required.
``whatsapp_import_contacts`` fills the alias file in bulk.
"""

from __future__ import annotations

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from ..services import contacts_cache, whatsapp, whatsapp_aliases, whatsapp_import
from .base import Tool, ToolContext
from .desktop_apps import _bridge_call

log = get_logger("tools.whatsapp")


def _settings_of(ctx: ToolContext) -> Settings:
    return ctx.settings or get_settings()


def _mode_hint(settings: Settings) -> str:
    mode = settings.whatsapp_effective_mode
    if mode == "cloud":
        return "Send a WhatsApp message for real through the Cloud API"
    if mode == "link":
        return (
            "Compose a WhatsApp message and open that exact chat in WhatsApp with the text "
            "pre-filled; the user presses send"
        )
    return "Send a WhatsApp message (disabled — WHATSAPP_ENABLED is false)"


async def whatsapp_send_message(
    ctx: ToolContext,
    to: str,
    message: str,
    preview_url: bool = False,
) -> dict:
    settings = _settings_of(ctx)
    mode = settings.whatsapp_effective_mode
    if mode == "off":
        raise ToolError(
            "WhatsApp sending is disabled. Set WHATSAPP_ENABLED=true in .env and restart "
            "the backend (WHATSAPP_MODE=link needs no credentials at all)."
        )

    # Name -> number: WHATSAPP_CONTACTS + live aliases, then the Google contacts
    # cache, then one live People API lookup (whose result is written back).
    # A "Name=+number" recipient is saved as an alias first, so the shorthand also
    # teaches JARVIS the mapping for next time.
    recipient = (to or "").strip()
    alias_saved = None
    if "=" in recipient:
        alias_name, _, alias_number = recipient.partition("=")
        alias_name, alias_number = alias_name.strip(), alias_number.strip()
        if alias_name and alias_number:
            alias_saved = whatsapp_aliases.save(settings, name=alias_name, number=alias_number)
            recipient = alias_name

    number, label, source = await whatsapp.resolve_recipient_async(settings, recipient)

    body = (message or "").strip()
    if not body:
        raise ToolError("the message is empty — say what I should write")
    if len(body) > whatsapp.MAX_BODY:
        raise ToolError(f"that message is {len(body)} characters; WhatsApp allows {whatsapp.MAX_BODY}")

    if mode == "cloud":
        result = await whatsapp.send_text(
            settings, to=number, body=body, preview_url=bool(preview_url)
        )
        result.update(
            {
                "contact": label,
                "message": f"sent a WhatsApp message to {label}",
            }
        )
        return result

    # link mode: hand the composed text to the WhatsApp desktop app itself
    uri = whatsapp.chat_link(number, body)
    autosend = bool(settings.whatsapp_autosend)
    delay_ms = max(0, int(settings.whatsapp_autosend_delay_ms or 0))
    relayed = False
    auto_sent = False
    bridge_note = ""

    if settings.apps_bridge_enabled:
        # The host can ShellExecute the URI directly (browsers refuse custom
        # schemes opened from a websocket event) and, when autosend is on, press
        # Enter once WhatsApp is verifiably in the foreground.
        budget = float(settings.apps_bridge_timeout)
        if autosend:
            budget = max(budget, delay_ms / 1000.0 + 8.0)
        try:
            reply = await _bridge_call(
                settings,
                "open-uri",
                uri=uri,
                press_enter=autosend,
                delay_ms=delay_ms if autosend else 0,
                timeout=budget,
            )
            relayed = bool(reply.get("ok") or reply.get("opened"))
            auto_sent = bool(reply.get("enter_sent"))
            bridge_note = str(reply.get("message") or "")
            if not relayed:
                log.warning("bridge refused the whatsapp uri: %s", bridge_note)
        except ToolError as exc:
            log.warning("bridge could not open the whatsapp uri: %s", exc)

    log.info(
        "whatsapp %s to %s (%s, via %s)",
        "sent" if auto_sent else "hand-off",
        whatsapp.mask(number),
        source,
        "bridge" if relayed else "browser",
    )

    if auto_sent:
        message = f"sent {label} the message on WhatsApp"
    elif autosend and relayed:
        message = (
            f"opened the chat with {label} with the text filled in, but could not "
            f"auto-send ({bridge_note or 'WhatsApp was not in the foreground'}) — press send"
        )
    else:
        message = (
            f"opened the WhatsApp chat with {label} and the text filled in — "
            "press send in WhatsApp to deliver it"
        )

    result = {
        "ok": True,
        "mode": "link",
        "to": number,
        "contact": label,
        "resolved_from": source,
        "opened": uri,
        "delivered_via": "bridge" if relayed else "browser",
        "auto_sent": auto_sent,
        "web_fallback": whatsapp.web_link(number, body),
        "message": message,
    }
    if alias_saved:
        result["alias_saved"] = alias_saved["name"]
        message = f"{message} (saved '{alias_saved['name']}' as an alias)"
        result["message"] = message
    if not relayed:
        # no host bridge: let the browser hand the URI to the app instead
        result["client_action"] = {"action": "open_url", "url": uri}
    return result


def whatsapp_save_contact(
    ctx: ToolContext,
    name: str,
    number: str = "",
    remove: bool = False,
) -> dict:
    """Add, update or remove a runtime alias (no restart needed)."""
    settings = _settings_of(ctx)
    clean = (name or "").strip()
    if not clean:
        raise ToolError("which name should I save?")

    if remove:
        removed = whatsapp_aliases.remove(settings, name=clean)
        return {
            "ok": removed,
            "removed": removed,
            "name": clean,
            "path": str(settings.whatsapp_aliases_path),
            "message": (
                f"removed the alias '{clean}'"
                if removed
                else f"'{clean}' was not in the alias file"
            ),
        }

    value = (number or "").strip()
    if not value:
        raise ToolError("give me the phone number to store, e.g. '+91 98765 43210'")
    digits = whatsapp.normalise_number(value, settings.whatsapp_country_code)
    saved = whatsapp_aliases.save(settings, name=clean, number=value)
    return {
        "ok": True,
        "name": saved["name"],
        "number": whatsapp.mask(digits),
        "count": saved["count"],
        "path": str(settings.whatsapp_aliases_path),
        "message": (
            f"saved '{saved['name']}' -> {whatsapp.mask(digits)}; "
            "messages to that name now resolve automatically"
        ),
    }


def whatsapp_import_contacts(
    ctx: ToolContext,
    text: str = "",
    source: str = "auto",
    overwrite: bool = False,
    dry_run: bool = False,
    limit: int = 0,
) -> dict:
    """Bulk-load name -> number pairs into the live alias file."""
    settings = _settings_of(ctx)
    summary = whatsapp_import.run(
        settings,
        text=text,
        source=source,
        overwrite=bool(overwrite),
        dry_run=bool(dry_run),
        limit=max(0, int(limit or 0)),
    )
    summary["path"] = str(settings.whatsapp_aliases_path)
    return summary


def whatsapp_list_contacts(ctx: ToolContext) -> dict:
    settings = _settings_of(ctx)
    book = whatsapp.contacts(settings)
    cache = contacts_cache.load(settings)
    mode = settings.whatsapp_effective_mode
    people = [
        {"name": name, "number": whatsapp.mask(number), "source": "alias"}
        for name, number in sorted(book.items())
    ]
    cached = [
        {"name": item["name"], "number": whatsapp.mask(item["phones"][0]), "source": cache["source"]}
        for item in cache["contacts"][:50]
    ]
    return {
        "ok": True,
        "mode": mode,
        "count": len(people) + len(cached),
        "contacts": people + cached,
        "cache": {
            "path": str(settings.contacts_cache_path),
            "count": cache["count"],
            "updated_at": cache["updated_at"],
        },
        "message": (
            f"{len(people)} configured + {cache['count']} cached contact(s); mode={mode}"
            if (people or cached)
            else "no WhatsApp contacts yet — add 'name=+countrynumber' pairs to "
            "WHATSAPP_CONTACTS or run google_contacts_sync"
        ),
    }


TOOLS = [
    Tool(
        name="whatsapp_send_message",
        description=(
            _mode_hint(get_settings()) + ". External effect — needs confirmation"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": (
                        "Contact name (resolved from WHATSAPP_CONTACTS, saved aliases, Google "
                        "contacts cache or Google Contacts), a phone number with country code, "
                        "or 'Name=+number' to save a new alias and message it in one go"
                    ),
                },
                "message": {
                    "type": "string",
                    "description": f"Plain-text body, max {whatsapp.MAX_BODY} characters",
                },
                "preview_url": {
                    "type": "boolean",
                    "description": "Ask WhatsApp to render a link preview for the first URL",
                    "default": False,
                },
            },
            "required": ["to", "message"],
        },
        handler=whatsapp_send_message,
        requires_confirmation=True,
        confirmation_hint="This sends a WhatsApp message from your account.",
    ),
    Tool(
        name="whatsapp_save_contact",
        description=(
            "Save (or remove) a WhatsApp name -> number alias in data/whatsapp_aliases.json "
            "so that name resolves automatically from now on. No restart needed"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "How the person is addressed, e.g. 'Prashant Frd'"},
                "number": {
                    "type": "string",
                    "description": "Phone number with country code, e.g. '+91 98765 43210' (omit when removing)",
                },
                "remove": {
                    "type": "boolean",
                    "description": "Delete the alias instead of saving it",
                    "default": False,
                },
            },
            "required": ["name"],
        },
        handler=whatsapp_save_contact,
    ),
    Tool(
        name="whatsapp_import_contacts",
        description=(
            "Bulk-load WhatsApp name -> number aliases into data/whatsapp_aliases.json. "
            "source='contacts' imports every Google contact that has a phone number from "
            "the local cache; source='text' parses a pasted/exported list "
            "('Name=+91 98765 43210', CSV, TSV, vCard or JSON). Existing aliases are kept "
            "unless overwrite=true, so a hand-written alias always wins"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["auto", "contacts", "text"],
                    "description": (
                        "'contacts' = the Google contacts cache, 'text' = use the pasted "
                        "list, 'auto' = text when given, else contacts"
                    ),
                    "default": "auto",
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Contacts to import, one per line — 'Prashant Frd=+91 98765 43210', "
                        "'Prashant Frd,+91…', a tab-separated export, vCard or JSON"
                    ),
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace an existing alias whose number differs (default keeps it)",
                    "default": False,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Report what would change without writing the file",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 2000,
                    "description": "Import at most this many contacts (0 = all)",
                    "default": 0,
                },
            },
            "additionalProperties": False,
        },
        handler=whatsapp_import_contacts,
    ),
    Tool(
        name="whatsapp_list_contacts",
        description="List the WhatsApp contacts JARVIS may message (numbers masked)",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=whatsapp_list_contacts,
    ),
]
