"""Settings read from the environment (optionally a local .env file)."""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, no overrides of variables already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _default_token_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "music-mcp" / "spotify_token.json"


@dataclass(frozen=True)
class Settings:
    acr_host: str | None
    acr_access_key: str | None
    acr_access_secret: str | None
    spotify_client_id: str | None
    spotify_client_secret: str | None
    spotify_redirect_uri: str
    token_path: Path
    audio_dir: Path | None

    @classmethod
    def from_env(cls, dotenv: Path | None = Path(".env")) -> "Settings":
        if dotenv is not None:
            _load_dotenv(dotenv)
        env = os.environ.get
        audio_dir = env("MUSIC_MCP_AUDIO_DIR")
        return cls(
            acr_host=env("ACRCLOUD_HOST"),
            acr_access_key=env("ACRCLOUD_ACCESS_KEY"),
            acr_access_secret=env("ACRCLOUD_ACCESS_SECRET"),
            spotify_client_id=env("SPOTIFY_CLIENT_ID"),
            spotify_client_secret=env("SPOTIFY_CLIENT_SECRET"),
            spotify_redirect_uri=env("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            token_path=Path(env("MUSIC_MCP_TOKEN_PATH") or _default_token_path()),
            audio_dir=Path(audio_dir).resolve() if audio_dir else None,
        )
