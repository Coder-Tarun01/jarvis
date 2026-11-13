"""Google Calendar, Gmail and Contacts, off by default.

We call the REST endpoints directly with a refresh token, so there is no
google-api-python-client dependency to keep in sync. Enable in .env:

    GOOGLE_ENABLED=true
    GOOGLE_CLIENT_ID=...        (OAuth client, type "Desktop app")
    GOOGLE_CLIENT_SECRET=...
    GOOGLE_REFRESH_TOKEN=...    (see README "Google integrations")

Scopes: calendar.readonly, gmail.readonly, gmail.compose (drafts only),
contacts.readonly and contacts.other.readonly (contacts are read-only).
"""

from __future__ import annotations

import base64
import time
from datetime import timedelta
from email.message import EmailMessage
from typing import Any

import httpx

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from ..core.utils import retry_async, utcnow

log = get_logger("google")

TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
PEOPLE_API = "https://people.googleapis.com/v1"
TIMEOUT = httpx.Timeout(25.0, connect=10.0)

# Person fields requested from the People API; keep the list tight, each one costs quota.
CONTACT_FIELDS = "names,emailAddresses,phoneNumbers,organizations,photos"
OTHER_CONTACT_FIELDS = "names,emailAddresses,phoneNumbers"
CONTACTS_PAGE_SIZE = 500
CONTACTS_MAX_PAGES = 4


_token_cache: dict[str, Any] = {"value": None, "expires_at": 0.0}


def require_configured(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    if not settings.google_enabled:
        raise ToolError(
            "Google integration is disabled. Set GOOGLE_ENABLED=true and the GOOGLE_* "
            "credentials in .env (see README → Google integrations)."
        )
    missing = [
        name
        for name in ("google_client_id", "google_client_secret", "google_refresh_token")
        if not getattr(settings, name)
    ]
    if missing:
        raise ToolError(
            "Google integration is enabled but missing: " + ", ".join(m.upper() for m in missing)
        )
    return settings


async def access_token(settings: Settings | None = None) -> str:
    settings = require_configured(settings)
    now = time.time()
    if _token_cache["value"] and float(_token_cache["expires_at"]) > now + 60:
        return str(_token_cache["value"])

    payload = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": settings.google_refresh_token,
        "grant_type": "refresh_token",
    }

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.post(TOKEN_URL, data=payload)

    response = await retry_async(call, attempts=3, label="google.token", retry_on=(httpx.HTTPError,))
    if response.status_code >= 400:
        raise ToolError(
            f"Google token refresh failed (HTTP {response.status_code}). "
            "The refresh token may be revoked — re-run the OAuth helper from the README."
        )
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise ToolError("Google did not return an access token")
    _token_cache["value"] = token
    _token_cache["expires_at"] = now + float(data.get("expires_in", 3500))
    return token


async def _get(
    url: str,
    params: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    token = await access_token()
    headers = {"Authorization": f"Bearer {token}"}

    async def call() -> httpx.Response:
        if client is not None:  # injected transport (tests, proxies)
            return await client.get(url, params=params, headers=headers)
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as http:
            return await http.get(url, params=params)

    response = await retry_async(call, attempts=3, label="google.get", retry_on=(httpx.HTTPError,))
    if response.status_code >= 400:
        raise ToolError(f"Google API error (HTTP {response.status_code}): {response.text[:300]}")
    return response.json()


async def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = await access_token()

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}"}) as client:
            return await client.post(url, json=payload)

    response = await retry_async(call, attempts=3, label="google.post", retry_on=(httpx.HTTPError,))
    if response.status_code >= 400:
        raise ToolError(f"Google API error (HTTP {response.status_code}): {response.text[:300]}")
    return response.json()


# --------------------------------------------------------------------------- calendar
def _event_start(event: dict[str, Any]) -> str:
    start = event.get("start") or {}
    return start.get("dateTime") or start.get("date") or ""


async def list_calendar_events(
    settings: Settings | None = None,
    *,
    max_results: int = 10,
    days_ahead: int = 7,
) -> dict[str, Any]:
    settings = require_configured(settings)
    now = utcnow()
    params = {
        "timeMin": now.replace(microsecond=0).isoformat() + "Z",
        "timeMax": (now + timedelta(days=max(1, min(days_ahead, 60)))).replace(microsecond=0).isoformat() + "Z",
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max(1, min(max_results, 50)),
        "timeZone": settings.google_timezone or "UTC",
    }
    url = f"{CALENDAR_API}/calendars/{settings.google_calendar_id or 'primary'}/events"
    data = await _get(url, params)

    events = []
    for item in data.get("items", []):
        events.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary") or "(no title)",
                "start": _event_start(item),
                "end": (item.get("end") or {}).get("dateTime")
                or (item.get("end") or {}).get("date", ""),
                "location": item.get("location") or "",
                "attendees": [a.get("email") for a in item.get("attendees", []) if a.get("email")],
                "link": item.get("htmlLink"),
            }
        )
    return {"calendar": settings.google_calendar_id, "count": len(events), "events": events}


# --------------------------------------------------------------------------- gmail
def _header(payload: dict[str, Any], name: str) -> str:
    for header in payload.get("headers", []):
        if (header.get("name") or "").lower() == name.lower():
            return header.get("value") or ""
    return ""


async def list_gmail_messages(
    settings: Settings | None = None,
    *,
    query: str = "",
    max_results: int = 10,
) -> dict[str, Any]:
    require_configured(settings)
    params: dict[str, Any] = {"maxResults": max(1, min(max_results, 25))}
    if query:
        params["q"] = query
    listing = await _get(f"{GMAIL_API}/messages", params)

    messages = []
    for ref in listing.get("messages", []):
        message_id = ref.get("id")
        if not message_id:
            continue
        detail = await _get(
            f"{GMAIL_API}/messages/{message_id}",
            {
                "format": "metadata",
                "metadataHeaders": ["Subject", "From", "Date"],
            },
        )
        payload = detail.get("payload", {})
        messages.append(
            {
                "id": message_id,
                "thread_id": detail.get("threadId"),
                "from": _header(payload, "From"),
                "subject": _header(payload, "Subject"),
                "date": _header(payload, "Date"),
                "snippet": detail.get("snippet", ""),
            }
        )
    return {"query": query, "count": len(messages), "messages": messages}


async def create_gmail_draft(
    settings: Settings | None = None,
    *,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
) -> dict[str, Any]:
    """Creates a draft only — nothing is sent until the user presses send in Gmail."""
    require_configured(settings)
    if not to.strip():
        raise ToolError("a draft needs a recipient address")

    message = EmailMessage()
    message["To"] = to.strip()
    if cc:
        message["Cc"] = cc.strip()
    message["Subject"] = subject or "(no subject)"
    message.set_content(body or "")

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = await _post(f"{GMAIL_API}/drafts", {"message": {"raw": raw}})
    return {
        "ok": True,
        "draft_id": result.get("id"),
        "message_id": (result.get("message") or {}).get("id"),
        "to": to,
        "subject": message["Subject"],
    }


# --------------------------------------------------------------------------- contacts
def _person_to_contact(person: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Flatten a People API person into the shape the assistant talks about."""
    names = person.get("names") or []
    name = ""
    for item in names:
        if item.get("displayName"):
            name = str(item["displayName"]).strip()
            if (item.get("metadata") or {}).get("primary"):
                break

    emails = [str(e["value"]) for e in person.get("emailAddresses") or [] if e.get("value")]
    phones = [str(p["value"]) for p in person.get("phoneNumbers") or [] if p.get("value")]
    orgs = person.get("organizations") or []
    org = str(orgs[0].get("name") or "").strip() if orgs else ""

    photo = ""
    for item in person.get("photos") or []:
        if item.get("url"):
            photo = str(item["url"])
            if not item.get("default"):
                break

    label = name or (emails[0] if emails else (phones[0] if phones else ""))
    if not label:
        return None
    return {
        "name": label,
        "emails": emails,
        "phones": phones,
        "org": org,
        "photo": photo,
        "source": source,
    }


def _contact_matches(contact: dict[str, Any], needle: str) -> bool:
    """Every word of the query must appear somewhere in the contact."""
    if not needle:
        return True
    haystack = " ".join(
        [contact["name"], contact["org"], *contact["emails"], *contact["phones"]]
    ).lower()
    return all(word in haystack for word in needle.split())


async def _list_connections(
    max_results: int,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Saved contacts (People → Contacts)."""
    found: list[dict[str, Any]] = []
    page_token: str | None = None

    for _ in range(CONTACTS_MAX_PAGES):
        params: dict[str, Any] = {
            "personFields": CONTACT_FIELDS,
            "pageSize": CONTACTS_PAGE_SIZE,
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _get(f"{PEOPLE_API}/people/me/connections", params, client=client)
        for person in data.get("connections") or []:
            contact = _person_to_contact(person, "contacts")
            if contact:
                found.append(contact)
        page_token = data.get("nextPageToken")
        if not page_token or len(found) >= max_results:
            break
    return found


async def _list_other_contacts(
    max_results: int,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Auto-collected "other contacts" (people you have emailed).

    Needs the contacts.other.readonly scope; when it is missing the API answers
    403 and we simply skip this source instead of failing the whole search.
    """
    try:
        data = await _get(
            f"{PEOPLE_API}/otherContacts",
            {"readMask": OTHER_CONTACT_FIELDS, "pageSize": min(max_results, 500)},
            client=client,
        )
    except ToolError as exc:
        log.info("otherContacts unavailable (%s) — contacts scope only", exc)
        return []

    found: list[dict[str, Any]] = []
    for person in data.get("otherContacts") or []:
        contact = _person_to_contact(person, "other")
        if contact:
            found.append(contact)
    return found


async def search_contacts(
    settings: Settings | None = None,
    *,
    query: str = "",
    max_results: int = 20,
    include_other: bool | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Search the user's Google contacts by name, email, phone or company."""
    settings = require_configured(settings)
    limit = max(1, min(int(max_results or 20), 50))
    needle = " ".join((query or "").split()).lower()
    with_other = settings.google_contacts_include_other if include_other is None else include_other

    # Read enough to find matches, then filter locally (the People API has no
    # server-side text search for contacts).
    scan = min(CONTACTS_PAGE_SIZE * CONTACTS_MAX_PAGES, max(limit * 10, 200))
    people = await _list_connections(scan, client=client)
    if with_other:
        people += await _list_other_contacts(scan, client=client)

    seen: set[tuple[str, str]] = set()
    matches: list[dict[str, Any]] = []
    for contact in people:
        key = (contact["name"].lower(), contact["emails"][0].lower() if contact["emails"] else "")
        if key in seen:
            continue
        seen.add(key)
        if _contact_matches(contact, needle):
            matches.append(contact)

    return {
        "query": query,
        "count": len(matches[:limit]),
        "scanned": len(people),
        "contacts": matches[:limit],
    }


async def fetch_all_contacts(
    settings: Settings | None = None,
    *,
    include_other: bool | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Every contact that has a phone number (for the local WhatsApp cache)."""
    settings = require_configured(settings)
    with_other = settings.google_contacts_include_other if include_other is None else include_other

    scan = CONTACTS_PAGE_SIZE * CONTACTS_MAX_PAGES
    people = await _list_connections(scan, client=client)
    if with_other:
        people += await _list_other_contacts(scan, client=client)

    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for contact in people:
        if not contact.get("phones"):
            continue
        key = (contact["name"].lower(), contact["phones"][0].lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(contact)
    return result
