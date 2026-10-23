import httpx
import pytest

from music_mcp.acrcloud import AcrCloudClient, AcrCloudError, parse_matches, sign

from .conftest import TRACK_ID, acr_payload, json_response


def test_sign_is_stable_and_secret_dependent() -> None:
    a = sign("key", "secret", "1700000000")
    assert a == sign("key", "secret", "1700000000")
    assert a != sign("key", "other", "1700000000")
    assert len(a) == 28  # base64 of a 20-byte SHA-1 digest


def test_parse_matches_sorts_best_first_and_maps_spotify_id() -> None:
    matches = parse_matches(acr_payload(60, 95, 80))
    assert [m.score for m in matches] == [95, 80, 60]
    assert matches[0].spotify_track_id == TRACK_ID
    assert matches[0].isrc == "GBUM71029604"


def test_no_result_is_empty_not_an_error() -> None:
    assert parse_matches({"status": {"code": 1001, "msg": "No result"}}) == []


def test_api_error_raises_with_code() -> None:
    with pytest.raises(AcrCloudError, match="3014"):
        parse_matches({"status": {"code": 3014, "msg": "Invalid signature"}})


@pytest.mark.anyio
async def test_identify_posts_signed_multipart() -> None:
    seen: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url).encode()
        seen["body"] = request.read()
        return json_response(acr_payload(90))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        matches = await AcrCloudClient("host.example", "key", "secret", http).identify(b"\x00" * 10)

    assert seen["url"] == b"https://host.example/v1/identify"
    for field in (b'name="signature"', b'name="access_key"', b'name="sample"', b'name="timestamp"'):
        assert field in seen["body"]
    assert matches[0].title == "Song 90"
