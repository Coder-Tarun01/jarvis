"""Central configuration.

Every knob comes from the environment (or the project ``.env`` file).
Nothing in the code base hard-codes a secret.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/ -> <repo root>
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- core ----------
    app_name: str = "JARVIS"
    log_level: str = "INFO"
    auth_token: str = Field(
        default="change-me-please",
        validation_alias=AliasChoices("JARVIS_AUTH_TOKEN", "AUTH_TOKEN"),
    )
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- LLM ----------
    # openai (default) | anthropic (optional fallback)
    llm_provider: str = "openai"

    # --- OpenAI (default provider) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-6.1-terra"
    openai_model_fast: str = "gpt-5.4-mini"
    # Optional: point at an OpenAI-compatible gateway, e.g. https://host/v1
    openai_base_url: str = ""
    # gpt-6.x rejects function tools on /chat/completions unless this is "none".
    # Empty = omit the parameter entirely.
    openai_reasoning_effort: str = ""
    openai_max_tokens: int = 1500
    openai_timeout: float = 120.0

    # --- Anthropic (only used when LLM_PROVIDER=anthropic) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_utility_model: str = "claude-haiku-5-5"
    anthropic_max_tokens: int = 1500
    anthropic_timeout: float = 120.0

    max_tool_iterations: int = 6
    history_limit: int = 30
    confirmation_timeout: float = 180.0

    # ---------- storage ----------
    database_url: str = ""
    data_dir: str = "data"
    workspace_dir: str = "workspace"
    persona_path: str = "persona.md"

    # ---------- memory ----------
    memory_top_k: int = 6
    memory_min_score: float = 0.12
    memory_extraction_enabled: bool = True

    # ---------- search ----------
    search_provider: str = "duckduckgo"
    tavily_api_key: str = ""
    serpapi_api_key: str = ""
    search_max_results: int = 5

    # ---------- speech ----------
    stt_provider: str = "browser"
    tts_provider: str = "browser"
    openai_stt_model: str = "whisper-1"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model: str = "eleven_turbo_v2_5"

    # ---------- shell ----------
    allowed_commands: str = "ping,ipconfig,whoami,hostname,git status,git log,git diff"
    command_timeout: float = 20.0

    # ---------- google ----------
    google_enabled: bool = False
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_calendar_id: str = "primary"
    google_timezone: str = "UTC"
    # also search the auto-collected "other contacts" (people you have emailed)
    google_contacts_include_other: bool = True

    # ---------- whatsapp ----------
    # WHATSAPP_MODE decides how a message actually leaves the machine:
    #   auto  (default) -> Cloud API when the token + phone id are set,
    #                      otherwise the wa.me hand-off
    #   cloud           -> always the Cloud API (errors if it is not configured)
    #   link            -> always the wa.me hand-off (no credentials needed)
    whatsapp_enabled: bool = True
    whatsapp_mode: str = "auto"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v27.0"
    whatsapp_api_base: str = "https://graph.facebook.com"
    # name=+number pairs, semicolon (or comma) separated:
    #   mom=+919876543210;ravi=+447700900123
    whatsapp_contacts: str = ""
    # prepended when a spoken number has no country code, e.g. 91 for India
    whatsapp_country_code: str = ""
    # local mirror of Google Contacts, written by google_contacts_sync and read
    # before any live People API call
    whatsapp_contacts_cache: str = "data/contacts_cache.json"
    # runtime-editable aliases (name -> number); unlike WHATSAPP_CONTACTS this
    # needs no restart, and `whatsapp_save_contact` writes it
    whatsapp_aliases: str = "data/whatsapp_aliases.json"
    # link mode: after opening whatsapp://send, press Enter in the chat window so
    # the message actually goes out (the URI alone only pre-fills the box).
    # Off by default; the host bridge refuses unless WhatsApp is the foreground app.
    whatsapp_autosend: bool = False
    whatsapp_autosend_delay_ms: int = 2000

    # ---------- desktop apps (host bridge) ----------
    # The backend runs in a container, so open/close requests are queued in the
    # shared workspace and executed by host/app-bridge.ps1 on Windows.
    apps_bridge_enabled: bool = True
    apps_bridge_timeout: float = 12.0
    apps_require_confirmation: bool = False
    # alias=target[|processName] ; semicolon separated.
    # Targets may use %ENVIRONMENT_VARIABLES% so the same line works on any machine.
    apps_allowlist: str = (
        "notepad=notepad.exe;"
        "calculator=calc.exe|CalculatorApp;"
        "paint=mspaint.exe;"
        "explorer=explorer.exe;"
        "chrome=chrome.exe;"
        "edge=msedge.exe;"
        "firefox=firefox.exe;"
        "code=code.cmd|Code;"
        "antigravity=%LOCALAPPDATA%/Programs/Antigravity IDE/Antigravity IDE.exe|Antigravity IDE;"
        "spotify=spotify.exe;"
        "terminal=wt.exe;"
        "settings=ms-settings:"
    )
    # never closable, even if listed above
    apps_denylist: str = "explorer,winlogon,csrss,lsass,svchost,services,dwm,wininit,smss"

    # ---------- approval policy ----------
    # Only these tools pause for an explicit OK; everything else runs straight
    # away. "*" asks for every tool, an empty string falls back to the per-tool
    # flags. Shell commands stay gated; WhatsApp sends are authorised to go out
    # immediately (the host bridge still needs a resolvable contact).
    confirm_tools: str = "run_command"

    # ---------- housekeeping ----------
    reminder_poll_seconds: float = 5.0

    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_path / 'jarvis.db').as_posix()}"
        return self

    @staticmethod
    def _as_path(value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (PROJECT_ROOT / path)

    @property
    def data_path(self) -> Path:
        return self._as_path(self.data_dir)

    @property
    def workspace_path(self) -> Path:
        return self._as_path(self.workspace_dir)

    @property
    def persona_file(self) -> Path:
        return self._as_path(self.persona_path)

    @property
    def contacts_cache_path(self) -> Path:
        return self._as_path(self.whatsapp_contacts_cache or "data/contacts_cache.json")

    @property
    def whatsapp_aliases_path(self) -> Path:
        return self._as_path(self.whatsapp_aliases or "data/whatsapp_aliases.json")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_command_list(self) -> list[str]:
        return [c.strip().lower() for c in self.allowed_commands.split(",") if c.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def provider(self) -> str:
        """Active LLM provider, normalised to a supported value."""
        value = (self.llm_provider or "openai").strip().lower()
        return value if value in ("openai", "anthropic") else "openai"

    @property
    def llm_api_key(self) -> str:
        return self.openai_api_key if self.provider == "openai" else self.anthropic_api_key

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def llm_model(self) -> str:
        return self.openai_model if self.provider == "openai" else self.anthropic_model

    @property
    def llm_model_fast(self) -> str:
        if self.provider == "openai":
            return self.openai_model_fast or self.openai_model
        return self.anthropic_utility_model or self.anthropic_model

    @property
    def llm_max_tokens(self) -> int:
        return self.openai_max_tokens if self.provider == "openai" else self.anthropic_max_tokens

    @property
    def llm_timeout(self) -> float:
        return self.openai_timeout if self.provider == "openai" else self.anthropic_timeout

    @property
    def llm_reasoning_effort(self) -> str:
        return (self.openai_reasoning_effort or "").strip() if self.provider == "openai" else ""

    # -------------------------------------------------------------- whatsapp
    @property
    def whatsapp_cloud_ready(self) -> bool:
        """True when the Cloud API credentials are both present."""
        return bool(self.whatsapp_access_token.strip() and self.whatsapp_phone_number_id.strip())

    @property
    def whatsapp_effective_mode(self) -> str:
        """off | cloud | link — what the tools will actually use.

        ``cloud`` is reported even when the credentials are missing, so the tool
        can explain exactly which variable to fill in instead of silently
        opening a browser.
        """
        if not self.whatsapp_enabled:
            return "off"
        wanted = (self.whatsapp_mode or "auto").strip().lower()
        if wanted in ("off", "disabled", "none"):
            return "off"
        if wanted == "cloud":
            return "cloud"
        if wanted == "link":
            return "link"
        return "cloud" if self.whatsapp_cloud_ready else "link"

    @property
    def whatsapp_contact_map(self) -> dict[str, str]:
        """alias -> raw phone number, aliases lowercased."""
        pairs: dict[str, str] = {}
        raw = (self.whatsapp_contacts or "").replace(",", ";")
        for entry in raw.split(";"):
            entry = entry.strip()
            if not entry or "=" not in entry:
                continue
            name, _, number = entry.partition("=")
            name = " ".join(name.split()).lower()
            number = number.strip()
            if name and number:
                pairs[name] = number
        return pairs

    # ------------------------------------------------------------------ apps
    @property
    def apps_allowed(self) -> dict[str, tuple[str, str]]:
        """alias -> (launch target, process name override)."""
        allowed: dict[str, tuple[str, str]] = {}
        for entry in (self.apps_allowlist or "").split(";"):
            entry = entry.strip()
            if not entry or "=" not in entry:
                continue
            alias, _, value = entry.partition("=")
            target, _, process = value.partition("|")
            alias = alias.strip().lower()
            target = target.strip()
            if alias and target:
                allowed[alias] = (target, process.strip())
        return allowed

    @property
    def apps_denied(self) -> set[str]:
        return {item.strip().lower() for item in (self.apps_denylist or "").split(",") if item.strip()}

    # ------------------------------------------------------------- approvals
    @property
    def confirm_tool_set(self) -> set[str]:
        """Explicit list of tools that must ask first (``*`` = ask for all)."""
        return {item.strip().lower() for item in (self.confirm_tools or "").split(",") if item.strip()}

    def ensure_dirs(self) -> None:

        self.data_path.mkdir(parents=True, exist_ok=True)
        self.workspace_path.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
