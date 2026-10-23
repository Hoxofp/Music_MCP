"""The MCP server: tools for identifying songs and saving them to Spotify."""

import json
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass

import anyio
import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .acrcloud import AcrCloudClient, AcrCloudError
from .audio import AudioError, load_sample, resolve_audio_path
from .config import Settings
from .models import IdentifyResult, LibraryUpdate, Playlist, PlaylistUpdate, SongMatch, Track
from .spotify import SpotifyClient, SpotifyError, TokenStore

INSTRUCTIONS = """\
Identify music from local audio files and manage the user's Spotify library.
Typical flow: identify_song(path) -> if the best match has no spotify_track_id, search_tracks
with "title artist" -> save_to_library or add_to_playlist. Ask before modifying the library
when the match score is below 70.
"""

HISTORY_SIZE = 50


@dataclass
class AppContext:
    settings: Settings
    acrcloud: AcrCloudClient | None
    spotify: SpotifyClient


@asynccontextmanager
async def default_context() -> AsyncIterator[AppContext]:
    settings = Settings.from_env()
    async with httpx.AsyncClient(timeout=30) as http:
        acrcloud = None
        if settings.acr_host and settings.acr_access_key and settings.acr_access_secret:
            acrcloud = AcrCloudClient(
                settings.acr_host, settings.acr_access_key, settings.acr_access_secret, http
            )
        spotify = SpotifyClient(
            settings.spotify_client_id,
            settings.spotify_client_secret,
            TokenStore(settings.token_path),
            http,
        )
        yield AppContext(settings=settings, acrcloud=acrcloud, spotify=spotify)


def build_server(
    make_context: Callable[[], AbstractAsyncContextManager[AppContext]] = default_context,
) -> MCPServer:
    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[AppContext]:
        async with make_context() as app:
            yield app

    mcp = MCPServer(
        "music-mcp",
        title="Music Recognition + Spotify",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/Hoxofp/Music_MCP",
        lifespan=lifespan,
    )

    # Per-process history (stdio serves one user); exposed read-only as a resource.
    history: deque[SongMatch] = deque(maxlen=HISTORY_SIZE)

    def app_of(ctx: Context[AppContext]) -> AppContext:
        return ctx.request_context.lifespan_context

    @contextmanager
    def tool_errors() -> Iterator[None]:
        """Report expected failures to the model as tool errors it can act on."""
        try:
            yield
        except (SpotifyError, AudioError, AcrCloudError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Identify song", read_only_hint=True, open_world_hint=True
        )
    )
    async def identify_song(
        path: str, ctx: Context[AppContext], start_seconds: float = 0
    ) -> IdentifyResult:
        """Identify the song playing in a local audio file (mp3, wav, m4a, flac, ogg...).

        Args:
            path: Absolute path to the audio file.
            start_seconds: Where to take the ~12 s sample from. Try 30-60 if the intro fails.
        """
        app = app_of(ctx)
        if app.acrcloud is None:
            raise ToolError(
                "ACRCloud is not configured: set ACRCLOUD_HOST, _ACCESS_KEY, _ACCESS_SECRET."
            )
        with tool_errors():
            file = resolve_audio_path(path, app.settings.audio_dir)
            sample = await anyio.to_thread.run_sync(load_sample, file, start_seconds)
            matches = await app.acrcloud.identify(sample)
        if matches:
            history.appendleft(matches[0])
        return IdentifyResult(
            file=file.name,
            matched=bool(matches),
            best=matches[0] if matches else None,
            alternatives=matches[1:5],
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search tracks", read_only_hint=True, open_world_hint=True
        )
    )
    async def search_tracks(query: str, ctx: Context[AppContext], limit: int = 5) -> list[Track]:
        """Search Spotify for tracks, e.g. "Bohemian Rhapsody Queen". limit: 1-20."""
        with tool_errors():
            return await app_of(ctx).spotify.search_tracks(query, max(1, min(limit, 20)))

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Save to Liked Songs",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        )
    )
    async def save_to_library(track_ids: list[str], ctx: Context[AppContext]) -> LibraryUpdate:
        """Save tracks to the user's Spotify library (Liked Songs). Accepts IDs, URIs or links."""
        with tool_errors():
            uris = await app_of(ctx).spotify.save_to_library(track_ids)
        await ctx.info({"message": "saved to library", "count": len(uris)})
        return LibraryUpdate(saved=len(uris), uris=uris)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Create playlist", read_only_hint=False, destructive_hint=False
        )
    )
    async def create_playlist(
        name: str, ctx: Context[AppContext], description: str = "", public: bool = False
    ) -> Playlist:
        """Create a playlist owned by the logged-in user. Private by default."""
        with tool_errors():
            return await app_of(ctx).spotify.create_playlist(name, description, public)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Add to playlist", read_only_hint=False, destructive_hint=False
        )
    )
    async def add_to_playlist(
        playlist_id: str, track_ids: list[str], ctx: Context[AppContext]
    ) -> PlaylistUpdate:
        """Append tracks to a playlist. Not idempotent: calling twice adds duplicates."""
        with tool_errors():
            snapshot = await app_of(ctx).spotify.add_to_playlist(playlist_id, track_ids)
        return PlaylistUpdate(playlist_id=playlist_id, added=len(track_ids), snapshot_id=snapshot)

    @mcp.tool(annotations=ToolAnnotations(title="List playlists", read_only_hint=True))
    async def list_playlists(ctx: Context[AppContext], limit: int = 20) -> list[Playlist]:
        """List the logged-in user's playlists (owned and followed). limit: 1-50."""
        with tool_errors():
            return await app_of(ctx).spotify.list_playlists(max(1, min(limit, 50)))

    @mcp.resource(
        "music://history",
        name="recent_identifications",
        description="Songs identified during this session, newest first",
        mime_type="application/json",
    )
    def recent_identifications() -> str:
        return json.dumps([m.model_dump() for m in history], ensure_ascii=False)

    @mcp.prompt(title="Identify and save")
    def identify_and_save(path: str, playlist: str = "Liked Songs") -> str:
        """Identify a recording and file it into a playlist."""
        return (
            f"Identify the song in {path!r}. If the score is 70 or higher, save it to {playlist!r} "
            "(create the playlist if it does not exist). Otherwise show me the top matches and ask."
        )

    return mcp


mcp = build_server()
