from flask import Flask, render_template, send_from_directory, abort, url_for
import os
import markdown
from markdown.extensions.extra import ExtraExtension
import urllib.parse
import re
import logging
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    UPLOAD_FOLDER = "static/media"
    MARKDOWN_FOLDER = "static/markdown"
    HISTORY_RETENTION = 7
    # Extensions configuration
    MEDIA_EXTENSIONS = [".wav", ".mp4"]
    IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif"]
    MARKDOWN_EXTENSIONS = [".md"]

app = Flask(__name__)
app.config.from_object(Config)

def get_files(directory, extensions=None):
    """
    Recursively get files from a directory.    
    Args:
        directory (str): The directory to search.
        extensions (list): List of allowed file extensions (e.g., ['.md']).        
    Returns:
        list: List of relative file paths.
    """
    files = []
    # Walk safely
    if not os.path.exists(directory):
        logger.warning(f"Directory not found: {directory}")
        return files

    for root, dirs, filenames in os.walk(directory):
        # Sort directories and keep only the top N (assumed specifically for history retention)
        dirs.sort(reverse=True)
        if app.config["HISTORY_RETENTION"] > 0:
            dirs[:] = dirs[:app.config["HISTORY_RETENTION"]]
            
        cur_files = []
        for filename in filenames:
            if extensions:
                if not any(filename.endswith(ext) for ext in extensions):
                    continue
            rel_path = os.path.relpath(os.path.join(root, filename), directory)
            cur_files.append(rel_path)
            
        # Special sorting for markdown files (business logic)
        # Sort by the part before the first underscore
        if extensions == app.config["MARKDOWN_EXTENSIONS"]:
             try:
                 cur_files.sort(key=lambda path: os.path.basename(path).split('_')[0])
             except IndexError:
                 # Fallback if filename doesn't have an underscore
                 cur_files.sort()
        else:
            cur_files.sort()
                 
        files.extend(cur_files)
    return files

def get_safe_path(directory_config_key, filename):
    """
    Sanitize filename and resolve absolute path.    
    Args:
        directory_config_key (str): The config key for the base directory (e.g., 'UPLOAD_FOLDER').
        filename (str): The potentially unsafe filename/path from URL.        
    Returns:
        tuple: (absolute_filepath, normalized_filename)
        Raises 404 if file does not exist or path is unsafe.
    """
    directory = app.config[directory_config_key]
    
    # Decode URL-encoded filename
    decoded_filename = urllib.parse.unquote(filename)

    # Clean filename: remove leading/trailing whitespace and newlines
    cleaned_filename = decoded_filename.strip().replace("\n", "")

    # Normalize path to prevent traversal (e.g. ..)
    normalized_filename = os.path.normpath(cleaned_filename)
    
    # Ensure the path is relative and doesn't escape the directory
    # (os.path.join handles relative paths correctly, but we must ensure no traversal up)
    if normalized_filename.startswith("..") or normalized_filename.startswith("/"):
        logger.warning(f"Attempted path traversal: {normalized_filename}")
        abort(404)

    filepath = os.path.join(directory, normalized_filename)
    
    # Check if file exists
    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        abort(404)
        
    return filepath, normalized_filename

@app.route("/")
def index():
    media_files = get_files(app.config["UPLOAD_FOLDER"], extensions=app.config["MEDIA_EXTENSIONS"])
    
    # Fetch both Markdown and Images from the Markdown folder
    mixed_extensions = app.config["MARKDOWN_EXTENSIONS"] + app.config["IMAGE_EXTENSIONS"]
    markdown_files = get_files(app.config["MARKDOWN_FOLDER"], extensions=mixed_extensions)

    return render_template(
        "index.html",
        media_files=media_files,
        markdown_files=markdown_files,
        media_view_route="media_view",
    )

@app.route("/media/<path:filename>")
def media_file(filename):
    """Serve media files with cache control."""
    # We can rely on send_from_directory for safety, but we'll use our helper 
    # if we want to strictly validate existence first, or just pass to send_from_directory.
    # send_from_directory is safe against traversal.
    # However, to be consistent with other routes that clean the path:
    
    # Note: send_from_directory takes the directory and the filename. 
    # If filename contains slashes, it treats it relative to directory.
    decoded_filename = urllib.parse.unquote(filename)
    
    response = send_from_directory(app.config["UPLOAD_FOLDER"], decoded_filename)
    response.cache_control.public = True
    response.cache_control.max_age = 300
    return response

@app.route("/media_view/<path:filename>")
def media_view(filename):
    """Render media files with HTML5 player"""
    # Use helper to validate and normalize
    _, normalized_filename = get_safe_path("UPLOAD_FOLDER", filename)
    
    # Pass normalized filename to template. 
    # Template will generate URL using 'media_file' route.
    return render_template(
        "media.html", filename=normalized_filename
    )

@app.route("/assets/<path:filename>")
def markdown_asset_file(filename):
    """Serve asset files from the Markdown directory with cache control."""
    decoded_filename = urllib.parse.unquote(filename)
    
    response = send_from_directory(app.config["MARKDOWN_FOLDER"], decoded_filename)
    response.cache_control.public = True
    response.cache_control.max_age = 300
    return response

@app.route("/assets_view/<path:filename>")
def markdown_asset_view(filename):
    """Render asset files from Markdown folder with HTML5 player"""
    # Use helper to validate and normalize
    _, normalized_filename = get_safe_path("MARKDOWN_FOLDER", filename)
    
    # Generate the direct URL to the asset
    file_url = url_for('markdown_asset_file', filename=normalized_filename)
    
    return render_template(
        "media.html", filename=normalized_filename, file_url=file_url
    )

def fix_list_spacing(markdown_content: str) -> str:
    """
    Ensure there is a blank line before list items if preceded by a non-blank line.
    This helps the markdown parser correctly identify lists even when they are 
    immediately preceded by text (common with nl2br extension).
    """
    # Match lines starting with bullet (*, -, +) or numbered list (1.) followed by space
    list_item_pattern = re.compile(r'^(\s*([*+-]|\d+\.)\s+)')
    
    lines = markdown_content.split('\n')
    new_lines = []
    for i, line in enumerate(lines):
        if i > 0 and list_item_pattern.match(line):
            prev_line = lines[i-1].strip()
            # If previous line is not empty and doesn't look like a list item itself
            if prev_line and not list_item_pattern.match(lines[i-1]):
                new_lines.append('')
        new_lines.append(line)
    return '\n'.join(new_lines)

def fix_math_content(content):
    """
    Fix common LaTeX errors in math content.
    - Remove newlines to prevent markdown.extensions.nl2br from inserting <br> inside math.
    - Double subscripts: _a_b -> _{a}_{b} or _{a_b} depending on intent, 
      here we simply brace single alphanumeric subscripts to be safe: _x -> _{x}.
      This turns x_i_j into x_{i}_{j} which MathJax handles correctly.
    """
    content = content.replace('\n', ' ')
    return re.sub(r'_([a-zA-Z0-9]+)', r'_{\1}', content)

def process_math_pre_markdown(text):
    """
    Extract math content, fix it, and replace with placeholders to protect from Markdown processing.
    Returns: (text_with_placeholders, placeholders_dict)
    """
    placeholders = {}
    
    def store_math(content, is_display, delimiter_type='dollar'):
        # Apply fixes (remove newlines, fix subscripts)
        fixed_content = fix_math_content(content)
        
        # Create unique placeholder
        key = f"MATHPLACEHOLDER{uuid.uuid4().hex}ENDMATHPLACEHOLDER"
        
        # Wrap in appropriate delimiters for final output
        if delimiter_type == 'bracket':
            final_math = fr'\[ {fixed_content} \]'
        elif is_display:
            final_math = fr'$$ {fixed_content} $$'
        else:
            final_math = fr'$ {fixed_content} $'
            
        placeholders[key] = final_math
        return key

    # 1. Handle $$ ... $$ -> Display Math
    # (Processed first to avoid conflict with inline math or brackets)
    text = re.sub(r'\$\$(.*?)\$\$', 
                  lambda m: store_math(m.group(1), True, delimiter_type='dollar'), 
                  text, flags=re.DOTALL)

    # 2. Handle $ ... $ -> Inline Math
    text = re.sub(r'\$(.*?)\$', 
                  lambda m: store_math(m.group(1), False, delimiter_type='dollar'), 
                  text, flags=re.DOTALL)

    # 3. Handle [ ... ] with heuristic -> Display Math (\[ ... \])
    # (Processed last as a fallback/heuristic)
    bracket_pattern = r'\[\s*(.*?)\s*\]'
    def replace_bracket_math(match):
        math_content = match.group(1).strip()
        # Heuristic to distinguish math from markdown links/text
        if any(char in math_content for char in ['\\', '^', '_', '{', '}', '=', '<', '>', '+', '-', '*', '/']):
            return store_math(math_content, True, delimiter_type='bracket')
        else:
            return match.group(0)
    
    text = re.sub(bracket_pattern, replace_bracket_math, text, flags=re.DOTALL)
                  
    return text, placeholders

def restore_math(html, placeholders):
    """Restore math content from placeholders."""
    for key, val in placeholders.items():
        html = html.replace(key, val)
    return html

@app.route("/markdown/<path:filename>")
def render_markdown(filename):
    """Render Markdown file with MathJax support."""
    filepath, _ = get_safe_path("MARKDOWN_FOLDER", filename)

    with open(filepath, "r", encoding="utf-8") as f:
        md_content = f.read()

    md_content = fix_list_spacing(md_content)
    
    # Pre-process math to protect it from Markdown
    final_md_content, math_placeholders = process_math_pre_markdown(md_content)

    extensions = [
        ExtraExtension(),
        'markdown.extensions.nl2br',
        'markdown.extensions.tables'
    ]

    md = markdown.Markdown(extensions=extensions)
    html_content = md.convert(final_md_content)
    
    # Restore math content
    html_content = restore_math(html_content, math_placeholders)

    return render_template(
        "markdown.html", 
        content=html_content,
        filename=filename # Passing original filename for title/display
    )

if __name__ == "__main__":
    # In production, use a WSGI server (e.g., gunicorn)
    app.run(host="0.0.0.0", port=5000, debug=True)