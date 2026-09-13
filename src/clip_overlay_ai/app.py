from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QClipboard, QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .ai_client import ClientConfigurationError, OpenAIResponsesClient
from .config import AppConfig
from .hotkey import GlobalHotkeyListener
from .overlay import OverlayWindow
from .session_context import SessionContextStore, prompt_for_session_context
from .safety import (
    ClipboardRejectedError,
    PreparedClipboardPayload,
    prepare_clipboard_image,
    prepare_clipboard_text,
)
from .tray import TrayController


_MAX_VISIBLE_RESPONSE_CHARS = 480


def _fingerprint(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clip_response(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    target_length = max(1, min(max_chars, _MAX_VISIBLE_RESPONSE_CHARS))
    if len(normalized) <= target_length:
        return normalized
    return normalized[: target_length - 3].rstrip() + "..."


class WorkerSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class HotkeySignals(QObject):
    toggle_requested = Signal()
    send_text_requested = Signal()
    send_image_requested = Signal()


class ResponseWorker(QRunnable):
    def __init__(self, client: OpenAIResponsesClient, payload: PreparedClipboardPayload) -> None:
        super().__init__()
        self.client = client
        self.payload = payload
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.client.ask(self.payload)
        except Exception as exc:  # pragma: no cover - defensive path
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


@dataclass(slots=True)
class PendingRequest:
    payload: PreparedClipboardPayload
    fingerprint: str


class ClipboardOverlayController(QObject):
    def __init__(
        self,
        app: QApplication,
        config: AppConfig,
        status_reporter: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._config = config
        self._status_reporter = status_reporter or (lambda _message: None)
        self._client = OpenAIResponsesClient(config)
        self._context_store = self._client.session_context_store or SessionContextStore(config.session_context_path)
        self._overlay = OverlayWindow(config)
        self._thread_pool = QThreadPool.globalInstance()
        self._clipboard = QGuiApplication.clipboard()
        self._hotkey_signals = HotkeySignals()
        self._tray = TrayController(
            on_toggle=self.toggle_monitoring,
            on_send_text=self.send_selected_text_now,
            on_send_image=self.send_clipboard_image_now,
            on_toggle_overlay=self.toggle_overlay_visibility,
            on_update_context=self.update_session_context,
            on_refresh_resources=self.refresh_resources,
            on_clear=self._overlay.clear,
            on_quit=self._quit,
        )
        self._hotkey_listener = GlobalHotkeyListener(
            on_toggle_overlay=self._hotkey_signals.toggle_requested.emit,
            on_send_text=self._hotkey_signals.send_text_requested.emit,
            on_send_image=self._hotkey_signals.send_image_requested.emit,
        )

        self._monitoring_enabled = False
        self._busy = False
        self._last_seen_fingerprint: str | None = None
        self._last_submitted_fingerprint: str | None = None
        self._pending_request: PendingRequest | None = None

        self._status_reporter("[STARTUP] Checking system tray availability.")
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("System tray is not available in this desktop session.")

        self._clipboard.dataChanged.connect(self._handle_clipboard_change)
        self._hotkey_signals.toggle_requested.connect(self.toggle_overlay_visibility)
        self._hotkey_signals.send_text_requested.connect(self.send_selected_text_now)
        self._hotkey_signals.send_image_requested.connect(self.send_clipboard_image_now)
        self._tray.show()
        self._tray.set_enabled(False)
        self._status_reporter("[STARTUP] Tray icon is visible.")
        self._hotkey_listener.start()
        if self._hotkey_listener.is_supported:
            self._status_reporter("[STARTUP] Global hotkeys are enabled (Left Shift, R, and A).")
        elif self._hotkey_listener.reason:
            self._status_reporter(f"[STARTUP] Global hotkeys unavailable: {self._hotkey_listener.reason}")

        self._status_reporter("[STARTUP] Waiting for the subject/context dialog to close.")
        self.update_session_context(prompt_even_if_existing=True)
        self._status_reporter("[STARTUP] Subject/context step complete.")
        resource_count = self.refresh_resources(notify=False)
        self._status_reporter(f"[STARTUP] Resources indexed: {resource_count} file(s).")

        issues = self._config.readiness_issues()
        if issues:
            self._tray.notify("Clipboard AI Overlay", "Config incomplete. Set your model or token in .env.")
        else:
            self._tray.notify("Clipboard AI Overlay", "Ready. Left-click tray icon to enable monitoring.")

        if self._hotkey_listener.is_supported:
            self._tray.notify(
                "Clipboard AI Overlay",
                "Press Left Shift to hide/show overlay. Press R to send text or A to send a clipboard image.",
            )
        elif self._hotkey_listener.reason:
            self._tray.notify("Clipboard AI Overlay", self._hotkey_listener.reason)

        if self._config.auto_start_monitoring:
            self._set_monitoring_enabled(True)
            self._status_reporter("[STARTUP] Monitoring enabled automatically.")

    @property
    def monitoring_enabled(self) -> bool:
        return self._monitoring_enabled

    def toggle_monitoring(self) -> None:
        if self._busy:
            return
        self._set_monitoring_enabled(not self._monitoring_enabled)

    def _set_monitoring_enabled(self, enabled: bool) -> None:
        self._monitoring_enabled = enabled
        self._tray.set_enabled(enabled)
        self._overlay.set_idle_visible(enabled)
        message = "Monitoring enabled." if enabled else "Monitoring disabled."
        self._tray.notify("Clipboard AI Overlay", message)
        self._status_reporter(f"[MONITORING] {message}")

    def send_selected_text_now(self) -> None:
        self._status_reporter("[SEND] R pressed; sending text only.")
        selection_text = self._clipboard.text(QClipboard.Mode.Selection)
        if selection_text.strip():
            self._status_reporter("[SEND] Sending selected text.")
            self._submit_text_if_allowed(selection_text, force=True)
            return

        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        if text.strip():
            self._status_reporter("[SEND] Sending clipboard text.")
            self._submit_text_if_allowed(text, force=True)
            return

        self._overlay.show_error("Khong co van ban de gui.", timeout_ms=4000)

    def send_clipboard_image_now(self) -> None:
        self._status_reporter("[SEND] A pressed; sending clipboard image only.")
        image = self._clipboard.image(QClipboard.Mode.Clipboard)
        if not image.isNull():
            self._status_reporter("[SEND] Sending clipboard image.")
            self._submit_image_if_allowed(image, force=True)
            return

        self._overlay.show_error("Khong co anh trong clipboard de gui.", timeout_ms=4000)

    def toggle_overlay_visibility(self) -> None:
        self._overlay.toggle_visibility()

    def update_session_context(self, prompt_even_if_existing: bool = False) -> None:
        current = self._context_store.load()
        updated = prompt_for_session_context(None, current)

        if updated != current:
            self._context_store.save(updated)
            self._tray.notify("Clipboard AI Overlay", f"Context updated: {updated.summary()}")
            return

        if current.is_empty() and prompt_even_if_existing:
            self._tray.notify("Clipboard AI Overlay", "No subject/context set. Research quality may be lower.")

    def refresh_resources(self, notify: bool = True) -> int:
        count = self._client.refresh_resources()
        if notify:
            self._tray.notify("Clipboard AI Overlay", f"Resources refreshed: {count} file(s) indexed.")
        return count

    def _handle_clipboard_change(self) -> None:
        if not self._monitoring_enabled:
            return

        image = self._clipboard.image(QClipboard.Mode.Clipboard)
        if not image.isNull():
            self._status_reporter("[MONITORING] Clipboard image detected; waiting for A to send it.")
            return

        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        self._submit_text_if_allowed(text, force=False)

    def _submit_text_if_allowed(self, text: str, force: bool) -> None:
        if not text:
            return

        fingerprint = _fingerprint(text)
        if not force and fingerprint == self._last_seen_fingerprint:
            return
        self._last_seen_fingerprint = fingerprint

        try:
            payload = prepare_clipboard_text(text, self._config.max_clipboard_chars)
        except ClipboardRejectedError as exc:
            self._overlay.show_error(str(exc), timeout_ms=8000)
            return

        payload_fingerprint = _fingerprint(payload.text)
        if not force and payload_fingerprint == self._last_submitted_fingerprint:
            return

        if self._busy:
            self._pending_request = PendingRequest(payload=payload, fingerprint=payload_fingerprint)
            return

        self._dispatch_payload(payload, payload_fingerprint)

    def _submit_image_if_allowed(self, image, force: bool) -> None:
        try:
            payload = prepare_clipboard_image(image)
        except ClipboardRejectedError as exc:
            self._overlay.show_error(str(exc), timeout_ms=8000)
            return

        payload_fingerprint = _fingerprint(payload.png_bytes)
        if not force and payload_fingerprint == self._last_submitted_fingerprint:
            return

        if self._busy:
            self._pending_request = PendingRequest(payload=payload, fingerprint=payload_fingerprint)
            return

        self._dispatch_payload(payload, payload_fingerprint)

    def _dispatch_payload(self, payload: PreparedClipboardPayload, fingerprint: str) -> None:
        try:
            if self._config.readiness_issues():
                raise ClientConfigurationError(", ".join(self._config.readiness_issues()))
        except ClientConfigurationError as exc:
            self._overlay.show_error(str(exc), timeout_ms=20000)
            return

        self._busy = True
        self._last_submitted_fingerprint = fingerprint
        self._tray.set_busy(True)
        self._overlay.show_running()
        self._app.processEvents()

        worker = ResponseWorker(self._client, payload)
        worker.signals.finished.connect(self._handle_result)
        worker.signals.failed.connect(self._handle_error)
        self._thread_pool.start(worker)

    def _handle_result(self, text: str) -> None:
        self._busy = False
        self._tray.set_busy(False)
        self._tray.set_enabled(self._monitoring_enabled)
        self._overlay.show_response(_clip_response(text, self._config.max_response_chars))
        self._flush_pending()

    def _handle_error(self, error_text: str) -> None:
        self._busy = False
        self._tray.set_busy(False)
        self._tray.set_enabled(self._monitoring_enabled)
        self._overlay.show_error(f"AI error: {error_text}", timeout_ms=20000)
        self._flush_pending()

    def _flush_pending(self) -> None:
        if not self._pending_request:
            return
        pending_payload = self._pending_request.payload
        pending_fingerprint = self._pending_request.fingerprint
        self._pending_request = None
        if pending_fingerprint == self._last_submitted_fingerprint:
            return
        self._dispatch_payload(pending_payload, pending_fingerprint)

    def _quit(self) -> None:
        self._hotkey_listener.stop()
        self._overlay.clear()
        self._app.quit()
