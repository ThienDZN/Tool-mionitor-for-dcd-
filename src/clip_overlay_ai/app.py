from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QClipboard, QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .ai_client import ClientConfigurationError, OpenAIResponsesClient, PreparedQuestion
from .config import AppConfig
from .hotkey import GlobalHotkeyListener
from .overlay import OverlayWindow
from .question_splitter import DetectedQuestion
from .session_context import SessionContextStore, prompt_for_session_context
from .safety import (
    ClipboardRejectedError,
    PreparedClipboardImage,
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


# Auto-monitor may fire several times for one copy (text and image variants, or
# the same clipboard re-read by the toolkit). Only that burst is deduplicated;
# re-sending the same content later in the session stays possible.
_DEDUP_WINDOW_S = 8.0


def _clip_response(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    target_length = max(1, min(max_chars, _MAX_VISIBLE_RESPONSE_CHARS))
    if len(normalized) <= target_length:
        return normalized
    return normalized[: target_length - 3].rstrip() + "..."


def _safe_question_error_message(error_text: str) -> str:
    """Return a useful overlay status without exposing gateway response bodies."""
    lowered = error_text.casefold()
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return "AI error: Dịch vụ đang giới hạn lượt gọi. Hãy thử lại sau."
    if "timeout" in lowered or "timed out" in lowered or "time budget" in lowered:
        return "AI error: Câu này đã hết thời gian chờ. Hãy thử lại."
    return "AI error: Không thể lấy đáp án. Kiểm tra mạng hoặc cấu hình rồi thử lại."


class WorkerSignals(QObject):
    finished = Signal(int, str, float)
    failed = Signal(int, str, float)


class PreparationSignals(QObject):
    detected = Signal(object)
    finished = Signal(object)
    failed = Signal(str)


class HotkeySignals(QObject):
    toggle_requested = Signal()
    send_text_requested = Signal()
    send_image_requested = Signal()


class BatchPreparationWorker(QRunnable):
    def __init__(self, client: OpenAIResponsesClient, payload: PreparedClipboardPayload) -> None:
        super().__init__()
        self.client = client
        self.payload = payload
        self.signals = PreparationSignals()

    def run(self) -> None:
        try:
            result = self.client.prepare_batch(
                self.payload,
                on_questions_detected=self.signals.detected.emit,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


class ResponseWorker(QRunnable):
    def __init__(self, client: OpenAIResponsesClient, index: int, question: PreparedQuestion) -> None:
        super().__init__()
        self.client = client
        self.index = index
        self.question = question
        self.signals = WorkerSignals()

    def run(self) -> None:
        started_at = time.monotonic()
        try:
            result = self.client.ask_prepared(self.question)
        except Exception as exc:  # pragma: no cover - defensive path
            self.signals.failed.emit(self.index, str(exc), time.monotonic() - started_at)
            return
        self.signals.finished.emit(self.index, result, time.monotonic() - started_at)


@dataclass(slots=True)
class PendingRequest:
    payload: PreparedClipboardPayload
    fingerprint: str


@dataclass(slots=True)
class AnswerBatch:
    """UI state for one recognised group of independent questions."""

    detected_questions: list[DetectedQuestion] = field(default_factory=list)
    questions: list[PreparedQuestion] = field(default_factory=list)
    completion_order: list[int] = field(default_factory=list)
    lines_by_index: dict[int, str] = field(default_factory=dict)

    @property
    def display_questions(self) -> list[DetectedQuestion]:
        if self.questions:
            return [question.question for question in self.questions]
        return self.detected_questions

    @property
    def question_count(self) -> int:
        return len(self.display_questions)

    @property
    def is_multi_question(self) -> bool:
        return self.question_count > 1

    @property
    def is_complete(self) -> bool:
        return self.question_count > 0 and len(self.lines_by_index) == self.question_count

    def result_line(self, index: int, text: str) -> str:
        label = self._label_for(index)
        if not label:
            return text

        # The question label already tells the user which result this is, so
        # repeating the generic prefix wastes scarce overlay space.  Keep it
        # for unnumbered questions and leave non-answer text (for example an
        # error) untouched.
        answer_prefix = "Đáp án đúng:"
        if text.startswith(answer_prefix):
            answer = text.removeprefix(answer_prefix).strip()
            if answer:
                text = answer
        return f"{label}: {text}"

    def record_completion(self, index: int, line: str) -> bool:
        if index in self.lines_by_index:
            return False
        self.lines_by_index[index] = line
        self.completion_order.append(index)
        return True

    def progress_text(self) -> str:
        completed_lines = [self.lines_by_index[index] for index in self.completion_order]
        completed_indices = set(self.lines_by_index)
        running_lines = [
            self.result_line(index, "RUNNING")
            for index in range(self.question_count)
            if index not in completed_indices
        ]
        return "\n".join([*completed_lines, *running_lines])

    def _label_for(self, index: int) -> str | None:
        if 0 <= index < self.question_count:
            label = self.display_questions[index].label
            if label:
                return label
        return None


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
        self._client = OpenAIResponsesClient(config, status_reporter=self._status_reporter)
        self._context_store = self._client.session_context_store or SessionContextStore(config.session_context_path)
        self._overlay = OverlayWindow(config)
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(max(1, config.max_parallel_questions))
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
        self._last_submitted_at = 0.0
        self._pending_request: PendingRequest | None = None
        self._preparation_worker: BatchPreparationWorker | None = None
        self._active_workers: dict[int, ResponseWorker] = {}
        self._active_batch: AnswerBatch | None = None

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

        self._status_reporter("[STARTUP] Waiting for the subject dialog to close.")
        self.update_session_context(prompt_even_if_existing=True)
        self._status_reporter("[STARTUP] Subject step complete.")
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

        self._status_reporter("[SKIP] No image in clipboard; nothing to send.")
        self._overlay.show_error("Khong co anh trong clipboard de gui.", timeout_ms=4000)

    def toggle_overlay_visibility(self) -> None:
        self._overlay.toggle_visibility()

    def update_session_context(self, prompt_even_if_existing: bool = False) -> None:
        current = self._context_store.load()
        updated = prompt_for_session_context(None, current)

        if updated != current:
            self._context_store.save(updated)
            self._tray.notify("Clipboard AI Overlay", f"Subject updated: {updated.summary()}")
            return

        if current.is_empty() and prompt_even_if_existing:
            self._tray.notify("Clipboard AI Overlay", "No subject set. Research quality may be lower.")

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
            self._status_reporter("[SKIP] Clipboard text already seen; not sending again.")
            return
        self._last_seen_fingerprint = fingerprint

        try:
            payload = prepare_clipboard_text(text, self._config.max_clipboard_chars)
        except ClipboardRejectedError as exc:
            self._status_reporter(f"[SKIP] Clipboard text rejected: {exc}")
            self._overlay.show_error(str(exc), timeout_ms=8000)
            return

        payload_fingerprint = _fingerprint(payload.text)
        if not force and self._is_duplicate_recent(payload_fingerprint):
            self._status_reporter("[SKIP] Same text already submitted within dedup window.")
            return

        if self._busy:
            self._status_reporter("[QUEUE] Busy; keeping this text as the pending request.")
            self._pending_request = PendingRequest(payload=payload, fingerprint=payload_fingerprint)
            return

        self._dispatch_payload(payload, payload_fingerprint)

    def _submit_image_if_allowed(self, image, force: bool) -> None:
        try:
            payload = prepare_clipboard_image(image)
        except ClipboardRejectedError as exc:
            self._status_reporter(f"[SKIP] Clipboard image rejected: {exc}")
            self._overlay.show_error(str(exc), timeout_ms=8000)
            return

        payload_fingerprint = _fingerprint(payload.png_bytes)
        if not force and self._is_duplicate_recent(payload_fingerprint):
            self._status_reporter("[SKIP] Same image already submitted within dedup window.")
            return

        if self._busy:
            self._status_reporter("[QUEUE] Busy; keeping this image as the pending request.")
            self._pending_request = PendingRequest(payload=payload, fingerprint=payload_fingerprint)
            return

        self._dispatch_payload(payload, payload_fingerprint)

    def _is_duplicate_recent(self, fingerprint: str) -> bool:
        """Treat a repeat as a duplicate only inside the dedup window.

        Before this window existed the check was permanent, so re-copying the
        exact same content later in a session was silently dropped and looked
        like the app had stopped working.
        """
        if fingerprint != self._last_submitted_fingerprint:
            return False
        return (time.monotonic() - self._last_submitted_at) < _DEDUP_WINDOW_S

    def _dispatch_payload(self, payload: PreparedClipboardPayload, fingerprint: str) -> None:
        try:
            if self._config.readiness_issues():
                raise ClientConfigurationError(", ".join(self._config.readiness_issues()))
        except ClientConfigurationError as exc:
            self._status_reporter(f"[ERROR] Configuration incomplete: {exc}")
            self._overlay.show_error(str(exc), timeout_ms=20000)
            return

        self._busy = True
        self._last_submitted_fingerprint = fingerprint
        self._last_submitted_at = time.monotonic()
        self._active_batch = AnswerBatch()
        self._tray.set_busy(True)
        self._overlay.show_running("ĐANG NHẬN DIỆN CÂU HỎI...")
        self._app.processEvents()

        kind = "image" if isinstance(payload, PreparedClipboardImage) else "text"
        self._status_reporter(f"[DISPATCH] Preparing {kind} question(s) for the AI service.")
        worker = BatchPreparationWorker(self._client, payload)
        self._preparation_worker = worker
        worker.signals.detected.connect(self._handle_questions_detected)
        worker.signals.finished.connect(self._handle_batch_prepared)
        worker.signals.failed.connect(self._handle_preparation_error)
        self._thread_pool.start(worker)

    def _handle_questions_detected(self, questions_object: object) -> None:
        batch = self._active_batch
        if batch is None:
            return
        if not isinstance(questions_object, list) or not questions_object:
            self._status_reporter("[PREPARE] No usable question headings were detected.")
            return
        if not all(isinstance(question, DetectedQuestion) for question in questions_object):
            self._status_reporter("[PREPARE] Ignoring invalid question-detection data.")
            return

        batch.detected_questions = list(questions_object)
        self._status_reporter(f"[PREPARE] Detected {batch.question_count} question(s).")
        self._overlay.show_batch_progress(batch.progress_text())

    def _handle_batch_prepared(self, questions_object: object) -> None:
        self._preparation_worker = None
        if not isinstance(questions_object, list) or not questions_object:
            self._finish_batch_with_error("Không nhận diện được câu hỏi để gửi.")
            return
        if not all(isinstance(question, PreparedQuestion) for question in questions_object):
            self._finish_batch_with_error("Dữ liệu chuẩn bị câu hỏi không hợp lệ.")
            return

        batch = self._active_batch
        if batch is None:
            self._finish_batch_with_error("Phiên xử lý đã kết thúc trước khi chuẩn bị xong.")
            return

        questions = questions_object
        batch.questions = questions
        # The prepared objects are the authoritative source for worker indexes.
        # This also makes the UI resilient if a queued Qt signal arrives after
        # the preparation-complete signal.
        batch.detected_questions = [question.question for question in questions]
        self._overlay.show_batch_progress(batch.progress_text())
        self._status_reporter(
            f"[PREPARE] Dispatching {len(questions)} question(s) "
            f"(max {self._config.max_parallel_questions} parallel)."
        )

        for index, question in enumerate(questions):
            worker = ResponseWorker(self._client, index, question)
            self._active_workers[index] = worker
            worker.signals.finished.connect(self._handle_question_result)
            worker.signals.failed.connect(self._handle_question_error)
            self._thread_pool.start(worker)

    def _handle_preparation_error(self, error_text: str) -> None:
        self._preparation_worker = None
        self._finish_batch_with_error(error_text)

    def _handle_question_result(self, index: int, text: str, elapsed_s: float) -> None:
        batch = self._active_batch
        if batch is None or index < 0 or index >= batch.question_count:
            return

        self._active_workers.pop(index, None)
        result = _clip_response(text, self._config.max_response_chars)
        line = batch.result_line(index, result)
        status_label = batch.display_questions[index].label or f"Câu {index + 1}"
        self._status_reporter(f"[RESULT] {status_label} completed ({elapsed_s:.1f}s)")
        self._record_question_completion(batch, index, line)

    def _handle_question_error(self, index: int, error_text: str, elapsed_s: float) -> None:
        batch = self._active_batch
        if batch is None or index < 0 or index >= batch.question_count:
            return

        self._active_workers.pop(index, None)
        error = _clip_response(_safe_question_error_message(error_text), self._config.max_response_chars)
        line = batch.result_line(index, error)
        status_label = batch.display_questions[index].label or f"Câu {index + 1}"
        self._status_reporter(f"[ERROR] {status_label} failed ({elapsed_s:.1f}s)")
        self._record_question_completion(batch, index, line)

    def _record_question_completion(self, batch: AnswerBatch, index: int, line: str) -> None:
        if not batch.record_completion(index, line):
            return
        if not batch.is_complete:
            self._overlay.show_batch_progress(batch.progress_text())
            return

        # Once every line is final, resume the normal response timer. Until
        # this point ``show_batch_progress`` intentionally stays visible.
        self._overlay.show_response(batch.progress_text())
        self._finish_batch()

    def _finish_batch_with_error(self, error_text: str) -> None:
        self._status_reporter("[ERROR] Batch preparation failed.")
        self._overlay.show_error(f"AI error: {error_text}", timeout_ms=20000)
        self._finish_batch()

    def _finish_batch(self) -> None:
        self._preparation_worker = None
        self._active_batch = None
        self._active_workers.clear()
        self._busy = False
        self._tray.set_busy(False)
        self._tray.set_enabled(self._monitoring_enabled)
        self._flush_pending()

    def _flush_pending(self) -> None:
        if not self._pending_request:
            return
        pending_payload = self._pending_request.payload
        pending_fingerprint = self._pending_request.fingerprint
        self._pending_request = None
        if self._is_duplicate_recent(pending_fingerprint):
            self._status_reporter("[SKIP] Pending request duplicates the last submission.")
            return
        self._status_reporter("[QUEUE] Sending the pending request now.")
        self._dispatch_payload(pending_payload, pending_fingerprint)

    def _quit(self) -> None:
        self._hotkey_listener.stop()
        self._overlay.clear()
        self._app.quit()
