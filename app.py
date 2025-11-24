from flask import Flask, render_template, send_from_directory, abort
import os
import markdown
from markdown.extensions.extra import ExtraExtension
import urllib.parse
import mdformat
import re


HISTORY_RETENTION = 7

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "static/media"
app.config["MARKDOWN_FOLDER"] = "static/markdown"


def get_files(directory, extensions=None):
    """获取目录及子目录下的文件列表（递归）"""
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs.sort(reverse=True)
        dirs[:] = dirs[:HISTORY_RETENTION]
        cur_files = []
        for filename in filenames:
            # 根据扩展名列表过滤文件
            if extensions:
                if not any(filename.endswith(ext) for ext in extensions):
                    continue
            rel_path = os.path.relpath(os.path.join(root, filename), directory)
            cur_files.append(rel_path)
        if extensions == [".md"]:
            cur_files.sort(key=lambda path: os.path.basename(path).split('_')[0])
        files.extend(cur_files)
    return files


@app.route("/")
def index():
    # 过滤media目录的.wav和.mp4文件
    media_files = get_files(app.config["UPLOAD_FOLDER"], extensions=[".wav", ".mp4"])
    # 过滤markdown目录的.md文件
    markdown_files = get_files(app.config["MARKDOWN_FOLDER"], extensions=[".md"])
    return render_template(
        "index.html",
        media_files=media_files,
        markdown_files=markdown_files,
        media_view_route="media_view",
    )  # Add media_view_route to context


@app.route("/media/<path:filename>")
def media_file(filename):
    # Decode URL-encoded filename
    decoded_filename = urllib.parse.unquote(filename)
    response = send_from_directory(app.config["UPLOAD_FOLDER"], decoded_filename)
    # Add cache control
    response.cache_control.public = True
    response.cache_control.max_age = 300
    return response


@app.route("/media_view/<path:filename>")
def media_view(filename):
    """Render media files with HTML5 player"""
    # Decode URL-encoded filename
    decoded_filename = urllib.parse.unquote(filename)

    # Clean filename: remove leading/trailing whitespace and newlines
    cleaned_filename = decoded_filename.strip().replace("\n", "")

    # Normalize path
    normalized_filename = os.path.normpath(cleaned_filename)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], normalized_filename)
    if not os.path.exists(filepath):
        app.logger.error(f"File not found: {filepath}")
        abort(404)

    # Create URL for the media file
    file_url = f"/media/{urllib.parse.quote(normalized_filename)}"

    return render_template(
        "media.html", filename=normalized_filename, filepath=file_url
    )


def convert_math_delimiters(markdown_content: str) -> str:
    """
    Convert non-standard math delimiters [ ... ] to standard LaTeX delimiters \\[ ... \\]
    for proper MathJax rendering.
    """
    # Pattern to match [ math content ] where math content doesn't contain unescaped brackets
    # This handles both inline and display math using square brackets
    pattern = r'\[\s*(.*?)\s*\]'
    
    def replace_math(match):
        math_content = match.group(1).strip()
        # Check if this looks like a mathematical expression
        # (contains LaTeX commands, operators, etc.)
        if any(char in math_content for char in ['\\', '^', '_', '{', '}', '=', '<', '>', '+', '-', '*', '/']):
            return f'\\[ {math_content} \\]'
        else:
            # Not a math expression, keep original
            return match.group(0)
    
    # Apply the conversion
    converted_content = re.sub(pattern, replace_math, markdown_content, flags=re.DOTALL)
    return converted_content


@app.route("/markdown/<path:filename>")
def render_markdown(filename):
    """渲染Markdown文件并支持LaTeX公式"""
    # Decode URL-encoded filename
    decoded_filename = urllib.parse.unquote(filename)

    # Clean filename: remove leading/trailing whitespace and newlines
    cleaned_filename = decoded_filename.strip().replace("\n", "")

    # Normalize path
    normalized_filename = os.path.normpath(cleaned_filename)

    filepath = os.path.join(app.config["MARKDOWN_FOLDER"], normalized_filename)
    if not os.path.exists(filepath):
        app.logger.error(f"File not found: {filepath}")
        abort(404)

    # 读取Markdown内容
    with open(filepath, "r", encoding="utf-8") as f:
        md_content = f.read()

    # Step 1: 转换数学公式分隔符 [ ... ] 为 \[ ... \]
    md_content = convert_math_delimiters(md_content)

    # Step 2: 使用 mdformat 格式化 Markdown 内容
    formatted_md_content = mdformat.text(md_content, extensions={'gfm'})

    # Step 3: Use the mdformat output directly.
    final_md_content = formatted_md_content

    # 配置Markdown扩展
    extensions = [ExtraExtension(), 'markdown.extensions.nl2br', 'markdown.extensions.tables']

    # 转换为HTML
    md = markdown.Markdown(extensions=extensions)
    html_content = md.convert(final_md_content)

    return render_template("markdown.html", content=html_content, filename=filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
