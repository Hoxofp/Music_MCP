"""End-to-end through the MCP protocol with an in-memory client and fake HTTP backends."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from mcp import Client

from music_mcp.acrcloud import AcrCloudClient
from music_mcp.config import Settings
from music_mcp.server import AppContext, build_server
from music_mcp.spotify import SpotifyClient, TokenStore

from .conftest import TRACK_ID, acr_payload, json_response


def fake_backend(request: httpx.Request) -> httpx.Response:
    if "acrcloud" in request.url.host:
        return json_response(acr_payload(97, 41))
    return json_response({})


def server_for(settings: Settings):
    @asynccontextmanager
    async def context() -> AsyncIterator[AppContext]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake_backend)) as http:
            yield AppContext(
                settings=settings,
                acrcloud=AcrCloudClient(settings.acr_host, "key", "secret", http),  # type: ignore[arg-type]
                spotify=SpotifyClient("client-id", None, TokenStore(settings.token_path), http),
            )

    return build_server(context)


@pytest.mark.anyio
async def test_tools_are_listed_with_safety_annotations(settings: Settings) -> None:
    async with Client(server_for(settings)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "identify_song",
        "search_tracks",
        "save_to_library",
        "create_playlist",
        "add_to_playlist",
        "list_playlists",
    }
    assert tools["identify_song"].annotations.read_only_hint is True
    assert tools["save_to_library"].annotations.idempotent_hint is True
    assert tools["add_to_playlist"].annotations.read_only_hint is False
    assert tools["identify_song"].output_schema is not None


@pytest.mark.anyio
async def test_identify_song_returns_structured_match_and_records_history(
    settings: Settings, tmp_path: Path
) -> None:
    song = tmp_path / "clip.mp3"
    song.write_bytes(b"\xff\xfb" + b"\x00" * 4096)

    async with Client(server_for(settings)) as client:
        result = await client.call_tool("identify_song", {"path": str(song)})
        history = await client.read_resource("music://history")

    assert not result.is_error
    data = result.structured_content
    assert data["matched"] is True
    assert data["best"]["score"] == 97
    assert data["best"]["spotify_track_id"] == TRACK_ID
    assert [m["score"] for m in data["alternatives"]] == [41]
    assert json.loads(history.contents[0].text)[0]["title"] == "Song 97"


@pytest.mark.anyio
async def test_paths_outside_audio_dir_are_refused(settings: Settings, tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere.mp3"
    async with Client(server_for(settings)) as client:
        result = await client.call_tool("identify_song", {"path": str(outside)})
    assert result.is_error
    assert "MUSIC_MCP_AUDIO_DIR" in result.content[0].text


@pytest.mark.anyio
async def test_library_write_without_login_is_a_tool_error_the_model_can_explain(
    settings: Settings,
) -> None:
    async with Client(server_for(settings)) as client:
        result = await client.call_tool("save_to_library", {"track_ids": [TRACK_ID]})
    assert result.is_error
    assert "music-mcp auth" in result.content[0].text
