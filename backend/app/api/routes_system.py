"""Health + tool discovery. The frontend uses /api/health to validate the token."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core.config import get_settings
from ..core.security import require_auth
from ..core.utils import iso, utcnow
from ..tools.registry import load_tools, tool_summaries

router = APIRouter(tags=["system"], dependencies=[Depends(require_auth)])


@router.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": "1.0.0",
        "time_utc": iso(utcnow()),
        "provider": settings.provider,
        "model": settings.llm_model,
        "model_fast": settings.llm_model_fast,
        "llm_configured": settings.llm_configured,
        "search_provider": settings.search_provider,
        "stt_provider": settings.stt_provider,
        "tts_provider": settings.tts_provider,
        "google_enabled": settings.google_enabled,
        "whatsapp_mode": settings.whatsapp_effective_mode,
        "whatsapp_contacts": len(settings.whatsapp_contact_map),
        "tool_count": len(load_tools()),
        "workspace": str(settings.workspace_path),
    }


@router.get("/api/tools")
def list_tools() -> list[dict]:
    return tool_summaries()
