"""Sandboxed access to the ./workspace folder (and nothing outside it)."""

from __future__ import annotations

from pathlib import Path

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from .base import Tool, ToolContext

MAX_BYTES = 512 * 1024


def _root(ctx: ToolContext) -> Path:
    settings: Settings = ctx.settings or get_settings()
    root = settings.workspace_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve(ctx: ToolContext, relative: str) -> Path:
    root = _root(ctx)
    relative = (relative or "").strip().replace("\\", "/").lstrip("/")
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ToolError("that path is outside the workspace sandbox")
    return candidate


def list_files(ctx: ToolContext, subdir: str = "") -> dict:
    target = _resolve(ctx, subdir)
    if not target.exists():
        raise ToolError(f"'{subdir}' does not exist in the workspace")
    if not target.is_dir():
        raise ToolError(f"'{subdir}' is a file, not a folder")

    entries = []
    for path in sorted(target.iterdir()):
        if path.name.startswith("."):
            continue
        try:
            stat = path.stat()
        except OSError:  # pragma: no cover
            continue
        entries.append(
            {
                "name": path.name,
                "type": "dir" if path.is_dir() else "file",
                "size": None if path.is_dir() else stat.st_size,
            }
        )
    root = _root(ctx)
    return {
        "workspace": str(root),
        "path": str(target.relative_to(root)).replace("\\", "/") or ".",
        "entries": entries[:200],
        "truncated": len(entries) > 200,
    }


def read_file(ctx: ToolContext, path: str, max_chars: int = 8000) -> dict:
    target = _resolve(ctx, path)
    if not target.exists():
        raise ToolError(f"'{path}' does not exist in the workspace")
    if target.is_dir():
        return list_files(ctx, path)
    size = target.stat().st_size
    if size > MAX_BYTES:
        raise ToolError(f"file is {size} bytes; the workspace reader caps at {MAX_BYTES}")

    raw = target.read_bytes()
    if b"\x00" in raw[:2048]:
        raise ToolError("that looks like a binary file, so I won't read it as text")

    text = raw.decode("utf-8", errors="replace")
    max_chars = max(200, min(int(max_chars), 40000))
    truncated = len(text) > max_chars
    return {
        "path": str(target.relative_to(_root(ctx))).replace("\\", "/"),
        "size": size,
        "truncated": truncated,
        "content": text[:max_chars],
    }


def search_files(ctx: ToolContext, query: str, limit: int = 20) -> dict:
    query = (query or "").strip()
    if len(query) < 2:
        raise ToolError("search needs at least two characters")
    root = _root(ctx)
    needle = query.lower()
    hits: list[dict] = []
    scanned = 0

    for path in root.rglob("*"):
        if len(hits) >= limit or scanned >= 500:
            break
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        scanned += 1
        if needle in path.name.lower():
            hits.append({"path": str(path.relative_to(root)).replace("\\", "/"), "match": "filename"})
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:1024]:
            continue
        text = raw.decode("utf-8", errors="replace")
        lowered = text.lower()
        index = lowered.find(needle)
        if index != -1:
            snippet = text[max(0, index - 80): index + len(query) + 80].replace("\n", " ")
            hits.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "match": "content",
                    "snippet": snippet.strip(),
                }
            )
    return {"query": query, "scanned": scanned, "count": len(hits), "hits": hits}


TOOLS = [
    Tool(
        name="list_workspace_files",
        description="List files in the sandboxed ./workspace folder",
        input_schema={
            "type": "object",
            "properties": {"subdir": {"type": "string", "description": "Optional subfolder"}},
        },
        handler=list_files,
    ),
    Tool(
        name="read_workspace_file",
        description="Read a text file from the sandboxed ./workspace folder",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to ./workspace"},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 40000, "default": 8000},
            },
            "required": ["path"],
        },
        handler=read_file,
    ),
    Tool(
        name="search_workspace_files",
        description="Search filenames and text contents inside ./workspace",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "required": ["query"],
        },
        handler=search_files,
    ),
]
