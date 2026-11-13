"""Structured-ish logging setup shared by the API and the background workers."""

from __future__ import annotations

import logging
import re
import sys

_CONFIGURED = False

FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"

#: Bearer tokens ride in the WebSocket query string; keep them out of the logs.
_TOKEN_PATTERN = re.compile(r"(token=)[^&\s\"]+")


class _RedactTokenFilter(logging.Filter):
    """Masks ``token=…`` in uvicorn's access log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib API
        try:
            if record.args:
                record.args = tuple(
                    _TOKEN_PATTERN.sub(r"\1***", item) if isinstance(item, str) else item
                    for item in record.args
                )
            elif isinstance(record.msg, str):
                record.msg = _TOKEN_PATTERN.sub(r"\1***", record.msg)
        except Exception:  # noqa: BLE001 - logging must never raise
            return True
        return True


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    try:  # Windows consoles default to cp1252 and mangle em dashes
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):  # pragma: no cover
        pass
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format=FORMAT,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "anthropic", "openai", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # uvicorn logs the WebSocket handshake (which carries ?token=) on "error".
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        logging.getLogger(name).addFilter(_RedactTokenFilter())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"jarvis.{name}")
