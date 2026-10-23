import time
from urllib.parse import parse_qs

import httpx
import pytest

from music_mcp.spotify import (
    SpotifyAuthError,
    SpotifyClient,
    SpotifyError,
    Token,
    TokenStore,
    parse_track_id,
)

from .conftest import TRACK_ID, json_response, spotify_track


@pytest.mark.parametrize(
    "value",
    [
        TRACK_ID,
        f"spotify:track:{TRACK_ID}",
        f"https://open.spotify.com/track/{TRACK_ID}?si=abc",
        f"https://open.spotify.com/intl-tr/track/{TRACK_ID}",
    ],
)
def test_parse_track_id_accepts_common_forms(value: str) -> None:
    assert parse_track_id(value) == TRACK_ID


def test_parse_track_id_rejects_garbage() -> None:
    with pytest.raises(SpotifyError):
        parse_track_id("not-a-track")


def make_client(tmp_path, handler, token: Token | None = None, secret: str | None = None):
    store = TokenStore(tmp_path / "token.json")
    if token:
        store.save(token)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SpotifyClient("client-id", secret, store, http), store, http


@pytest.mark.anyio
async def test_user_call_without_login_explains_how_to_fix(tmp_path) -> None:
    client, _, http = make_client(tmp_path, lambda r: json_response({}))
    async with http:
        with pytest.raises(SpotifyAuthError, match="music-mcp auth"):
            await client.save_to_library([TRACK_ID])


@pytest.mark.anyio
async def test_save_to_library_uses_new_endpoint_in_chunks_of_40(tmp_path) -> None:
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT" and request.url.path == "/v1/me/library"
        calls.append(parse_qs(request.url.query.decode())["uris"][0].split(","))
        return httpx.Response(200)

    token = Token("user-token", time.time() + 3600, "refresh")
    client, _, http = make_client(tmp_path, handler, token)
    async with http:
        uris = await client.save_to_library([TRACK_ID] * 45)
    assert [len(c) for c in calls] == [40, 5]
    assert uris[0] == f"spotify:track:{TRACK_ID}"


@pytest.mark.anyio
async def test_expired_token_is_refreshed_and_persisted(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            assert b"grant_type=refresh_token" in request.read()
            return json_response({"access_token": "fresh", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer fresh"
        return json_response({"items": [{"id": "p1", "name": "Mix", "items": {"total": 3}}]})

    client, store, http = make_client(
        tmp_path, handler, Token("stale", time.time() - 10, "refresh")
    )
    async with http:
        playlists = await client.list_playlists()
    assert playlists[0].track_count == 3
    saved = store.load()
    assert saved and saved.access_token == "fresh" and saved.refresh_token == "refresh"


@pytest.mark.anyio
async def test_401_triggers_one_forced_refresh_then_retries(tmp_path) -> None:
    attempts = {"api": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            return json_response({"access_token": "new", "expires_in": 3600})
        attempts["api"] += 1
        if request.headers["Authorization"] == "Bearer revoked":
            return json_response({"error": {"status": 401, "message": "expired"}}, 401)
        return json_response({"tracks": {"items": [spotify_track()]}})

    client, _, http = make_client(tmp_path, handler, Token("revoked", time.time() + 3600, "r"))
    async with http:
        tracks = await client.search_tracks("rick astley")
    assert attempts["api"] == 2 and tracks[0].artists == ["Rick Astley"]


@pytest.mark.anyio
async def test_search_falls_back_to_client_credentials(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            assert b"grant_type=client_credentials" in request.read()
            return json_response({"access_token": "app", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer app"
        return json_response({"tracks": {"items": [spotify_track()]}})

    client, _, http = make_client(tmp_path, handler, secret="client-secret")
    async with http:
        assert (await client.search_tracks("x"))[0].id == TRACK_ID


@pytest.mark.anyio
async def test_add_to_playlist_posts_to_items_endpoint(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/v1/playlists/p1/items"
        return json_response({"snapshot_id": "snap"}, 201)

    client, _, http = make_client(tmp_path, handler, Token("t", time.time() + 3600))
    async with http:
        assert await client.add_to_playlist("p1", [TRACK_ID]) == "snap"
