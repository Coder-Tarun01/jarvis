"""Google People API (contacts): request shape, pagination, parsing and matching.

Fully offline — `access_token` is stubbed and the People API is replaced by an
httpx MockTransport, so no credentials and no network are involved.
"""

import asyncio
import os
import sys
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_contacts_test_")
os.environ["DATA_DIR"] = _TEST_DATA
os.environ["WORKSPACE_DIR"] = os.path.join(_TEST_DATA, "workspace")
os.environ["JARVIS_AUTH_TOKEN"] = "test-token"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.errors import ToolError  # noqa: E402
from app.services import google  # noqa: E402
from app.tools.registry import load_tools  # noqa: E402

failures = []


def check(label, condition, extra=""):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


async def _fake_token(settings=None):
    return "test-token"


google.access_token = _fake_token  # skip the OAuth exchange entirely

SETTINGS = Settings(
    google_enabled=True,
    google_client_id="cid",
    google_client_secret="secret",
    google_refresh_token="refresh",
    google_contacts_include_other=True,
)

PAGE_ONE = {
    "connections": [
        {
            "names": [{"displayName": "Ravi Kumar", "metadata": {"primary": True}}],
            "emailAddresses": [{"value": "ravi@example.com"}],
            "phoneNumbers": [{"value": "+91 98765 43210"}],
            "organizations": [{"name": "Acme Ltd"}],
            "photos": [{"url": "https://example.com/avatar.png"}],
        },
        {
            "names": [{"displayName": "Ravi Shankar"}],
            "emailAddresses": [{"value": "rshankar@example.org"}],
        },
        {"emailAddresses": [{"value": "no-name@example.com"}]},
        {"names": [{"displayName": ""}]},  # unusable -> skipped
    ],
    "nextPageToken": "page-2",
}
PAGE_TWO = {
    "connections": [
        {
            "names": [{"displayName": "Priya Nair"}],
            "emailAddresses": [{"value": "priya@example.com"}],
            "organizations": [{"name": "Globex"}],
        }
    ]
}
OTHER = {
    "otherContacts": [
        {"names": [{"displayName": "Dev Patel"}], "emailAddresses": [{"value": "dev@example.net"}]}
    ]
}

seen = []


def handler(request):
    seen.append(request)
    path = request.url.path
    if path.endswith("/people/me/connections"):
        token = request.url.params.get("pageToken")
        return httpx.Response(200, json=PAGE_TWO if token == "page-2" else PAGE_ONE)
    if path.endswith("/otherContacts"):
        return httpx.Response(200, json=OTHER)
    return httpx.Response(404, json={"error": {"message": "not found"}})


async def run_search(**kwargs):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await google.search_contacts(SETTINGS, client=client, **kwargs)


# ------------------------------------------------------------------ parsing
print("--- contact parsing")
contact = google._person_to_contact(PAGE_ONE["connections"][0], "contacts")
check("name parsed", contact["name"] == "Ravi Kumar", contact["name"])
check("email parsed", contact["emails"] == ["ravi@example.com"], str(contact["emails"]))
check("phone parsed", contact["phones"] == ["+91 98765 43210"], str(contact["phones"]))
check("company parsed", contact["org"] == "Acme Ltd", contact["org"])
check("photo parsed", contact["photo"] == "https://example.com/avatar.png", contact["photo"])
check("source tagged", contact["source"] == "contacts")

nameless = google._person_to_contact(PAGE_ONE["connections"][2], "contacts")
check("falls back to the email when there is no name", nameless["name"] == "no-name@example.com")
check("empty person dropped", google._person_to_contact(PAGE_ONE["connections"][3], "contacts") is None)

# ------------------------------------------------------------------ matching
print("\n--- matching")
check("multi-word AND match", google._contact_matches(contact, "ravi kumar"))
check("no false positive on a bad word", not google._contact_matches(contact, "ravi zzz"))
check("matches on company", google._contact_matches(contact, "acme"))
check("matches on phone digits", google._contact_matches(contact, "98765"))
check("empty query matches everything", google._contact_matches(contact, ""))

# ------------------------------------------------------------------ search
print("\n--- search")
seen.clear()
result = asyncio.run(run_search(query="ravi"))
check("two Ravis found", result["count"] == 2, str(result["count"]))
check("names returned", {c["name"] for c in result["contacts"]} == {"Ravi Kumar", "Ravi Shankar"})
paths = [r.url.path for r in seen]
check("connections queried", any(p.endswith("/people/me/connections") for p in paths), str(paths))
check("other contacts queried", any(p.endswith("/otherContacts") for p in paths), str(paths))
check(
    "pagination followed",
    sum(1 for p in paths if p.endswith("/people/me/connections")) == 2,
    str(len(paths)),
)

first = seen[0]
check(
    "personFields sent",
    "names" in (first.url.params.get("personFields") or ""),
    first.url.params.get("personFields"),
)
check(
    "bearer token sent",
    first.headers.get("authorization") == "Bearer test-token",
    first.headers.get("authorization"),
)
other_req = next(r for r in seen if r.url.path.endswith("/otherContacts"))
check("readMask sent for other contacts", "names" in (other_req.url.params.get("readMask") or ""))

print("\n--- sources and limits")
result = asyncio.run(run_search(query="dev"))
check(
    "other contact found",
    result["count"] == 1 and result["contacts"][0]["source"] == "other",
    str(result["contacts"]),
)
result = asyncio.run(run_search(query=""))
check("empty query lists contacts", result["count"] == 5, str(result["count"]))  # 4 saved + 1 other
result = asyncio.run(run_search(query="ravi", max_results=1))
check("max_results respected", result["count"] == 1, str(result["count"]))


# ------------------------------------------------------------------ failures
print("\n--- failures")


def forbidden(request):
    if request.url.path.endswith("/otherContacts"):
        return httpx.Response(403, json={"error": {"message": "insufficient scope"}})
    return httpx.Response(200, json=PAGE_TWO)


async def run_forbidden():
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        return await google.search_contacts(SETTINGS, query="priya", client=client)


result = asyncio.run(run_forbidden())
check("missing otherContacts scope is tolerated", result["count"] == 1, str(result["count"]))

try:
    asyncio.run(google.search_contacts(Settings(google_enabled=False), query="x"))
    check("disabled integration refuses", False)
except ToolError as exc:
    check("disabled integration refuses", "GOOGLE_ENABLED" in str(exc), str(exc)[:80])

print("\n--- registry")
tools = load_tools()
check("google_contacts_search registered", "google_contacts_search" in tools)
check("google_contacts_sync registered", "google_contacts_sync" in tools)
sync_tool = tools.get("google_contacts_sync")
check("contacts sync is read-only/local", bool(sync_tool and sync_tool.requires_confirmation is False))
tool = tools.get("google_contacts_search")
check("contacts search is read-only", bool(tool and tool.requires_confirmation is False))
check(
    "schema is an object",
    (tool.schema()["input_schema"].get("type") == "object") if tool else False,
)

print("")
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("all google-contacts checks passed")
