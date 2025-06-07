from flask import Flask, render_template, send_from_directory, abort
import os
import markdown
from markdown.extensions.extra import ExtraExtension
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.toc import TocExtension

HISTORY_RETENTION=7

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/media'
app.config['MARKDOWN_FOLDER'] = 'static/markdown'

def get_files(directory, extensions=None):
    """获取目录及子目录下的文件列表（递归）"""
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs.sort(reverse=True) 
        dirs[:] = dirs[:HISTORY_RETENTION] 
        for filename in filenames:
            # 根据扩展名列表过滤文件
            if extensions:
                if not any(filename.endswith(ext) for ext in extensions):
                    continue
            rel_path = os.path.relpath(os.path.join(root, filename), directory)
            files.append(rel_path)
    return files

@app.route('/')
def index():
    # 过滤media目录的.wav和.mp4文件
    media_files = get_files(app.config['UPLOAD_FOLDER'], extensions=['.wav', '.mp4'])
    # 过滤markdown目录的.md文件
    markdown_files = get_files(app.config['MARKDOWN_FOLDER'], extensions=['.md'])
    return render_template('index.html', 
                          media_files=media_files,
                          markdown_files=markdown_files,
                          media_view_route='media_view')  # Add media_view_route to context

@app.route('/media/<path:filename>')
def media_file(filename):
    # Decode URL-encoded filename
    decoded_filename = urllib.parse.unquote(filename)
    response = send_from_directory(app.config['UPLOAD_FOLDER'], decoded_filename)
    # Add cache control
    response.cache_control.public = True
    response.cache_control.max_age = 300
    return response

@app.route('/media_view/<path:filename>')
def media_view(filename):
    """Render media files with HTML5 player"""
    # Decode URL-encoded filename
    decoded_filename = urllib.parse.unquote(filename)
    
    # Clean filename: remove leading/trailing whitespace and newlines
    cleaned_filename = decoded_filename.strip().replace('\n', '')
    
    # Normalize path
    normalized_filename = os.path.normpath(cleaned_filename)
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], normalized_filename)
    app.logger.debug(f"Looking for media file: {filepath}")
    if not os.path.exists(filepath):
        app.logger.error(f"File not found: {filepath}")
        abort(404)
    
    # Create URL for the media file
    file_url = f"/media/{urllib.parse.quote(normalized_filename)}"
    
    return render_template('media.html', 
                          filename=normalized_filename,
                          filepath=file_url)

import urllib.parse

@app.route('/markdown/<path:filename>')
def render_markdown(filename):
    """渲染Markdown文件并支持LaTeX公式"""
    # Decode URL-encoded filename
    decoded_filename = urllib.parse.unquote(filename)
    
    # Clean filename: remove leading/trailing whitespace and newlines
    cleaned_filename = decoded_filename.strip().replace('\n', '')
    
    # Normalize path
    normalized_filename = os.path.normpath(cleaned_filename)
    
    filepath = os.path.join(app.config['MARKDOWN_FOLDER'], normalized_filename)
    app.logger.debug(f"Looking for markdown file: {filepath}")
    if not os.path.exists(filepath):
        app.logger.error(f"File not found: {filepath}")
        abort(404)
    
    # 读取Markdown内容
    with open(filepath, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 配置Markdown扩展
    extensions = [
        ExtraExtension(),
        CodeHiliteExtension(),
        TocExtension(title='Table of Contents'),
        'markdown.extensions.tables',
        'markdown.extensions.sane_lists'
    ]
    
    # 转换为HTML
    html_content = markdown.markdown(md_content, extensions=extensions)
    
    # 添加MathJax支持
    mathjax_script = '''
    <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <script>
    MathJax = {
        tex: {
            inlineMath: [['$', '$'], ['\\(', '\\)']]
        }
    };
    </script>
    '''
    
    return render_template('markdown.html', 
                          content=html_content,
                          filename=filename,
                          mathjax=mathjax_script)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
