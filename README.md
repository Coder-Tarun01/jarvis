# JARVIS — a local, voice-first personal AI assistant

Talk to it or type at it. It remembers durable facts about you, keeps your todos and
reminders, searches the web, reads files from a sandbox, opens and closes desktop apps, and
asks permission before it does anything with side effects.

- **Frontend**: React + Vite + Tailwind, dark HUD with an orb for idle / listening / thinking / speaking
- **Symbol**: the INTI monogram (`frontend/src/components/IntiMark.jsx`) is the app's mark — it is the orb core, the header badge, the archive icon, the login lockup and the favicon
- **Archive rail**: the conversation sidebar starts closed; the panel button in the header toggles it (hamburger on mobile)
- **Backend**: FastAPI, WebSocket streaming, SQLite via SQLAlchemy
- **Brain**: OpenAI Chat Completions with function tools and token streaming (Claude kept as an optional fallback)
- **Voice**: browser Web Speech API (default) or Whisper / OpenAI TTS / ElevenLabs via `.env`
- **Wake word**: say *“Hey Jarvis”* and then the request — same breath (*“hey jarvis, what's the weather”*) or the next one. The detector hands the microphone over to a command capture, which submits after ~1.8 s of silence (or gives up after 8 s if you stay quiet) and re-arms itself afterwards
- **Desktop control**: open/close Windows apps through a small PowerShell bridge (see §8)
- **WhatsApp**: send messages via the Cloud API, or hand a pre-filled chat to WhatsApp when no credentials exist (see §9)
- **Extensible**: drop a file into `backend/app/tools/` and it is registered on the next start

## Architecture (in one breath)

```
browser ──WS /ws──► FastAPI agent loop ──► OpenAI chat.completions (streaming, function tools)
   ▲                     │  │                 └ fallback: Anthropic (LLM_PROVIDER=anthropic)
   │                     │  └── tools/* (one file per tool, auto-loaded)
   │                     └───── memory: retrieve facts → system prompt → extract new facts
   └── token stream ─────┘
REST /api/* : conversations, memories, tasks, notes, reminders, speech
SQLite: conversations, messages, memories, tasks, reminders, notes
desktop apps: tools queue JSON in workspace/.appbridge ──► host/app-bridge.ps1 (PowerShell)
```

---

## 1. Quick start (no Docker)

Requirements: **Python 3.11+**, **Node 20+**, an OpenAI API key.

```bash
# from the project root
cp .env.example .env          # Windows: Copy-Item .env.example .env
```

Open `.env` and set at least:

```ini
ANTHROPIC_API_KEY=sk-ant-...
JARVIS_AUTH_TOKEN=<paste a long random string>
```

Generate a token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then run everything with one command:

```bash
./run.sh          # macOS / Linux
.\run.ps1         # Windows PowerShell
```

or start the two halves by hand:

```bash
# terminal 1 — backend
cd backend
python -m venv ../.venv
../.venv/Scripts/python -m pip install -r requirements.txt   # Windows
../.venv/bin/python -m pip install -r requirements.txt        # macOS/Linux
../.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**, paste your `JARVIS_AUTH_TOKEN`, and say hello.
API docs live at **http://127.0.0.1:8000/docs**.

> Voice input needs **Chrome or Edge** (Web Speech API). Typing works everywhere.
> The first microphone use asks for permission; wake word needs the mic open too.

## 2. Quick start (Docker)

```bash
cp .env.example .env     # then fill in ANTHROPIC_API_KEY + JARVIS_AUTH_TOKEN
mkdir -p data workspace
docker compose up --build
```

- UI → **http://localhost:8080**
- API → **http://localhost:8000** (direct, useful for debugging)

The compose stack runs the API in one container and serves the built React app from
nginx in another, proxying `/api` and `/ws` to the backend. `data/`, `workspace/` and
`persona.md` are bind-mounted, so your database, files and persona survive rebuilds
and image updates.

Stop with `docker compose down` (add `-v` only if you want to start from scratch).

## 3. Configuration

Every setting comes from `.env`. Nothing is hard-coded, and `.env` is git-ignored.

| Variable | Default | What it does |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | `openai` (default), `anthropic` (fallback) or `openrouter` (free models). |
| `OPENAI_API_KEY` | — | **Required for the default provider.** Also powers Whisper STT and OpenAI TTS. |
| `OPENAI_MODEL` | `gpt-6.1-terra` | Main chat model. Must support function tools + streaming (see §3.1). |
| `OPENAI_MODEL_FAST` | `gpt-5.4-mini` | Cheap model for background memory extraction. |
| `OPENAI_REASONING_EFFORT` | `none` | Sent only when set. **`none` is required** for `gpt-6.x` to accept function tools on `/chat/completions`. |
| `OPENAI_BASE_URL` | empty | Point at an OpenAI-compatible gateway; empty = api.openai.com. |
| `OPENAI_MAX_TOKENS` | `1500` | Per-turn output cap (`max_completion_tokens`). |
| `OPENAI_TIMEOUT` | `120` | Request timeout in seconds. |
| `ANTHROPIC_API_KEY` | — | Only used when `LLM_PROVIDER=anthropic`. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Fallback provider's main model. |
| `ANTHROPIC_UTILITY_MODEL` | `claude-haiku-5-5` | Fallback provider's cheap model. |
| `OPENROUTER_API_KEY` | — | Only used when `LLM_PROVIDER=openrouter` (free models, e.g. when the OpenAI quota is spent). |
| `OPENROUTER_MODEL` | `baidu/ernie-5.5-flash-preview:free` | Free chat model; must support `tools` + streaming. |
| `OPENROUTER_MAX_TOKENS` | `1500` | Per-turn output cap, sent as `max_tokens` (OpenRouter rejects `max_completion_tokens`). |
| `JARVIS_AUTH_TOKEN` | `change-me-please` | Single-user bearer token for REST **and** WebSocket. **Change it.** |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated browser origins allowed to call the API. |
| `DATABASE_URL` | empty → `<data>/jarvis.db` | Any SQLAlchemy URL; SQLite by default. |
| `DATA_DIR` | `data` | SQLite location. |
| `WORKSPACE_DIR` | `workspace` | The only folder the file tools may read. |
| `PERSONA_PATH` | `persona.md` | Persona file, re-read every turn. |
| `MEMORY_TOP_K` / `MEMORY_MIN_SCORE` | `6` / `0.12` | How many memories to inject, and the similarity floor. |
| `MEMORY_EXTRACTION_ENABLED` | `true` | Turn on automatic fact extraction after each reply. |
| `SEARCH_PROVIDER` | `duckduckgo` | `duckduckgo` (free), `tavily`, or `serpapi`. |
| `TAVILY_API_KEY` / `SERPAPI_API_KEY` | — | Needed for those providers. |
| `STT_PROVIDER` | `browser` | `browser` (Web Speech) or `whisper` (OpenAI). |
| `TTS_PROVIDER` | `browser` | `browser` (SpeechSynthesis) or `elevenlabs`. |
| `OPENAI_API_KEY` / `OPENAI_STT_MODEL` | — / `whisper-1` | For `STT_PROVIDER=whisper`. |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | — | For `TTS_PROVIDER=elevenlabs`. |
| `ALLOWED_COMMANDS` | `ping,ipconfig,...` | Comma-separated **prefix** whitelist for `run_command`. |
| `COMMAND_TIMEOUT` | `20` | Seconds before a command is killed. |
| `GOOGLE_ENABLED` | `false` | Turns on Calendar/Gmail/Contacts tools. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` | — | See §7. |
| `GOOGLE_CONTACTS_INCLUDE_OTHER` | `true` | Also search the auto-collected "other contacts" (needs `contacts.other.readonly`). |
| `CONFIRM_TOOLS` | `run_command,whatsapp_send_message` | The only tools that ask before acting. `*` = ask for everything, empty = use each tool's flag (see §5). |
| `APPS_BRIDGE_ENABLED` | `true` | Allows the desktop-app tools; the host watcher still has to run (see §8). |
| `APPS_REQUIRE_CONFIRMATION` | `false` | Extra gate on launching apps. Leave it off and use `CONFIRM_TOOLS` instead. |
| `APPS_ALLOWLIST` | `notepad=notepad.exe;…` | `alias=target[|process]` pairs separated by `;` — the only apps JARVIS may launch or close (ships with `antigravity`, `code`, `chrome`, …). |
| `APPS_DENYLIST` | `explorer,winlogon,…` | Processes that can never be closed. |
| `APPS_CLOSE_GRACE_MS` | `2500` | How long a polite close gets before termination (host-side). |
| `APPS_FORCE_AFTER_GRACE` | `true` | Terminate apps that ignore the close request; `false` only reports them. |
| `APPS_BRIDGE_TIMEOUT` | `12` | Seconds to wait for the host to answer a request. |
| `WHATSAPP_ENABLED` | `true` | Master switch for the WhatsApp tools. |
| `WHATSAPP_MODE` | `auto` | `auto` = Cloud API if credentials exist, else the `wa.me` hand-off; `cloud`/`link` force one path (see §9). |
| `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` | — | Cloud API credentials. Without them messages are pre-filled instead of sent. |
| `WHATSAPP_CONTACTS` | empty | `name=+countrynumber` pairs separated by `;` — who JARVIS may message. |
| `WHATSAPP_COUNTRY_CODE` | empty | Prefix for numbers spoken (or bulk-imported) without one — e.g. `91`. Set it before the first import. |
| `WHATSAPP_CONTACTS_CACHE` | `data/contacts_cache.json` | Local mirror of Google Contacts used for name → number lookups (written by `google_contacts_sync`). |
| `WHATSAPP_ALIASES` | `data/whatsapp_aliases.json` | Live alias file (name → number) written by `whatsapp_save_contact` and `whatsapp_import_contacts`; no restart needed. |
| `WHATSAPP_AUTOSEND` | `false` | After opening the chat, press Enter so the message actually goes out (needs the bridge). |
| `WHATSAPP_AUTOSEND_DELAY_MS` | `2000` | Wait before typing, so the chat and compose box are ready. |
| `REMINDER_POLL_SECONDS` | `5` | How often the scheduler checks for due reminders. |
| `HISTORY_LIMIT` | `30` | Messages of context per turn. |
| `MAX_TOOL_ITERATIONS` | `6` | Hard stop for tool-call loops. |
| `CONFIRMATION_TIMEOUT` | `180` | Seconds before a pending approval auto-denies. |
| `LOG_LEVEL` | `INFO` | `DEBUG` shows per-request detail. |

### 3.1 LLM provider setup (OpenAI by default, Claude optional)

The models in `.env.example` were **not guessed**. They were picked by listing what the
account can actually see (`client.models.list()`, 96 models) and then probing each
general-purpose candidate for streaming **function-tool** support:

| Model | Role | Why |
| --- | --- | --- |
| `gpt-6.1-terra` | `OPENAI_MODEL` | Newest general-purpose chat model on the account that returns streamed `tool_calls` on `/chat/completions`. |
| `gpt-5.4-mini` | `OPENAI_MODEL_FAST` | Cheapest model that still does reliable JSON extraction; used only for background memory extraction. |

Two gotchas worth knowing:

- The **`gpt-6.x` / `gpt-5.6-*` families reject function tools on `/chat/completions`**
  unless `reasoning_effort` is set to `none` (their default effort is only permitted on
  `/v1/responses`). Hence `OPENAI_REASONING_EFFORT=none`. Models like `gpt-5.5`, `gpt-5.4`
  and `chat-latest` also pass the probe.
- Switching vendor or routing through a gateway is configuration, not code: set
  `OPENAI_BASE_URL` to any OpenAI-compatible endpoint, or `LLM_PROVIDER=anthropic` to use the
  Claude fallback (the `anthropic` package is already pinned).

Re-run the probe after a model refresh:

```bash
cd backend
python scripts/probe_models.py
```

It prints `OPENAI_MODEL` / `OPENAI_REASONING_EFFORT` / `OPENAI_MODEL_FAST` recommendations
and never prints the key.

#### Running on free models (OpenRouter)

When the OpenAI quota runs out, nothing has to be re-wired: `LLM_PROVIDER=openrouter` swaps in
the `OpenRouterProvider`, which is the same Chat Completions client pointed at
`https://openrouter.ai/api/v1` — streaming, tool calls and the agent loop are unchanged.

```
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-…          # https://openrouter.ai/settings/keys
OPENROUTER_MODEL=baidu/ernie-5.5-flash-preview:free
OPENROUTER_MAX_TOKENS=1500
```

```bash
docker compose up -d --force-recreate backend   # .env is read at start
```

What differs from the OpenAI provider, and why:

| Detail | OpenAI | OpenRouter | Why it matters |
| --- | --- | --- | --- |
| Output cap | `max_completion_tokens` | **`max_tokens`** | `max_completion_tokens` is an OpenAI-only field; OpenRouter rejects it |
| Reasoning | `reasoning_effort` | **omitted** (OpenRouter takes a `reasoning` object) | free models 400 on the OpenAI spelling |
| Usage | final chunk has `usage` | `usage: {include: true}` in the body | token counts **and `cost`** for free models |
| Attribution | — | optional `HTTP-Referer` / `X-Title` | shows JARVIS in the model's OpenRouter rankings |

Practical notes:

- **Free tier is rate limited.** OpenRouter answers `429` with `Retry-After`; the shared
  backoff already retries that (and only before any text has been streamed, so the UI never
  sees a duplicate answer). `402` means the free allowance is spent — it is reported verbatim.
- **JSON mode is best-effort.** The memory extractor asks for `response_format: json_object`;
  if a free model refuses it, the provider retries that one call as plain text and parses the
  JSON out of the reply (`extract_json`).
- **Speech does not need OpenAI** if you keep `STT_PROVIDER=browser` / `TTS_PROVIDER=browser`
  (the default here), which is why an exhausted OpenAI key is survivable end to end.
- Switch back at any time by setting `LLM_PROVIDER=openai` — the OpenAI keys stay in `.env`.
- Offline proof of the request shape (no key, no quota): `python tests/openrouter_test.py`.

Verify the live path with one command — it prints the provider/model/key and then makes a real
completion plus a real tool call:

```bash
cd backend
python scripts/check_llm.py            # 0 ok · 2 no key · 3 key rejected · 4 bad model · 5 rate/credit
python scripts/check_llm.py --no-tools # skip the tool probe (cheaper on a free tier)
```

---

## 4. Project layout

```
tor/
├── .env.example              # every knob, documented
├── docker-compose.yml
├── persona.md                # editable persona / system prompt
├── run.sh · run.ps1          # one-command dev start
├── host/                     # Windows-side helper for desktop apps (see section 8)
│   ├── app-bridge.ps1        # watcher: open / close / list desktop applications
│   ├── start-bridge.cmd      # double-click launcher for the watcher
│   └── whatsapp-import.ps1   # bulk-import WhatsApp aliases (see section 9)
├── data/                     # SQLite lives here (git-ignored)
├── workspace/                # the only folder file tools can read
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt      # pinned
│   ├── scripts/
│   │   ├── check_llm.py      # preflight: provider, key, one real completion + tool call
│   │   ├── google_oauth.py   # one-time refresh-token helper
│   │   └── import_whatsapp_contacts.py # bulk alias import (contacts cache / CSV / vCard)
│   ├── tests/
│   │   ├── smoke_test.py     # imports, tools, time parsing, memory
│   │   ├── api_test.py       # REST + WebSocket contract
│   │   ├── agent_mock_test.py# full agent loop against a fake OpenAI endpoint
│   │   ├── desktop_bridge_test.py # allowlist, approvals, file-queue protocol
│   │   └── whatsapp_test.py  # contacts, both delivery paths, Cloud API errors
│   └── app/
│       ├── main.py           # app factory, lifespan, SPA serving
│       ├── api/
│       │   ├── deps.py
│       │   ├── router.py
│       │   ├── routes_chat.py            # WebSocket protocol
│       │   ├── routes_conversations.py   # history: list/search/open/rename/delete
│       │   ├── routes_memories.py
│       │   ├── routes_tasks.py
│       │   ├── routes_notes.py
│       │   ├── routes_reminders.py
│       │   ├── routes_speech.py          # whisper / elevenlabs endpoints
│       │   └── routes_system.py          # /api/health, /api/tools
│       ├── core/
│       │   ├── agent.py      # the loop: context → Claude → tools → answer → memory
│       │   ├── config.py     # pydantic-settings, .env only
│       │   ├── db.py         # engine, sessions, SQLite pragmas
│       │   ├── models.py     # conversations, messages, memories, tasks, reminders, notes
│       │   ├── schemas.py    # request models
│       │   ├── security.py   # single-user bearer token
│       │   ├── errors.py
│       │   ├── logging.py
│       │   └── utils.py      # UTC helpers, NL time parser, retry/backoff
│       ├── memory/
│       │   ├── store.py      # remember / rank / delete
│       │   └── extractor.py  # LLM fact extraction + "remember that…" fallback
│       ├── services/
│       │   ├── llm.py        # provider-neutral facade + shared types
│       │   ├── llm_openai.py # OpenAI chat.completions: streaming, tool deltas, retries
│       │   ├── llm_openrouter.py # free-tier models on the same Chat Completions shape
│       │   ├── llm_anthropic.py # optional fallback provider
│       │   ├── persona.py    # persona.md + clock + memories → system prompt
│       │   ├── hub.py        # WebSocket fan-out
│       │   ├── scheduler.py  # reminder/timer polling loop
│       │   ├── speech.py     # Whisper + ElevenLabs
│       │   ├── google.py     # Calendar + Gmail over REST
│       │   └── whatsapp.py   # Cloud API send + wa.me hand-off, contact book
│       └── tools/            # ← plugins live here
│           ├── base.py       # Tool + ToolContext
│           ├── registry.py   # auto-discovery + execution
│           ├── datetime_tool.py
│           ├── desktop_apps.py  # open / close / list desktop apps via the host bridge
│           ├── files.py
│           ├── google_tools.py
│           ├── notes.py
│           ├── reminders.py
│           ├── system.py
│           ├── tasks.py
│           ├── whatsapp.py      # whatsapp_send_message / save_contact / import_contacts / list_contacts
│           └── web_search.py
└── frontend/
    ├── Dockerfile · nginx.conf
    ├── package.json · vite.config.js · tailwind.config.js · postcss.config.js
    ├── index.html
    └── src/
        ├── main.jsx · App.jsx · index.css
        ├── lib/api.js
        ├── hooks/
        │   ├── useJarvis.js      # WebSocket state machine + message list
        │   ├── useSpeech.js      # TTS (browser / ElevenLabs)
        │   ├── useVoiceInput.js  # STT (Web Speech / Whisper)
        │   └── useWakeWord.js    # "Hey Jarvis"
        ├── components/
        │   ├── Orb.jsx · StatusBar.jsx · Sidebar.jsx
        │   ├── ChatPanel.jsx · MessageBubble.jsx · Composer.jsx
        │   ├── ConfirmationModal.jsx · Toasts.jsx
        └── pages/
            ├── Login.jsx
            └── Assistant.jsx
```

## 5. How it works

**One turn, end to end**

1. Browser sends `{"type":"user_message","text":"…","conversation_id":12}` over `/ws`.
2. The message is persisted; the agent retrieves the top-K memories for that text.
3. System prompt = `persona.md` + local/UTC clock + retrieved memories + operating rules.
4. The configured provider (OpenAI by default) streams a turn with all tool schemas. Text
   deltas go straight to the UI.
5. If the turn contains `tool_use` blocks, each tool runs; results are fed back as
   `tool_result` blocks and the loop repeats (max `MAX_TOOL_ITERATIONS`).
6. Only tools that need approval (see below) pause the loop and ask the UI; approval or
   denial is sent back over the same socket, and a timeout counts as a denial.
7. The final answer is saved, then a cheap model extracts durable facts into memory.

**Approval policy — only the irreversible things ask.** `CONFIRM_TOOLS` is the single
source of truth and ships with three entries:

| Asks first | Runs straight away |
| --- | --- |
| `run_command` (shell) | everything else: notes, todos, reminders, memory, file reads, web search, `open_url`, `open_desktop_app`, `close_desktop_app`, **`whatsapp_send_message`**, `google_*` |

App control is authorised to run unprompted: JARVIS may open or close anything in
`APPS_ALLOWLIST` on demand. The host bridge still enforces that allowlist (and the
`APPS_DENYLIST` for shells/session processes, plus its own process tree), so "no prompt"
never means "no limits" — it can only touch apps you listed. Add `close_desktop_app` back
to `CONFIRM_TOOLS` if you want the dialog for closes only.

Set `CONFIRM_TOOLS=*` for the paranoid behaviour, or a shorter list
(`CONFIRM_TOOLS=run_command`) if you want almost no prompts. Leave it empty to fall back
to each tool's own `requires_confirmation` flag. `GET /api/tools` always reports the
*effective* value, so the UI drawer matches what will actually happen.

Under the hood the agent awaits a future keyed by the model's tool-call id; the UI answers
with `{"type":"confirm","id":"…","approved":true|false}`. Silence for `CONFIRMATION_TIMEOUT`
seconds denies.

**Memory** — facts are stored as sentences and ranked with a token-set similarity score
(stop-words removed). No embedding service required, no network hop, and it is easy to
audit: open the sidebar's memory list via `GET /api/memories`. If you later want vectors,
only `memory/store.py` needs to change.

**Reminders & timers** — written to SQLite with a UTC due time. A background task polls
every few seconds, marks due rows fired, and broadcasts `{"type":"reminder",…}` to every
connected tab, which shows a toast, a desktop notification (if permitted) and speaks it.

---

## 6. Adding a new tool

A tool is one file. The registry imports every module in `backend/app/tools/` that is not
named `base`/`registry` and collects its `TOOLS` list. No registration step, no edits
elsewhere.

Example — `backend/app/tools/weather.py`:

```python
from __future__ import annotations

import httpx

from ..core.config import get_settings
from ..core.errors import ToolError
from .base import Tool, ToolContext


async def get_weather(ctx: ToolContext, city: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"},
        )
    if response.status_code >= 400:
        raise ToolError(f"weather lookup failed ({response.status_code})")
    return {"city": city, "current": response.json().get("current")}


TOOLS = [
    Tool(
        name="get_weather",
        description="Current weather for a city",          # the model reads this
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        handler=get_weather,                                # sync or async both work
        requires_confirmation=False,                        # True → UI approval first
        confirmation_hint="",                               # shown in the approval dialog
    ),
]
```

Rules of the road:

- `input_schema` must be a JSON-Schema **object** (the registry validates this at import).
- Handlers take `ctx: ToolContext` plus keyword args, and return anything JSON-serialisable;
  the registry stringifies it for the model.
- Raise `ToolError("user-safe message")` for expected failures — it is shown to the model
  and in the tool chip, never as a 500.
- Sync handlers are fine for DB work; use `async def` for network calls so the event loop
  is not blocked.
- To make the browser do something, return `{"client_action": {"action": "open_url", "url": ...}}`;
  the agent forwards it as a `client_action` event.
- Restart the backend (or let `--reload` do it) and the tool appears in `GET /api/tools`,
  ready for Claude to call.

## 7. Google Calendar, Gmail + Contacts (off by default)

The tools are `google_calendar_events` (read), `google_gmail_search` (read),
`google_gmail_create_draft` (creates a **draft** — nothing is ever sent) and
`google_contacts_search` (read-only **Contacts**, People API).

1. Go to **Google Cloud Console → APIs & Services**:
   - Enable **Google Calendar API**, **Gmail API** and **Google People API**.
   - **OAuth consent screen**: External, add yourself as a test user, and add the scopes
     `calendar.readonly`, `gmail.readonly`, `gmail.compose`, `contacts.readonly`,
     `contacts.other.readonly`.
   - **Credentials → Create credentials → OAuth client ID → Desktop app**.
2. Add this authorised redirect URI to the client:
   `http://localhost:8765/oauth2callback`
3. Run the helper and follow the browser flow:

   ```bash
   cd backend
   # Windows
   ..\.venv\Scripts\python.exe scripts\google_oauth.py
   # macOS / Linux
   ../.venv/bin/python scripts/google_oauth.py
   ```

   It prints the four `.env` lines to paste in (client id, secret, refresh token, and
   `GOOGLE_ENABLED=true`). If the browser does not open, it prints the consent URL.
4. Restart the backend. `GET /api/health` now shows `"google_enabled": true`, and the
   four tools appear in the tool list.

### Contacts

`google_contacts_search` reads two sources and merges them:

| Source | What it is | Scope |
| --- | --- | --- |
| `people/me/connections` | the contacts you saved | `contacts.readonly` |
| `otherContacts` | people you have emailed but never saved | `contacts.other.readonly` |

Results carry `name`, `emails`, `phones`, `org`, `photo` and `source` (`contacts` or
`other`). The query is a plain multi-word AND over name, company, emails and phone
digits — *"ravi acme"* matches `Ravi Kumar · Acme Ltd`, *"98765"* matches the phone —
because the People API has no server-side text search. If the `otherContacts` scope was
not granted, that source is skipped silently rather than failing the call.

Ask things like *“What's Ravi's email address?”*, *“Find Priya in my contacts”* or
*“Who do I know at Globex?”*. It is read-only, so it runs without an approval prompt.

Notes: the refresh token is stored only in `.env`; access tokens are cached in memory for
their lifetime. Revoke access any time at **myaccount.google.com → Security → Third-party
access**. Google is not required for anything else — JARVIS works fine with it off.

### If Google says "Access blocked"

`Error 403: access_denied — <app> has not completed the Google verification process`
means the app is in **Testing** mode and your account is not on its test-user list
(contacts/calendar/gmail are *sensitive* scopes, so Testing mode is restricted):

1. Cloud Console → your project → **Google Auth Platform → Audience**.
2. Under **Test users → + Add users**, add the Google account you sign in with, **Save**.
3. Re-open the consent link from the helper.

Alternatively click **Publish app** on the same page: the consent screen shows an
"unverified app" warning you can click through, but the refresh token no longer expires
after 7 days (Testing-mode tokens do).

## 8. Desktop apps: open and close (host bridge)

JARVIS lives in a Linux container, so it cannot touch your Windows desktop directly. The
backend therefore drops a request into the bind-mounted workspace, and a small PowerShell
watcher on the host performs the action and writes the answer back:

```
browser --WS--> backend (container) --> workspace/.appbridge/req/<id>.json
                                              |
                                 host/app-bridge.ps1 (PowerShell watcher)
                                              |
                                  Start-Process / CloseMainWindow / Get-Process
```

No ports are opened, nothing is exposed to the network, and the whole channel is a folder
you can inspect (requests are deleted as soon as they are answered).

### One-time setup (Windows host)

```powershell
host\start-bridge.cmd        # minimised window titled "JARVIS desktop bridge"
```

Leave that window open. It prints the aliases it loaded, a heartbeat every 2 minutes, and one
line per request (`open  notepad  a91f3c -> OK`). Works with the Docker stack and with a
native backend; `docker-compose.yml` already bind-mounts `./workspace`.

Optional auto-start on login:

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "D:\projects\tor\host\app-bridge.ps1"'
Register-ScheduledTask -TaskName 'JARVIS app bridge' -Action $action -RunLevel Limited
```

…or put a shortcut to `host\start-bridge.cmd` in `shell:startup`.

### Tools

| Tool | Approval | Notes |
| --- | --- | --- |
| `open_desktop_app(app, arguments?)` | no (add it to `CONFIRM_TOOLS` if you want the gate) | `app` is an alias from `APPS_ALLOWLIST`; `arguments` can carry a file to open |
| `close_desktop_app(app, force?)` | no (add it to `CONFIRM_TOOLS` for a dialog) | polite close first, then termination after the grace period; `APPS_DENYLIST` and the bridge's own process tree are never touched |
| `list_desktop_apps()` | no | windows with a title, each flagged `allowlisted` |

### Allowlist

`APPS_ALLOWLIST` holds `alias=target[|process-name]` entries separated by `;`:

```
APPS_ALLOWLIST=notepad=notepad.exe;calculator=calc.exe|CalculatorApp;code=code.cmd|Code;antigravity=%LOCALAPPDATA%/Programs/Antigravity IDE/Antigravity IDE.exe|Antigravity IDE;settings=ms-settings:
```

- `target` is what gets launched, so App Paths (`chrome`), `.cmd` shims (`code.cmd`) and
  protocol URIs (`ms-settings:`) all work. `%ENVIRONMENT_VARIABLES%` and forward slashes are
  fine (the watcher expands them), so one line works on any machine.
- `process-name` is only needed when it differs from the executable: packaged apps
  (Calculator → `CalculatorApp`), launchers (`code.cmd` → `Code`) and names with spaces
  (`Antigravity IDE.exe` → `Antigravity IDE`) need it for closing.
- **Microsoft Store (MSIX) apps** (WhatsApp, Spotify from the Store, new Teams…) cannot be
  pointed at their `WindowsApps` exe — the folder is version-stamped and locked. Use the
  package's shell target instead, with the machine-wide package family name:

  ```
  whatsapp=shell:AppsFolder/5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App|WhatsApp.Root
  ```

  Find the family name and the process name with:

  ```powershell
  Get-AppxPackage -Name '*WhatsApp*' | Select Name, PackageFamilyName
  (Get-Process -Name 'WhatsApp*').ProcessName
  ```

  Shell targets (`shell:…`, `ms-settings:`, `whatsapp:`) are handed straight to the shell,
  so they open reliably and survive app updates.
- **Spoken names are matched loosely.** `antigravity` also matches *"Google Antigravity"*,
  *"Antigravity IDE"*, *"Antigravity-IDE.exe"* and *"the Antigravity app"* — vendor words and
  filler are stripped, punctuation/extension ignored.
- Anything else is refused, and the error lists the valid aliases so the model can tell you
  what is available. Add a line, restart the bridge, done.
- `APPS_DENYLIST` (`explorer,winlogon,lsass,…`) can never be closed even if it is listed, so
  the shell and session processes stay out of reach.

### Closing behaviour

1. `CloseMainWindow()` — the same WM_CLOSE as clicking the ✕.
2. Wait `APPS_CLOSE_GRACE_MS` (default `2500`).
3. Whatever is left is terminated when `APPS_FORCE_AFTER_GRACE=true` (default), because
   packaged apps routinely leave windowless stub processes behind. Set it to `false` to only
   report stragglers and require the model to pass `force: true`.

Opening and closing both pass through the approval gate, so nothing moves without a click.

### If it does not work

| Symptom | Fix |
| --- | --- |
| *“the desktop bridge did not answer in time”* | The watcher is not running — start `host\start-bridge.cmd` and keep the window open. |
| *“… is not in the app allowlist”* | Add `alias=exe` to `APPS_ALLOWLIST` in `.env`, restart the bridge. |
| App opens but no window appears | Look for the `-> OK` line in the bridge window; a launch failure is reported there and back to JARVIS. |
| Close leaves the app running | Raise `APPS_CLOSE_GRACE_MS` or set `APPS_FORCE_AFTER_GRACE=true`. |
| Turn it off | `APPS_BRIDGE_ENABLED=false` (backend refuses the tools) and close the bridge window. |

---

## 9. WhatsApp messages (optional Cloud API)

Two delivery paths:

| Mode | What actually happens | Needs |
| --- | --- | --- |
| `link` (the fallback) | JARVIS resolves the name to a number, then opens `whatsapp://send?phone=<number>&text=<message>`. The host bridge ShellExecutes it, so the **WhatsApp desktop app jumps to that exact chat with the text already typed** — you press send. No bridge running? The browser is asked to open the same URI, and a `wa.me` link is included in the result. | nothing |
| `cloud` | A real send through Meta's WhatsApp Cloud API. It arrives without you touching anything. | `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` |

`WHATSAPP_MODE=auto` (default) picks `cloud` as soon as both credentials are present and
`link` otherwise. Force one with `WHATSAPP_MODE=cloud|link`, or switch the feature off with
`WHATSAPP_ENABLED=false`.

### Contacts — a name is enough

Resolution runs in this order, so you never have to read out a phone number:

1. **`WHATSAPP_CONTACTS`** in `.env` — static aliases (changing them needs a restart).
2. **`data/whatsapp_aliases.json`** — the *live* alias file. `whatsapp_save_contact` writes
   it, `whatsapp_import_contacts` fills it in bulk, and a change is effective on the next
   message, no restart.
3. **`data/contacts_cache.json`** — a local mirror of Google Contacts, refreshed with the
   `google_contacts_sync` tool (687 contacts / 74 KB on the test machine). No network call.
4. **One live Google People API query** — only when the name is not cached; the hit is
   written back into the cache, so the next time it is instant.

```
WHATSAPP_CONTACTS=mom=+919876543210
WHATSAPP_COUNTRY_CODE=91
WHATSAPP_CONTACTS_CACHE=data/contacts_cache.json
WHATSAPP_ALIASES=data/whatsapp_aliases.json
```

Matching is deliberately forgiving — punctuation, case, partial and word order all work:

| You say | Resolves to |
| --- | --- |
| `Prashant` / `prashant-frd` / `frd prashant` | `Prashant Frd` |
| `ravi k` | `Ravi Kumar` |
| `Devi` (two candidates) | asks which one instead of guessing |

If a name matches nothing, JARVIS stops guessing and asks **once** for the number, and offers
to remember it. Four ways to teach it:

- **Say it inline** — *"WhatsApp Prashant Frd=+91 98765 43210 that I'm late"*. The
  `Name=+number` form saves the alias *and* opens the chat in one step.
- **Ask it** — *"Save Prashant Frd as +91 98765 43210"* → `whatsapp_save_contact`
  (also accepts `remove: true` to forget one).
- **Import them all** — `whatsapp_import_contacts` / `host/whatsapp-import.ps1` (next section).
- **Edit `.env`** — add `Prashant Frd=+919876543210` to `WHATSAPP_CONTACTS` and restart the
  backend, if you prefer static config.

### Bulk import — every contact at once

Doing that one name at a time is tedious, so there is a bulk path:
`whatsapp_import_contacts` (tool) and `host/whatsapp-import.ps1` (command line). Both write
`data/whatsapp_aliases.json` through the same merge, so a name is searchable the moment the
command returns — no restart, no rebuild.

```
.\host\whatsapp-import.ps1 -Contacts -DryRun     # what would change, change nothing
.\host\whatsapp-import.ps1 -Contacts             # every Google contact with a number
.\host\whatsapp-import.ps1 -File .\workspace\contacts.csv
Get-Content list.txt | .\host\whatsapp-import.ps1 -Stdin
```

Or just ask: *"import all my Google contacts into WhatsApp aliases"*, or paste a list into the
chat and say *"import these"*. The tool takes `source` (`contacts` / `text` / `auto`),
`overwrite`, `dry_run` and `limit`.

Accepted formats — the parser is deliberately unfussy, because exported lists never agree:

| Input line | Result |
| --- | --- |
| `Prashant Frd=+91 98765 43210` | `Prashant Frd` → `919876543210` |
| `Gowri Akka, +91 90592 94845` | comma (also `;`, tab, `\|`, `:` and `tel:`/`whatsapp:` prefixes) |
| `+91 90000 33333 Karthik Csit` | number first, name after |
| vCard `FN:` / `N:` + `TEL` | one alias per number (`Priya Sharma`) |
| `{"Sita": "+91…"}` / `[{"name":…,"phones":[…]}]` | JSON map or list |
| `# comment`, `name,number` header | skipped |

What it will **not** do: overwrite you. An alias that already maps to a different number is
reported as a conflict and left alone (`-Overwrite` replaces it, `-DryRun` previews first), and
entries that are not usable aliases are skipped and listed — a number too short to be real
(`112`) or a contact saved as a bare number (`+91 98661 66186`). The real run on the development
machine: *687 cached contacts → 675 usable pairs → 668 aliases added, 7 number-only names and 4
bad numbers skipped, the hand-written alias untouched, and a second run reports 0 added.*

Set `WHATSAPP_COUNTRY_CODE` **before** the first import: it turns national-format numbers
(`9949483226`) into international ones (`919949483226`), and it is applied again on every lookup,
so entries imported earlier still resolve correctly once you set it.

#### Why there is no "scan the chat list" button

WhatsApp Desktop keeps the chat list locally, but every store is closed to an ordinary tool:

| Store | State |
| --- | --- |
| `%LOCALAPPDATA%\Packages\5319275A.WhatsAppDesktop_*\LocalState\sessions\*\*.db` (`contacts.db`, `genericStorage.db`, …) | SQLCipher-encrypted — no SQLite header, unreadable without WhatsApp's key |
| `…\LocalCache\EBWebView\Default\IndexedDB\*.ldb` | 4k+ plaintext JIDs, but only inside **log lines** — no names attached |
| Windows People store (`Windows.ApplicationModel.Contacts`) | empty unless you maintain it by hand |
| Google Contacts (`google_contacts_sync`) | **the real source** — name, phone, email, org |

That is why the importer reads the contacts cache and exported lists instead of screen-scraping:
it gets the same names with numbers that actually work, and nothing breaks when WhatsApp updates
its storage format.


### The bridge's `open-uri` action

The host watcher also accepts `{"action": "open-uri", "uri": "whatsapp://send?…"}`. It
ShellExecutes the URI and refuses any scheme outside `APPS_URI_SCHEMES` (default
`whatsapp,ms-settings`), so the container can ask the desktop to open a deep link without
being able to launch arbitrary protocols.

### Auto-send

`WHATSAPP_AUTOSEND=true` turns the hand-off into a real send: the bridge opens the URI,
waits `WHATSAPP_AUTOSEND_DELAY_MS` (default 2000 ms) for the chat and compose box, then
presses **Enter**. It is deliberately paranoid about *where* that Enter lands:

- the window is matched by **process name** (`WhatsApp*`) or an **exact** title
  (`WhatsApp`) — never a substring, so a code editor showing `whatsapp_test.py` can't match;
- the app's own process wins over its `msedgewebview2` host window;
- the window is raised with `AttachThreadInput` + `SetForegroundWindow` (Windows blocks
  focus stealing otherwise), then `GetForegroundWindow` is re-checked;
- **Enter is only pressed if the owner of the foreground window is that exact PID.** If
  anything else has focus, nothing is typed and the tool answers *"…could not auto-send —
  press send"*.

The result reports the outcome, so the model can be accurate:

```json
{"auto_sent": true,  "message": "sent Gowri Akka the message on WhatsApp"}
{"auto_sent": false, "message": "opened the chat with Gowri Akka … could not auto-send (…did not come to the foreground) — press send"}
```

### Turning on real sends

1. Create a Meta app and add the **WhatsApp** product. Meta hands you a **test number**
   with a phone-number ID and a temporary (24 h) access token.
2. Put both in `.env`:
   ```
   WHATSAPP_ACCESS_TOKEN=EAAG...
   WHATSAPP_PHONE_NUMBER_ID=106540352242922
   ```
3. Add the recipient to the test number's **allowed list** (Meta → WhatsApp → API setup).
   A test number may message up to 5 verified recipients; production needs a real number
   and an approved business.
4. `docker compose up -d --force-recreate backend`, then ask
   *"WhatsApp mom that dinner is at 8"*.

Two limits come from WhatsApp, not from JARVIS, and both are reported as readable errors:
a business number cannot open a conversation outside the **24-hour window** unless it sends
an approved template, and a text body is capped at 4096 characters.

### If it does not work

| Symptom | Fix |
| --- | --- |
| *"…is not a contact I know"* | Add `name=+number` to `WHATSAPP_CONTACTS`, or say the number. |
| The chat opens but nothing is sent | You are in `link` mode — press send, or configure the Cloud API. |
| `HTTP 401` | The temporary token expired (24 h); generate a new one. |
| `HTTP 400 … not in allowed list` | Add the recipient to the test number's allowed list in Meta. |
| `HTTP 400 … 24-hour window` | The recipient has to message the business number first, or use a template. |
| Nothing happens | `WHATSAPP_ENABLED=false`, or the browser blocked the pop-up — the tool result in the chat still carries the link. |

---

## 10. HTTP + WebSocket reference

REST (all require `Authorization: Bearer <JARVIS_AUTH_TOKEN>`):

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Status, model, providers, tool count (also the login check) |
| `GET` | `/api/tools` | Tool names, descriptions, confirmation flags |
| `GET` | `/api/conversations?q=` | History list (search titles **and** message bodies) |
| `POST` | `/api/conversations` | Create |
| `GET` | `/api/conversations/{id}` | Full thread |
| `PATCH` | `/api/conversations/{id}` | Rename |
| `DELETE` | `/api/conversations/{id}` | Delete (cascades to messages) |
| `GET/POST` | `/api/memories` | List / search (`?q=`) and add |
| `DELETE` | `/api/memories/{id}` | Forget |
| `GET/POST` | `/api/tasks`, `PATCH /api/tasks/{id}/complete\|reopen`, `DELETE` | Todos |
| `GET/POST` | `/api/notes`, `GET/DELETE /api/notes/{id}` | Notes |
| `GET/POST` | `/api/reminders`, `DELETE /api/reminders/{id}` | Reminders |
| `GET` | `/api/speech/config` | Which speech providers are ready |
| `POST` | `/api/speech/transcribe` | Whisper STT (multipart `file`) |
| `POST` | `/api/speech/speak` | ElevenLabs TTS (returns `audio/mpeg`) |
| `GET` | `/healthz` | Unauthenticated liveness probe |

WebSocket `GET /ws?token=…`:

```
client → user_message {text, conversation_id?} | confirm {id, approved} | stop | ping
server → hello | state | token | tool_call | tool_result | confirmation_request
         confirmation_timeout | client_action | assistant_done | memory_added
         reminder_scheduled | reminder | conversation_created | warning | error | stopped | pong
```

## 11. Tests

The suite is plain scripts (no pytest needed) and uses a temporary data directory:

```bash
cd backend
python tests/smoke_test.py        # imports, tool schemas, OpenAI tool formatting, memory ranking
python tests/api_test.py          # auth, every REST route, WebSocket handshake + errors
python tests/agent_mock_test.py   # full agent loop + confirmation against a mocked OpenAI endpoint
python tests/desktop_bridge_test.py  # app allowlist, approval flags, file-queue protocol
python tests/whatsapp_test.py     # numbers, contacts, aliases, bulk import, both delivery paths, Cloud API errors
python tests/google_contacts_test.py  # People API request shape, pagination, matching (mocked)
python tests/openrouter_test.py   # free-model provider: request shape, SSE tool calls, 429 backoff (mocked)
```

The frontend has one plain-script test too (Node, no bundler, no browser):

```bash
cd frontend
node tests/wake_phrase_test.mjs   # "hey jarvis, what's the weather" -> wake phrase + command
```

`agent_mock_test.py` replays real Chat Completions SSE frames (including fragmented
`tool_calls` arguments) through the `openai` SDK, so streaming, tool-result round-trips and
the deny path are exercised without spending tokens or needing a key.

`whatsapp_test.py` is fully offline too: the Cloud API is replaced by an
`httpx.MockTransport`, so the request shape, the `wamid` parsing and every error message are
checked without a token — and without ever messaging a real person.

`desktop_bridge_test.py` runs offline: it simulates the host watcher (including PowerShell's
UTF-8 BOM on responses) and checks the allowlist, the approval flags and every refusal path.
With the real watcher running, add `-e APPS_LIVE=1` to `docker compose exec` to also verify a
live round trip.

---

## 12. Ten things to try right after setup

Voice (press the mic or say “Hey Jarvis” with the wake toggle on) and text both work.

1. **Clock + context** — *“What time is it, and what day is it?”* → calls `get_datetime`
2. **Reminder** — *“Remind me to call the dentist tomorrow at 9:30.”* → schedules it; you get a
   toast + desktop notification + spoken line at the time
3. **Timer** — *“Set a timer for 90 seconds, I'm steeping tea.”* → the orb flips to speaking
   when it fires
4. **Todo** — *“Add 'review the deck' to my todos, due tomorrow at 5pm.”* then *“What's on my list?”*
5. **Complete** — *“Mark 'review the deck' as done.”*
6. **Durable memory** — *“Remember that I'm allergic to peanuts.”* → watch the “Remembered”
   toast; later ask *“Can you suggest a snack?”* and it avoids peanuts
7. **Notes** — *“Save a note called Wifi with the hotel password: hunter2.”* then
   *“Search my notes for hunter2.”*
8. **Web search** — *“Search the web for the latest on fusion energy and give me three bullets.”*
9. **Sandboxed file read** — drop a text file in `workspace/`, then *“List the workspace and
   summarise welcome.txt.”*
10. **The approval gate** — *“Run git status in the workspace.”* → an approval dialog appears
    with the exact command; deny once and watch it stand down, then approve on the retry.
    Note that *“Open https://news.ycombinator.com”* runs immediately: only irreversible
    tools ask (see §5).

Extras worth a go: *“Save a note called Wifi…”* and *“Delete the note called Wifi”* (both run
directly), *“Open Notepad”* / *“Close Notepad”* (both immediate, needs
`host\start-bridge.cmd`), *“Open Google Antigravity”*, *“WhatsApp mom that I'll be late”*
(approval, then a pre-filled chat until you configure the Cloud API — see §9),
*“Who can you message on WhatsApp?”*, *“What have you remembered about me?”*, and *“Stop”*
mid-answer to interrupt the stream.

## 13. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `401 Invalid or missing JARVIS token` | The token in the UI must equal `JARVIS_AUTH_TOKEN`. Re-paste it or clear `localStorage`. |
| Chat replies *“OPENAI_API_KEY is not configured”* | Add the key to `.env` and restart the backend (`.env` is read at boot). |
| `400 Function tools with reasoning_effort are not supported` | The model needs `OPENAI_REASONING_EFFORT=none` (gpt-6.x), or pick a model that ignores it — see §3.1. |
| Orb spins forever, no text | Check the backend console; retryable failures are retried with backoff, other 4xx are logged with the API message. |
| No voice input, no mic button | Web Speech API needs Chrome/Edge (and HTTPS or localhost). Otherwise set `STT_PROVIDER=whisper` + `OPENAI_API_KEY`. |
| Wake word never fires | Toggle “hey jarvis” on; it needs mic permission and a quiet room. It is browser recognition, not offline. |
| Wake word fires but the mic stays dead | Fixed: the detector used to hold the microphone (Chrome allows one recogniser per page). It now stops, hands the device to the command capture, and re-arms after. If the `wake on` chip is amber the detector is restarting — wait a moment. |
| Reminders don't pop | Allow notifications via the “desktop alerts” button; toasts work regardless. Timers only fire while the backend is running. |
| `run_command` says “not whitelisted” | Add a prefix to `ALLOWED_COMMANDS` (comma-separated, lower-case) and restart. |
| *“the desktop bridge did not answer in time”* | Start `host\start-bridge.cmd` on the host and keep its window open; see §8. |
| *“… is not in the app allowlist”* | Add `alias=exe` to `APPS_ALLOWLIST` in `.env` and restart the bridge window. |
| WhatsApp says *“…is not a contact I know”* | Add `name=+countrynumber` to `WHATSAPP_CONTACTS`, or say the number — see §9. |
| WhatsApp chat opens but nothing sends | That is `link` mode; press send, or add the Cloud API credentials (§9). |
| Search returns nothing | DuckDuckGo may throttle. Set `SEARCH_PROVIDER=tavily` (or `serpapi`) with a key. |
| Docker: `env file ... not found` | `cp .env.example .env` before `docker compose up`. |
| Port already in use | Backend: `--port 8001` + update the Vite proxy. Frontend: `npm run dev -- --port 5174`. |

## 14. Security model (and its limits)

- **One user, one token.** Every REST route and the WebSocket require
  `JARVIS_AUTH_TOKEN`; comparison is constant-time. There are no accounts, sessions or
  cookies, so keep the deployment private (localhost, Tailscale, or behind a reverse proxy
  with TLS).
- **Secrets never reach the browser.** All provider keys are server-side; the UI learns only
  provider names and booleans from `/api/health`.
- **Files are sandboxed.** File tools resolve paths and reject anything outside
  `WORKSPACE_DIR`, including `../` traversal and out-of-tree symlinks. Files over 512 KB or
  containing NUL bytes are refused.
- **Commands are whitelisted.** `run_command` requires an allow-listed prefix, rejects shell
  metacharacters (`; | & > < `` ` `` $`), runs with `shell=False`, a timeout, and the
  workspace as cwd.
- **Approval is reserved for irreversible actions.** `CONFIRM_TOOLS` decides: by default only
  `run_command` and `whatsapp_send_message` pause for an explicit UI approval (auto-deny on
  timeout). Everything else — reading, notes, todos, reminders, memory, URLs, Gmail drafts and
  **app open/close** — executes straight away. Tighten it back with one `.env` line
  (`CONFIRM_TOOLS=run_command,close_desktop_app,whatsapp_send_message`), or set `*` to gate
  every tool.
- **App control is bounded by lists, not by prompts.** Even unprompted, the container can only
  name aliases from `APPS_ALLOWLIST`; the host watcher re-checks that list, refuses every
  `APPS_DENYLIST` process, and never terminates its own process tree — so a close request can
  only reach apps you explicitly listed.
- **WhatsApp has a contact allowlist and a switch.** Only people in `WHATSAPP_CONTACTS`, the
  contacts cache, or a contact you name can be messaged; the numbers are masked in listings
  and logs, and `WHATSAPP_ENABLED=false` removes the tools' ability to do anything at all.
  Sends are authorised to run without a prompt, and with `WHATSAPP_AUTOSEND=true` the message
  is delivered by pressing Enter — but only after the WhatsApp window is proven to own the
  foreground, which is what keeps a keystroke from landing in another app.
- **Desktop apps are allow-listed on both sides.** The container can only ask for aliases from
  `APPS_ALLOWLIST`; the host watcher re-checks the same list, refuses `APPS_DENYLIST` processes,
  and the transport is a folder inside the sandboxed workspace — no port, no listener, and a
  request that nobody answers simply expires.
- **Personal data stays local.** Conversations, memories and tasks live in your SQLite file;
  the only outbound traffic is to OpenAI (and Google/search/speech if you enable them).

## 15. Next upgrades

- **Offline wake word** — swap the browser recogniser for a tiny ONNX/Vosk model (e.g. openWakeWord) so “Hey Jarvis” works without Chrome or a network.
- **Mobile / PWA shell** — the API is already phone-friendly; add a manifest, service worker and push notifications for reminders when the tab is closed.
- **Home automation tools** — Home Assistant REST tools (`turn_on_light`, `set_thermostat`) behind the same confirmation gate.
- **Local LLM option** — run Ollama/LM Studio behind `OPENAI_BASE_URL` (they speak the OpenAI API), or use `LLM_PROVIDER=anthropic`; no code change needed either way.
- **Vector memory** — embed memories with a small local model and add cosine search in `memory/store.py`, keeping the keyword scorer as a fallback.
- **Streaming TTS** — sentence-chunked synthesis so speech starts on the first clause instead of the full reply.
- **Multi-step automations** — named routines (“morning briefing”) that chain tools server-side on a schedule.
- **Prompt caching + cost panel** — cache the persona/tool block and surface token spend per conversation.
