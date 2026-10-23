"""Spotify Web API client: PKCE user tokens with refresh, client-credentials fallback for search.

Uses the post-February-2026 endpoints (`/me/library`, `/me/playlists`, `/playlists/{id}/items`).
"""

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import anyio
import httpx

from .models import Playlist, Track

API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = "user-library-modify playlist-read-private playlist-modify-private playlist-modify-public"

_ID = re.compile(r"^[0-9A-Za-z]{22}$")
_URI_OR_URL = re.compile(
    r"(?:spotify:track:|open\.spotify\.com/(?:intl-[a-z]+/)?track/)([0-9A-Za-z]{22})"
)


class SpotifyError(Exception):
    pass


class SpotifyAuthError(SpotifyError):
    pass


def parse_track_id(value: str) -> str:
    """Accept a bare ID, a spotify:track: URI or an open.spotify.com link."""
    value = value.strip()
    if _ID.match(value):
        return value
    if match := _URI_OR_URL.search(value):
        return match.group(1)
    raise SpotifyError(f"Not a Spotify track ID, URI or link: {value!r}")


@dataclass
class Token:
    access_token: str
    expires_at: float
    refresh_token: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 60

    @classmethod
    def from_response(cls, data: dict[str, Any], previous_refresh: str | None = None) -> "Token":
        return cls(
            access_token=data["access_token"],
            expires_at=time.time() + int(data.get("expires_in", 3600)),
            # Spotify may omit refresh_token on refresh; keep the old one then.
            refresh_token=data.get("refresh_token") or previous_refresh,
        )


class TokenStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Token | None:
        try:
            return Token(**json.loads(self.path.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return None

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(token)), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)


def _track(item: dict[str, Any]) -> Track:
    return Track(
        id=item["id"],
        uri=item["uri"],
        name=item["name"],
        artists=[a["name"] for a in item.get("artists", [])],
        album=item.get("album", {}).get("name"),
        url=item.get("external_urls", {}).get("spotify"),
    )


def _playlist(item: dict[str, Any]) -> Playlist:
    items = item.get("items") or item.get("tracks") or {}
    return Playlist(
        id=item["id"],
        name=item["name"],
        url=item.get("external_urls", {}).get("spotify"),
        public=item.get("public"),
        track_count=items.get("total"),
    )


class SpotifyClient:
    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        store: TokenStore,
        http: httpx.AsyncClient,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._store = store
        self._http = http
        self._app_token: Token | None = None

    # -- auth ---------------------------------------------------------------------------------

    async def _user_token(self, force_refresh: bool = False) -> Token | None:
        token = self._store.load()
        if token is None:
            return None
        if (token.expired or force_refresh) and token.refresh_token and self._client_id:
            response = await self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token.refresh_token,
                    "client_id": self._client_id,
                },
            )
            if response.status_code != 200:
                raise SpotifyAuthError("Spotify session expired. Run `music-mcp auth` again.")
            token = Token.from_response(response.json(), token.refresh_token)
            self._store.save(token)
        return token

    async def _app_access_token(self) -> Token | None:
        if not (self._client_id and self._client_secret):
            return None
        if self._app_token is None or self._app_token.expired:
            response = await self._http.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
            )
            if response.status_code != 200:
                raise SpotifyAuthError(
                    f"Spotify rejected the client credentials ({response.status_code})"
                )
            self._app_token = Token.from_response(response.json())
        return self._app_token

    async def _bearer(self, user: bool, force_refresh: bool = False) -> str:
        token = await self._user_token(force_refresh)
        if token is None and not user:
            token = await self._app_access_token()
        if token is None:
            raise SpotifyAuthError(
                "Not logged in to Spotify. Run `music-mcp auth` once to authorize this server."
            )
        return token.access_token

    # -- transport ----------------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user: bool,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        refreshed = rate_limited = False
        while True:
            headers = {
                "Authorization": f"Bearer {await self._bearer(user, force_refresh=refreshed)}"
            }
            response = await self._http.request(
                method, f"{API}{path}", params=params, json=json_body, headers=headers
            )
            if response.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if response.status_code == 429 and not rate_limited:
                rate_limited = True
                await anyio.sleep(min(int(response.headers.get("Retry-After", "1")), 10))
                continue
            break
        if response.status_code >= 400:
            try:
                message = response.json().get("error", {}).get("message", response.text)
            except ValueError:
                message = response.text
            raise SpotifyError(f"Spotify {response.status_code} on {method} {path}: {message}")
        return response.json() if response.content else {}

    # -- API ----------------------------------------------------------------------------------

    async def search_tracks(self, query: str, limit: int = 5) -> list[Track]:
        data = await self._request(
            "GET", "/search", user=False, params={"q": query, "type": "track", "limit": limit}
        )
        return [_track(item) for item in data.get("tracks", {}).get("items", []) if item]

    async def save_to_library(self, track_ids: list[str]) -> list[str]:
        uris = [f"spotify:track:{parse_track_id(t)}" for t in track_ids]
        for i in range(0, len(uris), 40):  # endpoint limit: 40 URIs per call
            await self._request(
                "PUT", "/me/library", user=True, params={"uris": ",".join(uris[i : i + 40])}
            )
        return uris

    async def create_playlist(self, name: str, description: str, public: bool) -> Playlist:
        data = await self._request(
            "POST",
            "/me/playlists",
            user=True,
            json_body={"name": name, "description": description, "public": public},
        )
        return _playlist(data)

    async def add_to_playlist(self, playlist_id: str, track_ids: list[str]) -> str | None:
        uris = [f"spotify:track:{parse_track_id(t)}" for t in track_ids]
        snapshot = None
        for i in range(0, len(uris), 100):  # endpoint limit: 100 items per call
            data = await self._request(
                "POST",
                f"/playlists/{playlist_id}/items",
                user=True,
                json_body={"uris": uris[i : i + 100]},
            )
            snapshot = data.get("snapshot_id", snapshot)
        return snapshot

    async def list_playlists(self, limit: int = 20, offset: int = 0) -> list[Playlist]:
        data = await self._request(
            "GET", "/me/playlists", user=True, params={"limit": limit, "offset": offset}
        )
        return [_playlist(item) for item in data.get("items", []) if item]
