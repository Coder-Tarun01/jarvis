"""WhatsApp tools: number normalisation, contact lookup and both delivery paths.

Fully offline — the Cloud API is exercised through an httpx MockTransport, so no
token, no network and above all no real message is ever sent.
"""

import asyncio
import json
import os
import sys
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="jarvis_wa_test_")
os.environ["DATA_DIR"] = _TEST_DATA
os.environ["WORKSPACE_DIR"] = os.path.join(_TEST_DATA, "workspace")
os.environ["JARVIS_AUTH_TOKEN"] = "test-token"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.errors import ToolError  # noqa: E402
from app.services import contacts_cache, google, whatsapp  # noqa: E402
from app.tools import whatsapp as wa_tools  # noqa: E402
from app.tools.base import ToolContext  # noqa: E402
from app.tools.registry import load_tools  # noqa: E402

failures = []


def check(label, condition, extra=""):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


def make_settings(**overrides):
    """Settings pinned per-test, independent of the project .env."""
    base = {
        "whatsapp_enabled": True,
        "whatsapp_mode": "auto",
        "whatsapp_contacts": "",
        "whatsapp_country_code": "",
        "whatsapp_access_token": "",
        "whatsapp_phone_number_id": "",
        # keep the tests away from the real data/contacts_cache.json
        "whatsapp_contacts_cache": os.path.join(_TEST_DATA, "contacts_cache.json"),
        # ...and from the real alias file the user maintains
        "whatsapp_aliases": os.path.join(_TEST_DATA, "whatsapp_aliases.json"),
        # unit tests exercise the browser fallback; the live E2E covers the bridge
        "apps_bridge_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def ctx_for(settings):
    return ToolContext(db=None, settings=settings)


# ------------------------------------------------------------------ numbers
print("--- number normalisation")
cases = [
    ("+91 98765 43210", "", "919876543210"),
    ("+1 (650) 555-1234", "", "16505551234"),
    ("0091 98765 43210", "", "919876543210"),
    ("9876543210", "91", "919876543210"),
    ("+44 7700 900123", "", "447700900123"),
]
for raw, code, want in cases:
    got = whatsapp.normalise_number(raw, code)
    check(f"normalise {raw!r} -> {want}", got == want, f"(got {got})")

for bad in ("", "not-a-number", "+12"):
    try:
        whatsapp.normalise_number(bad)
        check(f"reject {bad!r}", False)
    except ToolError as exc:
        check(f"reject {bad!r}", True, str(exc)[:60])

check("mask hides the middle", whatsapp.mask("919876543210") == "+********3210", whatsapp.mask("919876543210"))


# ------------------------------------------------------------------ modes
print("\n--- mode resolution")
check("auto + no creds -> link", make_settings().whatsapp_effective_mode == "link")
check(
    "auto + creds -> cloud",
    make_settings(
        whatsapp_access_token="tok", whatsapp_phone_number_id="123456"
    ).whatsapp_effective_mode
    == "cloud",
)
check(
    "cloud + no creds stays cloud (so the error can name the variable)",
    make_settings(whatsapp_mode="cloud").whatsapp_effective_mode == "cloud",
)
check("link forces the hand-off", make_settings(whatsapp_mode="link").whatsapp_effective_mode == "link")
check("disabled -> off", make_settings(whatsapp_enabled=False).whatsapp_effective_mode == "off")
check("mode=off -> off", make_settings(whatsapp_mode="off").whatsapp_effective_mode == "off")

# ------------------------------------------------------------------ contacts
print("\n--- contacts")
settings = make_settings(
    whatsapp_contacts="Mom=+91 98765 43210;Ravi Kumar=0091 99887 76655;bad=junk",
    whatsapp_country_code="91",
)
book = whatsapp.contacts(settings)
check("book parses pairs", set(book) == {"mom", "ravi kumar"}, str(sorted(book)))
check("book normalises numbers", book.get("ravi kumar") == "919988776655", str(book))
check("junk entry skipped", "bad" not in book)

check("exact alias", whatsapp.resolve_recipient(settings, "Mom")[1] == "mom")
check("case/space insensitive", whatsapp.resolve_recipient(settings, "  MOM ")[0] == "919876543210")
check("prefix match 'ravi'", whatsapp.resolve_recipient(settings, "ravi")[1] == "ravi kumar")
check(
    "raw number with country code",
    whatsapp.resolve_recipient(settings, "+44 7700 900123")[0] == "447700900123",
)
check(
    "spaced number is still a number",
    whatsapp.resolve_recipient(settings, "+91 99999 99999")[0] == "919999999999",
    str(whatsapp.resolve_recipient(settings, "+91 99999 99999")),
)
check(
    "local number uses WHATSAPP_COUNTRY_CODE",
    whatsapp.resolve_recipient(settings, "9988776655")[0] == "919988776655",
)
check(
    "already-prefixed number is not double-prefixed",
    whatsapp.normalise_number("919876543210", "91") == "919876543210",
    whatsapp.normalise_number("919876543210", "91"),
)
check(
    "long number without '+' is left alone",
    whatsapp.normalise_number("16505551234", "91") == "16505551234",
    whatsapp.normalise_number("16505551234", "91"),
)
try:
    whatsapp.resolve_recipient(settings, "Priya")
    check("unknown name rejected", False)
except ToolError as exc:
    check("unknown name rejected", "WHATSAPP_CONTACTS" in str(exc), str(exc)[:80])
try:
    whatsapp.resolve_recipient(settings, "")
    check("empty recipient rejected", False)
except ToolError:
    check("empty recipient rejected", True)

ambiguous = make_settings(whatsapp_contacts="ravi=+919000000001;ravi kumar=+919000000002")
try:
    whatsapp.resolve_recipient(ambiguous, "rav")
    check("ambiguous prefix rejected", False)
except ToolError as exc:
    check("ambiguous prefix rejected", "several contacts" in str(exc), str(exc)[:80])

# ------------------------------------------------------------------ link mode
print("\n--- link hand-off")
settings = make_settings(whatsapp_contacts="Mom=+91 98765 43210")
result = asyncio.run(
    wa_tools.whatsapp_send_message(ctx_for(settings), to="Mom", message="Dinner at 8?")
)
check("link mode used", result.get("mode") == "link", str(result.get("mode")))
check("resolved contact", result.get("contact") == "mom", str(result.get("contact")))
check("number normalised", result.get("to") == "919876543210", str(result.get("to")))
check("client_action present", isinstance(result.get("client_action"), dict))
url = (result.get("client_action") or {}).get("url", "")
check(
    "whatsapp:// deep link",
    url.startswith("whatsapp://send?phone=919876543210&text="),
    url[:64],
)
check("body url-encoded", "Dinner%20at%208" in url, url[-40:])
check(
    "wa.me fallback kept",
    str(result.get("web_fallback", "")).startswith("https://wa.me/919876543210?text="),
    str(result.get("web_fallback"))[:60],
)
check(
    "browser fallback when no bridge",
    result.get("delivered_via") == "browser",
    str(result.get("delivered_via")),
)
check("message explains the hand-off", "press send" in result.get("message", ""), result.get("message"))

listing = wa_tools.whatsapp_list_contacts(ctx_for(settings))
masked = (listing.get("contacts") or [{}])[0].get("number", "")
check("contacts listed", listing.get("count") == 1, str(listing))
check("numbers masked in list", masked.startswith("+") and "*" in masked, masked)

# ------------------------------------------------------------------ contacts cache
print("\n--- google contacts cache (data/contacts_cache.json)")
cache_settings = make_settings(whatsapp_country_code="91")
payload = contacts_cache.save(
    cache_settings,
    [
        {"name": "Gowri Akka", "phones": ["+91 90592 94845"], "emails": []},
        {"name": "Devi Akka", "phones": ["75696 81708"]},
        {"name": "Devi Akka B", "phones": ["+91 95157 44337"]},
        {"name": "No Phone Person", "phones": []},  # dropped: nothing to dial
    ],
    source="google",
)
check("cache written", payload["count"] == 3, str(payload["count"]))
check("cache file exists", os.path.exists(str(cache_settings.contacts_cache_path)))
check(
    "phone-less contact skipped",
    all(c["name"] != "No Phone Person" for c in contacts_cache.load(cache_settings)["contacts"]),
)
check(
    "exact name resolves from cache",
    whatsapp.resolve_recipient(cache_settings, "Gowri Akka") == ("919059294845", "Gowri Akka"),
    str(whatsapp.resolve_recipient(cache_settings, "Gowri Akka")),
)
check(
    "prefix resolves from cache",
    whatsapp.resolve_recipient(cache_settings, "Gowri")[0] == "919059294845",
)
check(
    "bare local number gets the country code",
    whatsapp.resolve_recipient(cache_settings, "Devi Akka")[0] == "917569681708",
    whatsapp.resolve_recipient(cache_settings, "Devi Akka")[0],
)
try:
    whatsapp.resolve_recipient(cache_settings, "Devi")
    check("ambiguous cache match rejected", False)
except ToolError as exc:
    check("ambiguous cache match rejected", "several" in str(exc), str(exc)[:80])

precedence = make_settings(
    whatsapp_contacts="gowri akka=+919000000001",
    whatsapp_contacts_cache=str(cache_settings.contacts_cache_path),
)
check(
    "WHATSAPP_CONTACTS wins over the cache",
    whatsapp.resolve_recipient(precedence, "Gowri Akka")[0] == "919000000001",
)

print("\n--- live Google fallback")
CALLS = []


async def fake_search(settings=None, *, query="", max_results=20, **_kwargs):
    CALLS.append(query)
    return {
        "query": query,
        "count": 1,
        "scanned": 1,
        "contacts": [
            {
                "name": "Priya Nair",
                "emails": ["priya@example.com"],
                "phones": ["+91 99001 12233"],
                "org": "Globex",
                "photo": "",
                "source": "contacts",
            }
        ],
    }


original_search = google.search_contacts
google.search_contacts = fake_search
try:
    number, label, source = asyncio.run(
        whatsapp.resolve_recipient_async(cache_settings, "Priya")
    )
finally:
    google.search_contacts = original_search

check("google fallback resolves", number == "919900112233", number)
check("label from google", label == "Priya Nair", label)
check("source reported as google", source == "google", source)
check("live lookup was queried", CALLS == ["Priya"], str(CALLS))
check(
    "google hit remembered in the cache",
    whatsapp.resolve_recipient(cache_settings, "Priya Nair")[0] == "919900112233",
)

print("\n--- auto-send through the bridge")
BRIDGE_CALLS = []


async def fake_bridge(settings, action, **kwargs):
    BRIDGE_CALLS.append((action, kwargs))
    return {
        "ok": True,
        "opened": True,
        "enter_sent": True,
        "message": "opened whatsapp link and pressed Enter in 'WhatsApp'",
    }


autosend_settings = make_settings(
    whatsapp_contacts="Gowri=+919059294845",
    apps_bridge_enabled=True,
    whatsapp_autosend=True,
    whatsapp_autosend_delay_ms=2000,
)
original_bridge = wa_tools._bridge_call
wa_tools._bridge_call = fake_bridge
try:
    sent = asyncio.run(
        wa_tools.whatsapp_send_message(ctx_for(autosend_settings), to="Gowri", message="on my way")
    )
finally:
    wa_tools._bridge_call = original_bridge

check("bridge asked to open the uri", BRIDGE_CALLS and BRIDGE_CALLS[0][0] == "open-uri", str(BRIDGE_CALLS[:1]))
check("press_enter requested", BRIDGE_CALLS[0][1].get("press_enter") is True, str(BRIDGE_CALLS[0][1]))
check("delay forwarded", BRIDGE_CALLS[0][1].get("delay_ms") == 2000, str(BRIDGE_CALLS[0][1].get("delay_ms")))
check("reported as sent", sent.get("auto_sent") is True, str(sent.get("auto_sent")))
check("message says sent", "sent" in sent["message"], sent["message"])
check("no browser action when the bridge delivered", "client_action" not in sent)


async def fake_bridge_blocked(settings, action, **kwargs):
    return {
        "ok": False,
        "opened": True,
        "enter_sent": False,
        "message": "opened whatsapp link but did not send: window did not come to the foreground",
    }


wa_tools._bridge_call = fake_bridge_blocked
try:
    blocked = asyncio.run(
        wa_tools.whatsapp_send_message(ctx_for(autosend_settings), to="Gowri", message="on my way")
    )
finally:
    wa_tools._bridge_call = original_bridge

check("blocked autosend is not reported as sent", blocked.get("auto_sent") is False)
check("blocked autosend asks for a manual press", "press send" in blocked["message"], blocked["message"])

print("\n--- aliases (live file, no restart)")
from app.services import whatsapp_aliases  # noqa: E402

bring = make_settings(whatsapp_country_code="91")
saved = whatsapp_aliases.save(bring, name="Prashant Frd", number="+91 98765 43210")
check("alias saved", saved["name"] == "Prashant Frd" and saved["count"] == 1, str(saved))
check("alias file written", os.path.exists(str(bring.whatsapp_aliases_path)))

check(
    "alias resolves by full name",
    whatsapp.resolve_recipient(bring, "Prashant Frd") == ("919876543210", "prashant frd"),
    str(whatsapp.resolve_recipient(bring, "Prashant Frd")),
)
check(
    "alias resolves from a first name",
    whatsapp.resolve_recipient(bring, "prashant")[0] == "919876543210",
)
check(
    "alias resolves with words in another order",
    whatsapp.resolve_recipient(bring, "frd prashant")[0] == "919876543210",
)
check(
    "alias resolves ignoring punctuation/case",
    whatsapp.resolve_recipient(bring, " PRASHANT-frd ")[0] == "919876543210",
)

second = whatsapp_aliases.save(bring, name="Prashant Frd", number="+91 90000 11111")
check("alias upsert replaces, not duplicates", second["count"] == 1, str(second["count"]))
check(
    "alias update takes effect immediately",
    whatsapp.resolve_recipient(bring, "prashant")[0] == "919000011111",
)

check("alias removed", whatsapp_aliases.remove(bring, name="Prashant frd") is True)
try:
    whatsapp.resolve_recipient(bring, "prashant")
    check("removed alias no longer resolves", False)
except ToolError as exc:
    check("removed alias no longer resolves", "not in WHATSAPP_CONTACTS" in str(exc), str(exc)[:80])

print("\n--- failure message is actionable")
try:
    whatsapp.resolve_recipient(bring, "Nobody Known")
    check("unknown name fails", False)
except ToolError as exc:
    text = str(exc)
    check(
        "error explains all the sources",
        "WHATSAPP_CONTACTS" in text and "cache" in text and "Google Contacts" in text,
        text[:110],
    )
    check("error suggests saving an alias", "alias" in text, text[-90:])

print("\n--- 'Name=+number' shorthand")
from app.tools import whatsapp as wa_tools  # noqa: E402

shorthand = make_settings(whatsapp_country_code="91", apps_bridge_enabled=False)
result = asyncio.run(
    wa_tools.whatsapp_send_message(
        ctx_for(shorthand), to="Prashant Frd=+91 98765 43210", message="hi from JARVIS"
    )
)
check("shorthand saved the alias", result.get("alias_saved") == "Prashant Frd", str(result.get("alias_saved")))
check("shorthand resolved to the number", result.get("to") == "919876543210", str(result.get("to")))
check(
    "shorthand message got the uri",
    result.get("opened", "").startswith("whatsapp://send?phone=919876543210"),
    str(result.get("opened"))[:60],
)
check(
    "alias now resolves without the number",
    whatsapp.resolve_recipient(shorthand, "prashant")[0] == "919876543210",
)

saved_tool = wa_tools.whatsapp_save_contact(ctx_for(shorthand), name="Ravi", number="+91 90000 22222")
check("save tool stores a mask-safe number", "*" in str(saved_tool.get("number")), str(saved_tool))
removed_tool = wa_tools.whatsapp_save_contact(ctx_for(shorthand), name="Ravi", remove=True)
check("save tool can remove", removed_tool.get("removed") is True, str(removed_tool))

print("\n--- bulk import (whatsapp_import_contacts)")
from app.services import whatsapp_import  # noqa: E402

_bulk_dir = os.path.join(_TEST_DATA, "bulk")
os.makedirs(_bulk_dir, exist_ok=True)
bulk = make_settings(
    whatsapp_country_code="91",
    whatsapp_aliases=os.path.join(_bulk_dir, "aliases.json"),
    whatsapp_contacts_cache=os.path.join(_bulk_dir, "contacts_cache.json"),
)
whatsapp_aliases.save(bulk, name="Hand Written", number="+91 90000 00001")

pasted = "\n".join(
    [
        "# a comment line",
        "Prashant Frd=+91 98765 43210",       # = separator
        "Gowri Akka, +91 90592 94845",        # comma
        "Ravi\t+919000011111",                # tab
        "Syam: +91 90000 22222",              # colon
        "+91 90000 33333 Karthik Csit",       # number first
        "Broken Line=not-a-number",           # unusable number
        "",
    ]
)
parsed_pairs = whatsapp_import.parse(pasted)
check(
    "parses =, comma, tab, colon and number-first lines",
    [p[0] for p in parsed_pairs]
    == ["Prashant Frd", "Gowri Akka", "Ravi", "Syam", "Karthik Csit"],
    str(parsed_pairs),
)
check("comments and blanks are skipped", len(parsed_pairs) == 5, str(len(parsed_pairs)))

vcards = "\n".join(
    [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "N:Sharma;Priya;;;",
        "TEL;TYPE=CELL:+91 90000 44444",
        "END:VCARD",
        "BEGIN:VCARD",
        "FN=Uncle Bob",
        "TEL;TYPE=HOME:+91 90000 55555",
        "END:VCARD",
    ]
)
vcard_pairs = whatsapp_import.parse(vcards)
check(
    "parses vCard FN and N",
    set(vcard_pairs) == {("Priya Sharma", "+91 90000 44444"), ("Uncle Bob", "+91 90000 55555")},
    str(vcard_pairs),
)

json_pairs = whatsapp_import.parse('{"Sita": "+91 90000 66666", "Ramu": "+91 90000 77777"}')
check("parses a JSON map", len(json_pairs) == 2, str(json_pairs))
list_pairs = whatsapp_import.parse('[{"name": "Lakshmi", "phones": ["+91 90000 88888"]}]')
check("parses a JSON list with phones[]", list_pairs == [("Lakshmi", "+91 90000 88888")], str(list_pairs))

# --- merge semantics
dry = whatsapp_import.run(bulk, text=pasted, dry_run=True)
check("dry run reports without writing", dry["added"] == 5 and dry["dry_run"] is True, str(dry["added"]))
check(
    "dry run keeps the file untouched",
    len(whatsapp_aliases.load(bulk)["aliases"]) == 1,
    str(whatsapp_aliases.load(bulk)["aliases"]),
)

first = whatsapp_import.run(bulk, text=pasted)
check("bulk import added every usable pair", first["added"] == 5, str(first))
check("a pair without a usable number is not imported", "Broken Line" not in whatsapp_aliases.load(bulk)["aliases"])
check("hand-written alias survived", "Hand Written" in whatsapp_aliases.load(bulk)["aliases"])
check(
    "imported names resolve immediately",
    whatsapp.resolve_recipient(bulk, "prashant")[0] == "919876543210",
    str(whatsapp.resolve_recipient(bulk, "prashant")),
)
check(
    "imported tab-separated entry resolves",
    whatsapp.resolve_recipient(bulk, "ravi")[0] == "919000011111",
    str(whatsapp.resolve_recipient(bulk, "ravi")),
)
check(
    "word-order matching works on imported names",
    whatsapp.resolve_recipient(bulk, "csit karthik")[0] == "919000033333",
)

again = whatsapp_import.run(bulk, text=pasted)
check("re-import is idempotent", again["added"] == 0 and again["unchanged"] == 5, str(again))

conflict = whatsapp_import.run(bulk, text="Prashant Frd=+91 99999 00000")
check("conflicting number is not applied", conflict["updated"] == 0 and conflict["conflict_count"] == 1, str(conflict["conflicts"]))
check(
    "conflict keeps the original number",
    whatsapp.resolve_recipient(bulk, "prashant")[0] == "919876543210",
)
forced = whatsapp_import.run(bulk, text="Prashant Frd=+91 99999 00000", overwrite=True)
check("overwrite replaces the number", forced["updated"] == 1, str(forced))
check(
    "overwritten number resolves",
    whatsapp.resolve_recipient(bulk, "prashant")[0] == "919999900000",
)

# --- import from the Google contacts cache
print("\n--- bulk import from the contacts cache")
contacts_cache.save(
    bulk,
    [
        {"name": "Gowri Akka", "phones": ["+91 90592 94845"]},
        {"name": "Palu", "phones": ["+91 90000 12121"]},
        {"name": "+91 90000 99999", "phones": ["+91 90000 99999"]},  # saved with a number as its name
        {"name": "100", "phones": ["+91 90000 99998"]},
        {"name": "No Phone", "phones": []},
    ],
    source="google",
)
cache_pairs = whatsapp_import.from_contacts_cache(bulk)
check(
    "cache source keeps names with a number and drops the rest",
    sorted(p[0] for p in cache_pairs) == ["Gowri Akka", "Palu"],
    str(cache_pairs),
)
junk_text = whatsapp_import.run(bulk, text="12345=+91 90000 99997")
check(
    "a numeric name is refused, not imported",
    junk_text["added"] == 0 and junk_text["invalid_count"] == 1 and "12345" not in whatsapp_aliases.load(bulk)["aliases"],
    str(junk_text["invalid"]),
)
cached = wa_tools.whatsapp_import_contacts(ctx_for(bulk), source="contacts")
check("tools import from the cache works", cached["added"] == 1, str(cached))
check("cached contact resolves after import", whatsapp.resolve_recipient(bulk, "palu")[0] == "919000012121")

empty_cache = make_settings(
    whatsapp_aliases=os.path.join(_bulk_dir, "fresh_aliases.json"),
    whatsapp_contacts_cache=os.path.join(_bulk_dir, "fresh_cache.json"),
)
try:
    wa_tools.whatsapp_import_contacts(ctx_for(empty_cache), source="contacts")
    check("empty cache is reported", False)
except ToolError as exc:
    check("empty cache is reported", "google_contacts_sync" in str(exc), str(exc)[:110])

try:
    wa_tools.whatsapp_import_contacts(ctx_for(empty_cache), text="nothing useful here")
    check("unusable text is reported", False)
except ToolError as exc:
    check("unusable text is reported", "no usable" in str(exc), str(exc)[:110])

noisy = wa_tools.whatsapp_import_contacts(ctx_for(empty_cache), text="Boss=+91 90000 98765")
check(
    "tool returns counts and samples",
    noisy["added"] == 1 and noisy["samples"][0]["name"] == "Boss" and "*" in noisy["samples"][0]["number"],
    str(noisy["samples"]),
)
check("tool reports the alias file path", noisy["path"] == str(empty_cache.whatsapp_aliases_path), noisy["path"])

# ------------------------------------------------------------------ cloud mode
print("\n--- cloud send (mock transport)")
cloud = make_settings(
    whatsapp_access_token="EAAtoken", whatsapp_phone_number_id="106540352242922"
)
seen = []


def ok_handler(request):
    seen.append(request)
    return httpx.Response(
        200,
        json={
            "messaging_product": "whatsapp",
            "contacts": [{"input": "+919876543210", "wa_id": "919876543210"}],
            "messages": [{"id": "wamid.HBgL123"}],
        },
    )


async def mock_send(handler, body="hello"):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await whatsapp.send_text(cloud, to="919876543210", body=body, client=client)


result = asyncio.run(mock_send(ok_handler))
check("cloud returns message id", result.get("message_id") == "wamid.HBgL123", str(result))
check("cloud returns wa_id", result.get("wa_id") == "919876543210")
request = seen[0]
check(
    "posts to the messages endpoint",
    request.url.path.endswith("/v27.0/106540352242922/messages"),
    request.url.path,
)
check("bearer token header", request.headers.get("authorization") == "Bearer EAAtoken")
check(
    "payload shape",
    json.loads(request.content)
    == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "919876543210",
        "type": "text",
        "text": {"preview_url": False, "body": "hello"},
    },
    str(json.loads(request.content))[:120],
)

# ------------------------------------------------------------------ cloud errors
print("\n--- cloud errors")


def status_handler(code, payload):
    return lambda request: httpx.Response(code, json=payload)


for label, handler, needle in (
    (
        "401 names the token",
        status_handler(401, {"error": {"message": "Invalid OAuth access token", "code": 190}}),
        "access token",
    ),
    (
        "131030 explains the sandbox list",
        status_handler(400, {"error": {"message": "Recipient not in allowed list", "code": 131030}}),
        "allowed list",
    ),
):
    try:
        asyncio.run(mock_send(handler))
        check(label, False)
    except ToolError as exc:
        check(label, needle in str(exc), str(exc)[:110])

try:
    asyncio.run(whatsapp.send_text(make_settings(), to="919876543210", body="x"))
    check("missing credentials reported", False)
except ToolError as exc:
    check("missing credentials reported", "WHATSAPP_ACCESS_TOKEN" in str(exc), str(exc)[:110])

for body, label in (("", "empty body refused"), ("x" * 5000, "over-long body refused")):
    try:
        asyncio.run(whatsapp.send_text(cloud, to="919876543210", body=body))
        check(label, False)
    except ToolError:
        check(label, True)

try:
    asyncio.run(
        wa_tools.whatsapp_send_message(
            ctx_for(make_settings(whatsapp_enabled=False)), to="+919876543210", message="x"
        )
    )
    check("disabled tool refuses", False)
except ToolError as exc:
    check("disabled tool refuses", "WHATSAPP_ENABLED" in str(exc), str(exc)[:90])

# ------------------------------------------------------------------ registration
print("\n--- registry")
tools = load_tools()
check("whatsapp_send_message registered", "whatsapp_send_message" in tools)
check("whatsapp_list_contacts registered", "whatsapp_list_contacts" in tools)
check("whatsapp_import_contacts registered", "whatsapp_import_contacts" in tools)
import_schema = tools["whatsapp_import_contacts"].schema()["input_schema"] if "whatsapp_import_contacts" in tools else {}
check(
    "import schema exposes the source enum",
    import_schema.get("properties", {}).get("source", {}).get("enum") == ["auto", "contacts", "text"],
    str(import_schema.get("properties", {}).get("source")),
)
send_tool = tools.get("whatsapp_send_message")
check("send asks for confirmation", bool(send_tool and send_tool.requires_confirmation))
check("send schema is an object", (send_tool.schema()["input_schema"].get("type") == "object") if send_tool else False)

print("")
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("all whatsapp checks passed")
