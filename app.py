from flask import Flask, render_template, send_from_directory, abort
import os
import markdown
from markdown.extensions.extra import ExtraExtension
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.toc import TocExtension
from processor import MathPreprocessor, MathPostprocessor
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


def remove_mdformat_list_blank_lines(markdown_content: str) -> str:
    """
    Removes blank lines introduced by mdformat that break ordered list numbering 
    when an unordered list is nested directly within an ordered list item.
    This function now uses a stateful, line-by-line approach to correctly identify
    and reformat nested lists.
    """
    new_lines = []
    lines = markdown_content.split('\n')
    
    # State variables
    in_ordered_list_item = False
    current_ol_indent = 0
    current_ol_marker_len = 0 # e.g., for '1. ', this is 3

    for line_idx, line in enumerate(lines):
        original_indent_match = re.match(r'^\\s*', line)
        original_indent_len = len(original_indent_match.group(0)) if original_indent_match else 0
        content = line.lstrip()

        # Try to match an ordered list item (e.g., '1. Text')
        ol_match = re.match(r'^([0-9]+\.[ \t]+)(.*)', content)

        if ol_match:
            # Found an ordered list item
            in_ordered_list_item = True
            current_ol_indent = original_indent_len
            current_ol_marker_len = len(ol_match.group(1)) # e.g., '1. ' is 3 chars
            new_lines.append(line)
        elif in_ordered_list_item and not content.strip():
            # This is a blank line directly after an ordered list item. We skip it.
            # mdformat often inserts these, breaking nesting.
            continue
        elif in_ordered_list_item and (content.startswith('-') or content.startswith('*')):
            # This is a potential nested unordered list item.
            # We need to apply the correct indentation.
            # Required indent for nested UL = current_ol_indent + current_ol_marker_len + 4 spaces.
            # E.g., if OL is at column 0 ('1. '), then content starts at column 3. Nested UL needs 3+4=7 spaces.
            required_nested_indent_len = current_ol_indent + current_ol_marker_len + 4
            
            # Get the actual content of the unordered list item (without its current marker and indent)
            ul_item_match = re.match(r'^[-*+][ \t]+(.*)', content)
            if ul_item_match:
                ul_content = ul_item_match.group(1)
                # Reconstruct the line with the correct indentation
                corrected_line = ' ' * required_nested_indent_len + '- ' + ul_content
                new_lines.append(corrected_line)
            else:
                # Fallback if somehow a malformed UL item, just append original
                new_lines.append(line)
        else:
            # Not an OL item, not a blank line after OL, not a nested UL item.
            # Reset state if it's not a continuation of an OL.
            # We need to be careful not to reset if it's a continuation paragraph of the OL item itself.
            # A heuristic: if it's indented more than the OL, it might be a continuation.
            if not ol_match and original_indent_len <= current_ol_indent:
                in_ordered_list_item = False # Reset if not an OL item and not indented as a continuation
            new_lines.append(line)
            
    return '\n'.join(new_lines)


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

    # Step 1: 运行 MathPreprocessor 保护数学公式
    math_preprocessor = MathPreprocessor()
    md_content_protected = '\n'.join(math_preprocessor.run(md_content.split('\n')))


    # Step 2: 使用 mdformat 格式化 Markdown 内容 (在公式保护之后运行)
    formatted_md_content = mdformat.text(md_content_protected, extensions={'gfm'})


    # Step 3: 后处理：移除 mdformat 引入的、破坏有序列表编号的空行
    final_md_content = remove_mdformat_list_blank_lines(formatted_md_content)


    # 配置Markdown扩展 (不再需要 MathProtectExtension)
    extensions = [ExtraExtension()]

    # 转换为HTML
    md = markdown.Markdown(extensions=extensions)
    html_content = md.convert(final_md_content)


    # Step 4: 运行 MathPostprocessor 恢复数学公式
    math_postprocessor = MathPostprocessor(math_preprocessor.math_blocks)
    final_html_content = math_postprocessor.run(html_content)

    # Final cleanup: Remove any remaining '@@' not part of a math block placeholder
    final_html_content = re.sub(r'@@(?!MATH_BLOCK_\\d+)', '', final_html_content)

    return render_template("markdown.html", content=final_html_content, filename=filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)