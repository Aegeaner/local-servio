import os
import urllib.parse

from flask import abort, current_app


def list_files(directory: str, extensions: list[str] | None = None) -> list[str]:
    """Recursively list files under *directory*, optionally filtered by extension.

    Subdirectories are ordered most-recent-first and limited to
    ``HISTORY_RETENTION`` entries per level (intended for date-stamped
    directories so only recent history is retained).
    """
    if not os.path.exists(directory):
        current_app.logger.warning("Directory not found: %s", directory)
        return []

    retention = current_app.config["HISTORY_RETENTION"]
    files: list[str] = []

    for root, dirs, filenames in os.walk(directory):
        dirs.sort(reverse=True)
        if retention > 0:
            dirs[:] = dirs[:retention]

        matches = [
            os.path.relpath(os.path.join(root, name), directory)
            for name in filenames
            if not extensions
            or any(name.lower().endswith(ext.lower()) for ext in extensions)
        ]
        matches.sort()
        files.extend(matches)

    return files


def resolve_safe_path(directory: str, filename: str) -> tuple[str, str]:
    """Validate *filename* resolves inside *directory* and return its paths.

    Returns ``(absolute_path, relative_path)`` or aborts with 404 when the path
    is unsafe or the file does not exist.
    """
    decoded = urllib.parse.unquote(filename)
    cleaned = decoded.strip().replace("\n", "")

    base = os.path.abspath(directory)
    target = os.path.abspath(os.path.join(base, cleaned))

    if os.path.commonpath([base, target]) != base:
        current_app.logger.warning("Attempted path traversal: %s", cleaned)
        abort(404)

    if not os.path.isfile(target):
        current_app.logger.error("File not found: %s", target)
        abort(404)

    return target, os.path.relpath(target, base)
