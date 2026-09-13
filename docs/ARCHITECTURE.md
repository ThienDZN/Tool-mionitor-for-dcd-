# Architecture Brief

## Problem

Build a desktop utility that can be turned on and off, reacts to clipboard text and screenshot captures, prefers local study materials, can fall back to web research when needed, and shows the answer in a tiny translucent overlay at the bottom-left of the screen.

## Chosen approach

Use a native desktop app with PySide6:

- `QClipboard.dataChanged` for clipboard monitoring
- `QSystemTrayIcon` for toggle and lifecycle controls
- a frameless translucent `QWidget` for the overlay
- `QThreadPool` + `QRunnable` for background API calls
- local OCR for screenshots
- local file retrieval from `resources/`
- optional web-search tool fallback through the Responses API

## Why this approach

- fewer moving parts than Electron
- cross-platform clipboard and tray support in one toolkit
- easier to keep the overlay small, always-on-top, and transparent
- simple to isolate UI, safety checks, and AI transport

## Trust boundaries

1. Clipboard text or screenshot enters the app.
2. Safety checks decide whether it can be sent.
3. Local OCR and local resource retrieval enrich the prompt first.
4. If local material is not enough, web fallback may be enabled through the model API.
5. The returned answer is trimmed for the overlay and rendered locally.

## Security decisions

- never hard-code API keys
- block obvious secrets before network send
- keep logs free of clipboard contents and tokens
- reject startup as "not ready" if required config is missing

## Current limitations

- local retrieval is lexical, not embedding-based yet
- web fallback depends on provider support for the Responses web-search tool
- no direct binding to the current Codex chat session; this version uses the OpenAI API or a compatible gateway with a user-selected model
