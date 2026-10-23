"""One-time Spotify login (Authorization Code + PKCE). No client secret is required."""

import base64
import hashlib
import html
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import Settings
from .spotify import SCOPES, TOKEN_URL, Token, TokenStore

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return verifier, challenge.decode()


def _wait_for_code(redirect_uri: str, expected_state: str, timeout: float = 300) -> str:
    target = urlparse(redirect_uri)
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path != target.path:
                self.send_error(404)
                return
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if query.get("state") != expected_state:
                result["error"] = "state mismatch (possible CSRF); try again"
            elif "error" in query:
                result["error"] = query["error"]
            else:
                result["code"] = query.get("code", "")
            ok = "code" in result
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = (
                "Spotify connected. You can close this tab."
                if ok
                else f"Login failed: {html.escape(result['error'])}"
            )
            self.wfile.write(f"<h2>music-mcp</h2><p>{message}</p>".encode())
            done.set()

        def log_message(self, *args: object) -> None:  # keep the terminal quiet
            pass

    server = HTTPServer((target.hostname or "127.0.0.1", target.port or 80), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not done.wait(timeout):
            raise SystemExit("Timed out waiting for the Spotify redirect.")
    finally:
        server.shutdown()
    if "code" not in result:
        raise SystemExit(f"Spotify login failed: {result['error']}")
    return result["code"]


def login(settings: Settings) -> None:
    if not settings.spotify_client_id:
        raise SystemExit(
            "Set SPOTIFY_CLIENT_ID (see .env.example) before running `music-mcp auth`."
        )
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = f"{AUTHORIZE_URL}?" + urlencode(
        {
            "client_id": settings.spotify_client_id,
            "response_type": "code",
            "redirect_uri": settings.spotify_redirect_uri,
            "scope": SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )
    print(f"Opening Spotify login in your browser...\nIf nothing opens, visit:\n{url}\n")
    webbrowser.open(url)
    code = _wait_for_code(settings.spotify_redirect_uri, state)

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
            "client_id": settings.spotify_client_id,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(f"Token exchange failed ({response.status_code}): {response.text}")
    TokenStore(settings.token_path).save(Token.from_response(response.json()))
    print(f"Done. Token saved to {settings.token_path}")
