from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    UPLOAD_FOLDER = str(BASE_DIR / "static" / "media")
    MARKDOWN_FOLDER = str(BASE_DIR / "static" / "markdown")
    HISTORY_RETENTION = 7

    MEDIA_EXTENSIONS = [".wav", ".mp4", ".mp3"]
    AUDIO_EXTENSIONS = [".wav", ".mp3"]
    IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif"]
    MARKDOWN_EXTENSIONS = [".md"]
