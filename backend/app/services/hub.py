"""WebSocket fan-out: one hub, many browser tabs, serialized sends per socket."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from ..core.logging import get_logger

log = get_logger("hub")


class Hub:
    def __init__(self) -> None:
        self._sockets: dict[WebSocket, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> None:
        async with self._guard:
            self._sockets[websocket] = asyncio.Lock()
        log.info("client connected (%d online)", self.count)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._guard:
            self._sockets.pop(websocket, None)
        log.info("client disconnected (%d online)", self.count)

    @property
    def count(self) -> int:
        return len(self._sockets)

    async def send(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        lock = self._sockets.get(websocket)
        if lock is None:
            return False
        try:
            async with lock:
                await websocket.send_json(payload)
            return True
        except Exception as exc:  # noqa: BLE001 - a dead socket is not an error
            log.debug("send failed, dropping client: %s", exc)
            await self.unregister(websocket)
            return False

    async def broadcast(self, payload: dict[str, Any]) -> int:
        sent = 0
        for websocket in list(self._sockets):
            if await self.send(websocket, payload):
                sent += 1
        return sent


hub = Hub()
