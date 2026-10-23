"""Loading a short recognition sample from a local audio file."""

from pathlib import Path

ALLOWED_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".mp4"}
MAX_FILE_BYTES = 200 * 1024 * 1024
# ACRCloud recommends 10-15 s samples; without pydub we send a byte range of roughly that size.
FALLBACK_SAMPLE_BYTES = 1024 * 1024


class AudioError(Exception):
    pass


def resolve_audio_path(path: str, allowed_dir: Path | None) -> Path:
    """Validate a path the model asked us to read. Restrict to `allowed_dir` when configured."""
    file = Path(path).expanduser().resolve()
    if allowed_dir is not None and not file.is_relative_to(allowed_dir):
        raise AudioError(f"{file} is outside MUSIC_MCP_AUDIO_DIR ({allowed_dir})")
    if not file.is_file():
        raise AudioError(f"No such file: {file}")
    if file.suffix.lower() not in ALLOWED_SUFFIXES:
        raise AudioError(
            f"Unsupported audio type {file.suffix!r}; use one of {sorted(ALLOWED_SUFFIXES)}"
        )
    if file.stat().st_size > MAX_FILE_BYTES:
        raise AudioError(f"{file.name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    return file


def load_sample(file: Path, start_seconds: float = 0, seconds: float = 12) -> bytes:
    """Return ~`seconds` of audio from `start_seconds`; MP3-encoded when pydub is installed."""
    try:
        from pydub import AudioSegment  # optional extra: music-mcp[audio]
    except ImportError:
        return _byte_range_sample(file, start_seconds)

    try:
        audio = AudioSegment.from_file(file)
    # pydub raises bare exceptions when ffmpeg is missing or decoding fails
    except Exception as exc:
        raise AudioError(f"Could not decode {file.name} (is ffmpeg installed?): {exc}") from exc
    start_ms = int(start_seconds * 1000)
    if start_ms >= len(audio):
        raise AudioError(
            f"start_seconds={start_seconds} is past the end ({len(audio) / 1000:.0f}s)"
        )
    clip = audio[start_ms : start_ms + int(seconds * 1000)]
    return clip.export(format="mp3", bitrate="128k").read()


def _byte_range_sample(file: Path, start_seconds: float) -> bytes:
    # Frame-based streams (MP3/ADTS) stay decodable when cut mid-file; containers need a header.
    if start_seconds and file.suffix.lower() not in {".mp3", ".aac"}:
        raise AudioError(
            "Seeking inside this format needs the [audio] extra: pip install music-mcp[audio]"
        )
    # shortcut: assumes ~128 kbps when seeking without a decoder; [audio] extra gives exact cuts.
    offset = int(start_seconds * 16_000)
    with file.open("rb") as f:
        if offset:
            f.seek(offset)
        return f.read(FALLBACK_SAMPLE_BYTES)
