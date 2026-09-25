import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    UPLOAD_FOLDER = str(BASE_DIR / "static" / "media")
    MARKDOWN_FOLDER = str(BASE_DIR / "static" / "markdown")
    # Media cache written by the subcast CLI: one directory per source,
    # ``<key>.mp3`` / ``<key>.mp4`` plus timeline-aligned sidecars.
    SUBSCAST_FOLDER = os.path.expanduser(
        os.environ.get("SUBSCAST_FOLDER", "~/.cache/subcast")
    )
    HISTORY_RETENTION = 7

    MEDIA_EXTENSIONS = [".wav", ".mp4", ".mp3"]
    AUDIO_EXTENSIONS = [".wav", ".mp3"]
    IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif"]
    MARKDOWN_EXTENSIONS = [".md"]

    SUBSCAST_MEDIA_EXTENSIONS = [".mp3", ".mp4"]
    SUBSCAST_VIDEO_EXTENSIONS = [".mp4"]
