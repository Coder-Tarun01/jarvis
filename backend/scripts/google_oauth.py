"""One-time helper: exchange a Google OAuth client for a refresh token.

    cd backend
    python scripts/google_oauth.py

It opens your browser, catches the redirect on http://localhost:8765, and prints
the three values to paste into .env:

    GOOGLE_CLIENT_ID=...
    GOOGLE_CLIENT_SECRET=...
    GOOGLE_REFRESH_TOKEN=...

Scopes are read-only Calendar, read-only Gmail, Gmail draft composition, and
read-only Contacts (People API, including the auto-collected "other contacts").
Nothing is sent: the draft tool only creates drafts.
"""

from __future__ import annotations

import http.server
import json
import os
import secrets
import socketserver
import sys
import urllib.parse
import webbrowser

import httpx

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/oauth2callback"
SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://www.googleapis.com/auth/contacts.other.readonly",
    ]
)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def prompt(label: str, env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    return input(f"{label}: ").strip()


class _Handler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None
    state: str = ""

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path != "/oauth2callback":
            self.send_response(404)
            self.end_headers()
            return

        if params.get("state", [""])[0] != type(self).state:
            type(self).error = "state mismatch"
        elif "error" in params:
            type(self).error = params["error"][0]
        else:
            type(self).code = params.get("code", [None])[0]

        body = (
            "<html><body style='font-family:system-ui;background:#04060c;color:#e6f1ff;"
            "display:flex;align-items:center;justify-content:center;height:100vh'>"
            "<h2>JARVIS: authorisation received. You can close this tab.</h2></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:  # silence the default access log
        return


def main() -> int:
    client_id = prompt("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_ID")
    client_secret = prompt("GOOGLE_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required.")
        return 1

    _Handler.state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": _Handler.state,
        }
    )
    auth_url = f"{AUTH_URL}?{query}"

    print("\nCreate an OAuth client of type 'Desktop app' in Google Cloud Console,")
    print(f"and add this exact redirect URI:\n  {REDIRECT_URI}\n")
    print("If the browser does not open by itself, paste this URL into it:\n")
    print(auth_url)
    print()
    print("Opening the consent screen…")

    with socketserver.TCPServer(("localhost", PORT), _Handler) as server:
        webbrowser.open(auth_url)
        print(f"Waiting for the redirect on {REDIRECT_URI} (Ctrl+C to abort)")
        # Keep serving until the real callback arrives; browsers also poke the
        # port with probes (/favicon.ico, ...) which must not end the wait.
        while not (_Handler.code or _Handler.error):
            server.handle_request()

    if _Handler.error or not _Handler.code:
        print(f"Authorisation failed: {_Handler.error or 'no code returned'}")
        return 1

    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": _Handler.code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        print(f"Token exchange failed ({response.status_code}): {response.text[:300]}")
        return 1

    payload = response.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        print(
            "No refresh_token returned. Revoke JARVIS in your Google account and run again "
            "with prompt=consent (this script already sends it)."
        )
        print(json.dumps(payload, indent=2)[:500])
        return 1

    print("\nAdd these lines to your .env:\n")
    print("GOOGLE_ENABLED=true")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
    print("\nThen restart the backend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
