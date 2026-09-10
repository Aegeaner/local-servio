import urllib.parse

from flask import Flask, render_template, send_from_directory, url_for

from servio import files
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
