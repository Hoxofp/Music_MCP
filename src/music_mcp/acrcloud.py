"""ACRCloud audio fingerprinting client (Identification API v1)."""

import base64
import hashlib
import hmac
import time
from typing import Any

import httpx

from .models import SongMatch

# https://docs.acrcloud.com/reference/error-codes
_NO_RESULT = 1001


class AcrCloudError(Exception):
    pass


def sign(access_key: str, access_secret: str, timestamp: str, data_type: str = "audio") -> str:
    string_to_sign = "\n".join(["POST", "/v1/identify", access_key, data_type, "1", timestamp])
    digest = hmac.new(access_secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def parse_matches(payload: dict[str, Any]) -> list[SongMatch]:
    """Turn an identify response into matches, best first. No match is an empty list."""
    status = payload.get("status", {})
    code = status.get("code")
    if code == _NO_RESULT:
        return []
    if code != 0:
        raise AcrCloudError(f"ACRCloud error {code}: {status.get('msg', 'unknown error')}")

    matches = []
    for item in payload.get("metadata", {}).get("music", []):
        spotify = item.get("external_metadata", {}).get("spotify", {})
        matches.append(
            SongMatch(
                title=item.get("title", "Unknown"),
                artists=[a["name"] for a in item.get("artists", []) if a.get("name")],
                album=item.get("album", {}).get("name"),
                release_date=item.get("release_date"),
                score=int(item.get("score", 0)),
                isrc=item.get("external_ids", {}).get("isrc"),
                spotify_track_id=spotify.get("track", {}).get("id"),
                play_offset_ms=item.get("play_offset_ms"),
            )
        )
    return sorted(matches, key=lambda m: m.score, reverse=True)


class AcrCloudClient:
    def __init__(self, host: str, access_key: str, access_secret: str, http: httpx.AsyncClient):
        self._url = f"https://{host}/v1/identify"
        self._key = access_key
        self._secret = access_secret
        self._http = http

    async def identify(self, sample: bytes) -> list[SongMatch]:
        timestamp = str(int(time.time()))
        data = {
            "access_key": self._key,
            "data_type": "audio",
            "signature_version": "1",
            "signature": sign(self._key, self._secret, timestamp),
            "sample_bytes": str(len(sample)),
            "timestamp": timestamp,
        }
        try:
            response = await self._http.post(
                self._url, data=data, files={"sample": ("sample", sample)}, timeout=30
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AcrCloudError(f"ACRCloud request failed: {exc}") from exc
        return parse_matches(response.json())
