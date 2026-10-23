import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from music_mcp.config import Settings

Handler = Callable[[httpx.Request], httpx.Response]

TRACK_ID = "4uLU6hMCjMI75M1A2tKUQC"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        acr_host="identify-eu-west-1.acrcloud.com",
        acr_access_key="key",
        acr_access_secret="secret",
        spotify_client_id="client-id",
        spotify_client_secret=None,
        spotify_redirect_uri="http://127.0.0.1:8888/callback",
        token_path=tmp_path / "token.json",
        audio_dir=tmp_path,
    )


def acr_payload(*scores: int) -> dict:
    return {
        "status": {"code": 0, "msg": "Success"},
        "metadata": {
            "music": [
                {
                    "title": f"Song {s}",
                    "artists": [{"name": "Artist"}],
                    "album": {"name": "Album"},
                    "score": s,
                    "external_ids": {"isrc": "GBUM71029604"},
                    "external_metadata": {"spotify": {"track": {"id": TRACK_ID}}},
                    "play_offset_ms": 9000,
                }
                for s in scores
            ]
        },
    }


def spotify_track(track_id: str = TRACK_ID) -> dict:
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": "Never Gonna Give You Up",
        "artists": [{"name": "Rick Astley"}],
        "album": {"name": "Whenever You Need Somebody"},
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
    }


def json_response(data: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, content=json.dumps(data), headers={"content-type": "application/json"}
    )
