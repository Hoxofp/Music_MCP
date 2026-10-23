"""Structured tool outputs. MCP clients receive these as JSON with a published output schema."""

from pydantic import BaseModel, Field


class Track(BaseModel):
    id: str = Field(description="Spotify track ID")
    uri: str = Field(description="Spotify URI, e.g. spotify:track:<id>")
    name: str
    artists: list[str]
    album: str | None = None
    url: str | None = Field(default=None, description="Open-in-Spotify link")


class SongMatch(BaseModel):
    title: str
    artists: list[str]
    album: str | None = None
    release_date: str | None = None
    score: int = Field(description="ACRCloud confidence score, 0-100")
    isrc: str | None = None
    spotify_track_id: str | None = Field(
        default=None, description="Present when ACRCloud links the match to Spotify"
    )
    play_offset_ms: int | None = Field(
        default=None, description="Where in the original recording the sample matched"
    )


class IdentifyResult(BaseModel):
    file: str
    matched: bool
    best: SongMatch | None = None
    alternatives: list[SongMatch] = Field(default_factory=list)


class Playlist(BaseModel):
    id: str
    name: str
    url: str | None = None
    public: bool | None = None
    track_count: int | None = None


class LibraryUpdate(BaseModel):
    saved: int
    uris: list[str]


class PlaylistUpdate(BaseModel):
    playlist_id: str
    added: int
    snapshot_id: str | None = None
