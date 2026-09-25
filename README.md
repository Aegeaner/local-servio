# Local Servio Project

This is a simple Python web server built with Flask, designed for serving audio, video, and Markdown-formatted static files within a local network.

## Features
- Markdown content serving
- Static file hosting
- Subcast cache browser (`/subcast`): native HTML5 playback of cached `.mp3`/`.mp4` files with WebVTT subtitles
- Player keeps the screen awake while playing (Screen Wake Lock, where the browser has it) and falls back to the native video player fullscreen on iPadOS/iPhone
- Poetry dependency management

## Routes
| Route | Purpose |
| --- | --- |
| `/` | Index of uploaded media and Markdown documents |
| `/subcast` | Cache browser for the subcast CLI's media cache, grouped by source; files inside a source are newest-modified first |
| `/subcast/player/<source>/<key>` | HTML5 player: native `<video>`/`<audio>` over byte-range requests, `<track>` captions painted from `TextTrack.activeCues` into a caption lane below the player |
| `/subcast/media/<source>/<file>` | Byte-range media streaming (`206 Partial Content`, for seeking) |
| `/subcast/subtitles/<source>/<key>.vtt` | The cached `.srt`/`.cues.json` transcript as `text/vtt` |

The cache location defaults to `~/.cache/subcast` and can be overridden with the
`SUBSCAST_FOLDER` environment variable. Only `<key>.mp3` and `<key>.mp4` files are
listed; the `.srt`/`.cues.json` sidecars are served as subtitles, titles come from
`listings/*.json` and `<key>.meta.json`.

## Setup
```bash
poetry install
poetry run python app.py
```

## Usage
Access the application at `http://localhost:5000`
