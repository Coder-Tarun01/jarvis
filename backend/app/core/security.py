"""Single-user bearer-token auth for both REST and the WebSocket."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Query, WebSocket, status

from .config import get_settings


def _token_matches(candidate: str | None) -> bool:
    if not candidate:
        return False
    expected = get_settings().auth_token or ""
    if not expected:
        return False
    return secrets.compare_digest(candidate.strip(), expected)


def extract_token(authorization: str | None, query_token: str | None = None) -> str | None:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if value and scheme.lower() in ("bearer", "token"):
            return value.strip()
        if not value:
            return authorization.strip()
        return value.strip()
    return query_token


async def require_auth(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """FastAPI dependency: 401 unless a valid token is supplied."""
    if not _token_matches(extract_token(authorization, token)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing JARVIS token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def websocket_authorized(websocket: WebSocket) -> bool:
    header = websocket.headers.get("authorization")
    query = websocket.query_params.get("token")
    return _token_matches(extract_token(header, query))
