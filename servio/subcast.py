"""Browse the subcast media cache and serve its transcripts as WebVTT.

The cache (``SUBSCAST_FOLDER``, ``~/.cache/subcast`` by default) holds one
directory per source, and per media key:

* ``<key>.mp3`` / ``<key>.mp4`` - the media file itself;
* ``<key>.srt`` - the transcript, on the media timeline (seconds from 0);
* ``<key>.cues.json`` - the same cues as ``{"start", "end", "text"}`` objects,
  written when no SRT sidecar was kept;
* ``<key>.position``, ``<key>.segments.json``, ``<key>.chapters.txt`` - playback
  position and chapter data;
* ``listings/*.json`` and ``<key>.meta.json`` - titles (and durations) keyed by
  the media key.

Only the media files are listed, and subtitle conversion preserves cue timing
exactly: WebVTT keeps the SRT/SRT-derived millisecond timestamps untouched, so
browsers that drive cue display from the media clock stay in sync.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from flask import current_app

#: Sidecars that contain the transcript, in order of preference.
SUBTITLE_SUFFIXES = (".srt", ".cues.json")

#: Media types served to the browser, independent of the host's mime database.
_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
}

#: Directories inside the cache root that never hold media.
_SKIPPED_DIRS = {"listings"}


def content_type(filename: str) -> str:
    """HTTP media type for *filename* (``.mp3``/``.mp4`` are the only media)."""
    return _CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


class TitleInfo(NamedTuple):
    title: str
    duration: float | None


@dataclass(frozen=True)
class MediaEntry:
    """One playable file from the cache."""

    source: str
    key: str
    filename: str  # relative to the cache root, e.g. "rte/519ef8f5-....mp3"
    title: str
    kind: str  # "audio" | "video"
    duration: float | None
    size: int
    modified: float
    has_subtitles: bool

    @property
    def is_video(self) -> bool:
        return self.kind == "video"

    @property
    def name(self) -> str:
        """File name inside its source directory, e.g. ``519ef8f5-....mp3``."""
        return self.filename.rsplit("/", 1)[-1]

    @property
    def duration_text(self) -> str:
        if not self.duration:
            return ""
        seconds = int(self.duration)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


# Titles are read from every listing/meta file in the cache, so the parsed
# result is memoised per root and invalidated by the stat signature of those
# files.
_TITLE_CACHE: dict[str, tuple[tuple, dict[str, TitleInfo]]] = {}
_TITLE_CACHE_LIMIT = 8


def _source_dirs(root: Path) -> list[Path]:
    """Return the media directories of *root*, excluding metadata-only ones."""
    if not root.is_dir():
        return []
    return sorted(
        entry
        for entry in root.iterdir()
        if entry.is_dir()
        and not entry.name.startswith(".")
        and entry.name not in _SKIPPED_DIRS
    )


def list_media(folder: str | Path) -> list[MediaEntry]:
    """List playable files under *folder*, newest first.

    The whole result is ordered by modification time (descending), which is also
    the order inside each source: grouping the entries by source keeps them
    newest first, and the groups themselves appear with the source that changed
    most recently at the top.
    """
    root = Path(folder)
    if not root.is_dir():
        current_app.logger.warning("Subcast folder not found: %s", root)
        return []

    extensions = _extensions()
    directories = _source_dirs(root)
    titles = _titles(root, directories)

    entries: list[MediaEntry] = []
    for directory in directories:
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in extensions:
                entries.append(_entry(root, path, titles))

    entries.sort(key=lambda entry: entry.modified, reverse=True)
    return entries


def entry_for(folder: str | Path, source: str, key: str) -> MediaEntry | None:
    """Return the entry for ``<source>/<key>`` or ``None`` when it has no media."""
    media_path = find_media(folder, source, key)
    if media_path is None:
        return None
    root = Path(folder)
    return _entry(root, media_path, _titles(root, _source_dirs(root)))


def find_media(folder: str | Path, source: str, key: str) -> Path | None:
    """Resolve ``<source>/<key>`` to a media file with an allowed extension."""
    if not source or "/" in source or "\\" in source or source in {".", ".."}:
        return None
    if not key or "/" in key or "\\" in key or key in {".", ".."}:
        return None

    directory = Path(folder) / source
    for extension in _extensions():
        candidate = directory / f"{key}{extension}"
        if candidate.is_file():
            return candidate
    return None


def is_media_filename(filename: str, extensions: list[str]) -> bool:
    """Whether *filename* carries one of the servable media extensions."""
    allowed = {extension.lower() for extension in extensions}
    return Path(filename).suffix.lower() in allowed


def has_subtitles(directory: Path, key: str) -> bool:
    return _subtitle_file(directory, key) is not None


def vtt_for(directory: Path, key: str) -> str | None:
    """Build WebVTT for ``<key>`` from its SRT sidecar, else from ``cues.json``."""
    sidecar = _subtitle_file(directory, key)
    if sidecar is None:
        return None

    if sidecar.suffix == ".json":
        try:
            cues = json.loads(sidecar.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            current_app.logger.error("Unreadable cues file %s: %s", sidecar, error)
            return None
        if not isinstance(cues, list):
            current_app.logger.error("Unexpected cues format in %s", sidecar)
            return None
        return cues_to_vtt(cues)

    try:
        return srt_to_vtt(sidecar.read_text(encoding="utf-8-sig", errors="replace"))
    except OSError as error:
        current_app.logger.error("Unreadable subtitle file %s: %s", sidecar, error)
        return None


# ---------------------------------------------------------------------------
# WebVTT conversion. Timestamps are copied verbatim (only the SubRip decimal
# comma becomes a dot) so a converted file cannot drift from the media clock.
# ---------------------------------------------------------------------------

_CUE_TIMESTAMP_RE = re.compile(r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})")
_CUE_INDEX_RE = re.compile(r"\d{1,9}")
# WebVTT inline markup and character references that must survive escaping.
_VTT_MARKUP_RE = re.compile(
    r"</?(?:b|i|u|c|v|lang|ruby|rt)(?:\.[^>\s]*)?(?:\s[^>]*)?>"
    r"|&(?:amp|lt|gt|lrm|rlm|nbsp|#\d{1,7}|#x[0-9a-fA-F]{1,6});"
)
_STASH_RE = re.compile(r"\x00(\d+)\x00")


def srt_to_vtt(text: str) -> str:
    """Convert SubRip text into WebVTT with an unchanged cue timeline.

    Cue numbers are dropped (WebVTT does not need them and a bare number is
    ambiguous with cue text), cue settings on the timestamp line are kept, and
    cue blocks that carry no text are omitted because they render nothing.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").split("\n")
    cues: list[list[str]] = []
    pending: list[str] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if pending:
                cues.append(pending)
                pending = []
        elif _CUE_INDEX_RE.fullmatch(stripped) and _followed_by_timestamp(lines, index):
            continue
        elif "-->" in stripped:
            pending.append(_CUE_TIMESTAMP_RE.sub(_vtt_timestamp, stripped))
        else:
            pending.append(_escape_cue_text(line.rstrip()))
    if pending:
        cues.append(pending)

    blocks: list[str] = ["WEBVTT", ""]
    for cue in cues:
        if len(cue) > 1 and "-->" in cue[0]:
            blocks.extend(cue)
            blocks.append("")

    return "\n".join(blocks).rstrip("\n") + "\n"


def cues_to_vtt(cues: list[dict]) -> str:
    """Build WebVTT from ``cues.json`` timecodes (float seconds).

    Cues without usable bounds or text are dropped; the caller decides whether a
    transcript is complete enough to serve.
    """
    blocks: list[str] = ["WEBVTT", ""]

    for cue in cues:
        try:
            start = float(cue["start"])
            end = float(cue["end"])
        except (KeyError, TypeError, ValueError):
            continue
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        blocks.append(
            f"{_seconds_to_timestamp(start)} --> {_seconds_to_timestamp(end)}"
        )
        blocks.append(_escape_cue_text(text))
        blocks.append("")

    return "\n".join(blocks).rstrip("\n") + "\n"


def _vtt_timestamp(match: re.Match[str]) -> str:
    hours, minutes, seconds, milliseconds = match.groups()
    return f"{int(hours):02d}:{minutes}:{seconds}.{milliseconds.ljust(3, '0')[:3]}"


def _seconds_to_timestamp(value: float) -> str:
    total_ms = max(0, round(value * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _escape_cue_text(text: str) -> str:
    """Escape cue text for the WebVTT cue-text grammar.

    Stray ``<``/``&`` would otherwise start a tag or reference; the small set of
    inline tags and character references WebVTT allows is passed through.
    """
    kept: list[str] = []

    def _keep(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return f"\x00{len(kept) - 1}\x00"

    stashed = _VTT_MARKUP_RE.sub(_keep, text)
    escaped = stashed.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _STASH_RE.sub(lambda match: kept[int(match.group(1))], escaped)


def _followed_by_timestamp(lines: list[str], index: int) -> bool:
    for candidate in lines[index + 1 :]:
        if candidate.strip():
            return "-->" in candidate
    return False


# ---------------------------------------------------------------------------
# Cache metadata.
# ---------------------------------------------------------------------------


def _subtitle_file(directory: Path, key: str) -> Path | None:
    for suffix in SUBTITLE_SUFFIXES:
        candidate = directory / f"{key}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _extensions() -> list[str]:
    return [
        extension.lower()
        for extension in current_app.config["SUBSCAST_MEDIA_EXTENSIONS"]
    ]


def _entry(root: Path, path: Path, titles: dict[str, TitleInfo]) -> MediaEntry:
    extension = path.suffix.lower()
    key = path.stem
    stat = path.stat()
    info = titles.get(f"{path.parent.name}/{key}")

    return MediaEntry(
        source=path.parent.name,
        key=key,
        filename=str(path.relative_to(root)),
        title=info.title if info else key,
        kind="video" if extension in _video_extensions() else "audio",
        duration=info.duration if info else None,
        size=stat.st_size,
        modified=stat.st_mtime,
        has_subtitles=has_subtitles(path.parent, key),
    )


def _video_extensions() -> list[str]:
    return [
        extension.lower()
        for extension in current_app.config["SUBSCAST_VIDEO_EXTENSIONS"]
    ]


def _titles(root: Path, directories: list[Path]) -> dict[str, TitleInfo]:
    """Map ``<source>/<key>`` to its title, preferring listing metadata."""
    listing_files = [
        path
        for directory in directories
        for path in sorted((directory / "listings").glob("*.json"))
    ]
    meta_files = [
        path
        for directory in directories
        for path in sorted(directory.glob("*.meta.json"))
    ]

    signature = _stat_signature(listing_files + meta_files)
    cached = _TITLE_CACHE.get(str(root))
    if cached is not None and cached[0] == signature:
        return cached[1]

    titles: dict[str, TitleInfo] = {}
    for path in listing_files:
        data = _read_json(path)
        for item in data.get("items") or []:
            key = item.get("key")
            title = item.get("title")
            if key and title:
                titles[f"{path.parent.parent.name}/{key}"] = TitleInfo(
                    str(title), _as_duration(item.get("duration"))
                )
    for path in meta_files:
        data = _read_json(path)
        title = data.get("title")
        if title:
            key = path.name[: -len(".meta.json")]
            titles.setdefault(
                f"{path.parent.name}/{key}",
                TitleInfo(str(title), _as_duration(data.get("duration"))),
            )

    _TITLE_CACHE[str(root)] = (signature, titles)
    if len(_TITLE_CACHE) > _TITLE_CACHE_LIMIT:
        _TITLE_CACHE.pop(next(iter(_TITLE_CACHE)))
    return titles


def _stat_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    """Cheap invalidation key for memoised cache metadata."""
    entries: list[tuple[str, int, int]] = []
    for path in paths:
        stat = path.stat()
        entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        current_app.logger.warning("Unreadable metadata file %s: %s", path, error)
        return {}
    return data if isinstance(data, dict) else {}


def _as_duration(value) -> float | None:
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None
