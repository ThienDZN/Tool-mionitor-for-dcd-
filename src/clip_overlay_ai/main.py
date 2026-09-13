from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import ClipboardOverlayController
from .config import load_config


def _report_status(message: str) -> None:
    print(message, flush=True)


def run() -> int:
    _report_status("[STARTUP] Starting Clipboard AI Overlay.")
    app = QApplication(sys.argv)
    app.setApplicationName("Clipboard AI Overlay")
    app.setQuitOnLastWindowClosed(False)

    _report_status("[STARTUP] Loading configuration.")
    config = load_config()
    issues = config.readiness_issues()
    if issues:
        _report_status(f"[CONFIG] Incomplete: {', '.join(issues)}.")
    else:
        reasoning_effort = config.reasoning_effort or "provider default"
        _report_status(f"[CONFIG] Model: {config.model}; reasoning: {reasoning_effort}.")
        _report_status("[CONFIG] Image verification: 2 independent passes for A.")

    _report_status("[STARTUP] Initializing tray, overlay, clipboard, and hotkeys.")
    try:
        controller = ClipboardOverlayController(app, config, status_reporter=_report_status)
    except Exception as exc:
        _report_status(f"[ERROR] Startup failed: {exc}")
        return 1

    if controller.monitoring_enabled:
        _report_status("[READY] Monitoring is ON. New clipboard content will be sent automatically.")
    else:
        _report_status("[READY] Monitoring is OFF. Use the tray icon to enable it.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
