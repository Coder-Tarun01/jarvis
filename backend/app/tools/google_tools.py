"""Google Calendar + Gmail tools. Off by default; see services/google.py for setup."""

from __future__ import annotations

from ..core.config import get_settings
from ..services import contacts_cache, google
from .base import Tool, ToolContext


async def calendar_events(ctx: ToolContext, max_results: int = 10, days_ahead: int = 7) -> dict:
    settings = ctx.settings or get_settings()
    return await google.list_calendar_events(
        settings, max_results=int(max_results or 10), days_ahead=int(days_ahead or 7)
    )


async def gmail_search(ctx: ToolContext, query: str = "", max_results: int = 10) -> dict:
    settings = ctx.settings or get_settings()
    return await google.list_gmail_messages(
        settings, query=(query or ""), max_results=int(max_results or 10)
    )


async def gmail_create_draft(ctx: ToolContext, to: str, subject: str, body: str) -> dict:
    settings = ctx.settings or get_settings()
    return await google.create_gmail_draft(settings, to=to, subject=subject, body=body)


async def contacts_search(ctx: ToolContext, query: str = "", max_results: int = 20) -> dict:
    settings = ctx.settings or get_settings()
    return await google.search_contacts(
        settings, query=(query or ""), max_results=int(max_results or 20)
    )


async def contacts_sync(ctx: ToolContext) -> dict:
    """Mirror Google Contacts into data/contacts_cache.json for WhatsApp lookups."""
    settings = ctx.settings or get_settings()
    people = await google.fetch_all_contacts(settings)
    payload = contacts_cache.save(settings, people, source="google")
    return {
        "ok": True,
        "count": payload["count"],
        "updated_at": payload["updated_at"],
        "path": str(settings.contacts_cache_path),
        "message": (
            f"cached {payload['count']} contact(s) with a phone number — "
            "names now resolve to numbers without a network call"
        ),
    }


TOOLS = [
    Tool(
        name="google_calendar_events",
        description="List upcoming Google Calendar events (requires GOOGLE_ENABLED)",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "days_ahead": {"type": "integer", "minimum": 1, "maximum": 60, "default": 7},
            },
        },
        handler=calendar_events,
    ),
    Tool(
        name="google_gmail_search",
        description="Search the user's Gmail inbox (read-only, requires GOOGLE_ENABLED)",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search syntax, e.g. 'from:alice is:unread newer_than:7d'",
                },
                "max_results": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
            },
        },
        handler=gmail_search,
    ),
    Tool(
        name="google_gmail_create_draft",
        description=(
            "Create (never send) a Gmail draft for the user to review"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain-text body"},
            },
            "required": ["to", "subject", "body"],
        },
        handler=gmail_create_draft,
        requires_confirmation=False,
    ),
    Tool(
        name="google_contacts_search",
        description=(
            "Search the user's Google contacts and return names, emails and phone numbers "
            "(read-only, requires GOOGLE_ENABLED). Pass an empty query to list the first few"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name, email, phone fragment or company, e.g. 'ravi' or 'acme'",
                },
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
        },
        handler=contacts_search,
    ),
    Tool(
        name="google_contacts_sync",
        description=(
            "Refresh the local contacts cache (data/contacts_cache.json) from Google "
            "Contacts so WhatsApp name lookups resolve offline"
        ),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=contacts_sync,
    ),
]
