import urllib.parse

from flask import (
    Flask,
    Response,
    abort,
    render_template,
    send_from_directory,
    url_for,
)

from servio import files, subcast
from servio.markdown import render_markdown as markdown_to_html


def register_routes(app: Flask) -> None:
    @app.route("/")
    def index():
        media_files = files.list_files(
            app.config["UPLOAD_FOLDER"], extensions=app.config["MEDIA_EXTENSIONS"]
        )

        mixed_extensions = (
            app.config["MARKDOWN_EXTENSIONS"]
            + app.config["IMAGE_EXTENSIONS"]
            + app.config["AUDIO_EXTENSIONS"]
        )
        markdown_files = files.list_files(
            app.config["MARKDOWN_FOLDER"], extensions=mixed_extensions
        )

        return render_template(
            "index.html",
            media_files=media_files,
            markdown_files=markdown_files,
            media_view_route="media_view",
        )

    @app.route("/media/<path:filename>")
    def media_file(filename):
        response = send_from_directory(
            app.config["UPLOAD_FOLDER"], urllib.parse.unquote(filename)
        )
        response.cache_control.public = True
        response.cache_control.max_age = 300
        return response

    @app.route("/media_view/<path:filename>")
    def media_view(filename):
        _, normalized = files.resolve_safe_path(app.config["UPLOAD_FOLDER"], filename)
        return render_template("media.html", filename=normalized)

    @app.route("/assets/<path:filename>")
    def markdown_asset_file(filename):
        response = send_from_directory(
            app.config["MARKDOWN_FOLDER"], urllib.parse.unquote(filename)
        )
        response.cache_control.public = True
        response.cache_control.max_age = 300
        return response

    @app.route("/assets_view/<path:filename>")
    def markdown_asset_view(filename):
        _, normalized = files.resolve_safe_path(app.config["MARKDOWN_FOLDER"], filename)
        file_url = url_for("markdown_asset_file", filename=normalized)
        return render_template("media.html", filename=normalized, file_url=file_url)

    @app.route("/markdown/<path:filename>")
    def render_markdown(filename):
        filepath, _ = files.resolve_safe_path(app.config["MARKDOWN_FOLDER"], filename)

        with open(filepath, "r", encoding="utf-8") as handle:
            content = handle.read()

        return render_template(
            "markdown.html",
            content=markdown_to_html(content),
            filename=filename,
        )

    # Subcast cache: browse the CLI's media cache, stream it with byte-range
    # support and expose each transcript as WebVTT for the player's <track>.

    @app.route("/subcast")
    def subcast_index():
        entries = subcast.list_media(app.config["SUBSCAST_FOLDER"])
        groups: dict[str, list[subcast.MediaEntry]] = {}
        for entry in entries:
            groups.setdefault(entry.source, []).append(entry)

        return render_template(
            "subcast.html",
            groups=groups,
            total=len(entries),
            folder=app.config["SUBSCAST_FOLDER"],
        )

    @app.route("/subcast/media/<source>/<path:filename>")
    def subcast_media(source, filename):
        if not subcast.is_media_filename(
            filename, app.config["SUBSCAST_MEDIA_EXTENSIONS"]
        ):
            abort(404)

        response = send_from_directory(
            app.config["SUBSCAST_FOLDER"],
            f"{source}/{urllib.parse.unquote(filename)}",
            conditional=True,
            mimetype=subcast.content_type(filename),
        )
        response.cache_control.public = True
        response.cache_control.max_age = 300
        return response

    @app.route("/subcast/subtitles/<source>/<key>.vtt")
    def subcast_subtitles(source, key):
        media_path = subcast.find_media(app.config["SUBSCAST_FOLDER"], source, key)
        if media_path is None:
            abort(404)

        vtt = subcast.vtt_for(media_path.parent, key)
        if vtt is None:
            abort(404)

        response = Response(vtt, mimetype="text/vtt")
        response.cache_control.public = True
        response.cache_control.max_age = 300
        return response

    @app.route("/subcast/player/<source>/<key>")
    def subcast_player(source, key):
        entry = subcast.entry_for(app.config["SUBSCAST_FOLDER"], source, key)
        if entry is None:
            abort(404)

        return render_template(
            "subcast_player.html",
            entry=entry,
            media_url=url_for(
                "subcast_media", source=entry.source, filename=entry.name
            ),
            mimetype=subcast.content_type(entry.name),
            subtitles_url=(
                url_for("subcast_subtitles", source=entry.source, key=entry.key)
                if entry.has_subtitles
                else None
            ),
        )
