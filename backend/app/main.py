"""JARVIS backend entrypoint.

    uvicorn app.main:app --reload --port 8000      (run from ./backend)
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.router import api_router
from .core.config import PROJECT_ROOT, get_settings
from .core.db import init_db
from .core.logging import get_logger, setup_logging
from .services.scheduler import reminder_loop
from .tools.registry import load_tools

settings = get_settings()
setup_logging(settings.log_level)
log = get_logger("main")

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    init_db()
    tools = load_tools()
    task = asyncio.create_task(reminder_loop(settings), name="jarvis-reminders")

    log.info(
        "%s ready - provider=%s model=%s tools=%d llm=%s",
        settings.app_name,
        settings.provider,
        settings.llm_model,
        len(tools),
        "configured" if settings.llm_configured else "MISSING API KEY",
    )
    if not settings.llm_configured:
        key_name = "OPENAI_API_KEY" if settings.provider == "openai" else "ANTHROPIC_API_KEY"
        log.warning("%s is empty: chat will answer with a setup error.", key_name)
    if settings.auth_token in ("", "change-me-please"):
        log.warning("JARVIS_AUTH_TOKEN is still the default — set a real one in .env")

    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        log.info("shutdown complete")


app = FastAPI(
    title="JARVIS",
    version="1.0.0",
    description="Personal AI assistant: voice + text, memory, and tools.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """Unauthenticated liveness probe for Docker/compose."""
    return {"status": "ok"}


if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        if full_path.startswith(("api/", "ws")):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "app": settings.app_name,
                "status": "ok",
                "frontend": "run `npm run dev` in ./frontend (http://localhost:5173)",
                "docs": "/docs",
            }
        )
