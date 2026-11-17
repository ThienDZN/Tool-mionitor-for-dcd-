from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QClipboard, QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .ai_client import ClientConfigurationError, OpenAIResponsesClient, PreparedQuestion
from .clipboard_gate import RecentQuestions
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

# A reply can already start with the question heading it was shown (for example
# when one prompt carried the whole copied block). Prepending the label again
# produced "Câu 9: Câu 9: ...".
_ECHOED_LABEL_PATTERN = re.compile(
    r"(?i)^[ \t]*(?:(?:câu|cau|question)(?:[ \t]+(?:hỏi|hoi|số|so))?[ \t]*|q[ \t.\#]*)"
    r"\d{1,4}[ \t]*(?:[:.)\-–—][ \t]*)+"
)


def _fingerprint(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Auto-monitor may fire several times for one copy (text and image variants, or
# the same clipboard re-read by the toolkit). Only that burst is deduplicated;
# re-sending the same content later in the session stays possible.
_DEDUP_WINDOW_S = 8.0
# Only show the running clock once a question is noticeably slow; a counter on
# every fast question would just be visual noise.
_SHOW_ELAPSED_AFTER_S = 5.0
_PROGRESS_TICK_MS = 1000
_RETRY_NOTE_PATTERN = re.compile(r"\[RETRY\]\s*Attempt\s+(\d+)/(\d+)")
# One copy or screenshot fires dataChanged several times (each MIME type, or a
# screenshot tool that sets the image and then a file path). Read the clipboard
# once after it settles instead of reacting to every intermediate state.
_CLIPBOARD_SETTLE_MS = 300
# How long after an automatic skip H still means "send that anyway".
_FORCE_SKIPPED_WINDOW_S = 60.0
_DETECTING_TEXT = "ĐANG NHẬN DIỆN CÂU HỎI..."
_BUSY_HINT = "(Đang chạy câu trước — bấm H để hủy rồi chụp/copy lại)"


def _answer_per_line(text: str) -> str:
    """Show an unlabeled multi-part answer one part per line.

    When several questions arrive in one block with no "Câu N" headings, the
    model separates their answers with ";". Splitting those onto their own lines
    keeps them readable. Parts are numbered by question order, except when any
    part is a pair ("X → B"): then numbering would clash with the card numbers.
    """
    prefix = "Đáp án đúng:"
    body = text.removeprefix(prefix).strip() if text.startswith(prefix) else text
    parts = [part.strip() for part in re.split(r";\s*", body) if part.strip()]
    if len(parts) < 2:
        return text
    if any("→" in part for part in parts):
        return "\n".join(parts)
    return "\n".join(f"{number}) {part}" for number, part in enumerate(parts, 1))


def _short_progress_note(message: str) -> str | None:
    """Map a client status line to a short note shown next to RUNNING."""
    retry = _RETRY_NOTE_PATTERN.search(message)
    if retry:
        failed, total = int(retry.group(1)), int(retry.group(2))
        return f"thử lại {min(failed + 1, total)}/{total}"
    if message.startswith("[VERIFY] Re-checking"):
        return "kiểm tra lại ảnh"
    return None


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


# Every worker signal starts with the batch generation it belongs to. Pressing H
# bumps the generation; network calls already in flight cannot be interrupted,
# so their late results are recognised by the old generation and dropped.
class WorkerSignals(QObject):
    finished = Signal(int, int, str, float)
    failed = Signal(int, int, str, float)
    progress = Signal(int, int, str)


class PreparationSignals(QObject):
    detected = Signal(int, object)
    finished = Signal(int, object)
    failed = Signal(int, str)


class HotkeySignals(QObject):
    toggle_requested = Signal()
    cancel_requested = Signal()


class BatchPreparationWorker(QRunnable):
    def __init__(self, client: OpenAIResponsesClient, payload: PreparedClipboardPayload, generation: int) -> None:
        super().__init__()
        self.client = client
        self.payload = payload
        self.generation = generation
        self.signals = PreparationSignals()

    def run(self) -> None:
        try:
            result = self.client.prepare_batch(
                self.payload,
                on_questions_detected=lambda questions: self.signals.detected.emit(self.generation, questions),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            self.signals.failed.emit(self.generation, str(exc))
            return
        self.signals.finished.emit(self.generation, result)


class ResponseWorker(QRunnable):
    def __init__(
        self,
        client: OpenAIResponsesClient,
        index: int,
        question: PreparedQuestion,
        generation: int,
    ) -> None:
        super().__init__()
        self.client = client
        self.index = index
        self.question = question
        self.generation = generation
        self.signals = WorkerSignals()

    def run(self) -> None:
        started_at = time.monotonic()
        try:
            result = self.client.ask_prepared(
                self.question,
                on_progress=lambda message: self.signals.progress.emit(self.generation, self.index, message),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            self.signals.failed.emit(self.generation, self.index, str(exc), time.monotonic() - started_at)
            return
        self.signals.finished.emit(self.generation, self.index, result, time.monotonic() - started_at)


@dataclass(slots=True)
class AnswerBatch:
    """UI state for one recognised group of independent questions."""

    detected_questions: list[DetectedQuestion] = field(default_factory=list)
    questions: list[PreparedQuestion] = field(default_factory=list)
    completion_order: list[int] = field(default_factory=list)
    lines_by_index: dict[int, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    notes_by_index: dict[int, str] = field(default_factory=dict)
    # Shown under the RUNNING lines only, never in the final answer.
    footer: str = ""

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
        # Drop a heading the model echoed from the prompt before adding ours, so
        # the overlay never shows "Câu 9: Câu 9: ...".
        echoed_removed = _ECHOED_LABEL_PATTERN.sub("", text, count=1).strip()
        if echoed_removed:
            text = echoed_removed
        return f"{label}: {text}"

    def record_completion(self, index: int, line: str) -> bool:
        if index in self.lines_by_index:
            return False
        self.lines_by_index[index] = line
        self.completion_order.append(index)
        return True

    def running_text(self, index: int, now: float | None) -> str:
        """``RUNNING`` plus, when ``now`` is given, elapsed seconds and a retry note."""
        text = "RUNNING"
        if now is None:
            return text
        elapsed = now - self.started_at
        if elapsed >= _SHOW_ELAPSED_AFTER_S:
            text += f" {int(elapsed)}s"
        note = self.notes_by_index.get(index)
        if note:
            text += f" ({note})"
        return text

    def progress_text(self, now: float | None = None) -> str:
        completed_lines = [self.lines_by_index[index] for index in self.completion_order]
        completed_indices = set(self.lines_by_index)
        running_lines = [
            self.result_line(index, self.running_text(index, now))
            for index in range(self.question_count)
            if index not in completed_indices
        ]
        footer = [self.footer] if self.footer and not self.is_complete else []
        return "\n".join([*completed_lines, *running_lines, *footer])

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
            on_cancel=self._hotkey_signals.cancel_requested.emit,
        )

        self._monitoring_enabled = False
        self._busy = False
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(_PROGRESS_TICK_MS)
        self._progress_timer.timeout.connect(self._refresh_progress)
        self._last_seen_fingerprint: str | None = None
        self._last_submitted_fingerprint: str | None = None
        self._last_submitted_at = 0.0
        self._preparation_worker: BatchPreparationWorker | None = None
        self._active_workers: dict[int, ResponseWorker] = {}
        self._active_batch: AnswerBatch | None = None
        self._recent_questions = RecentQuestions()
        self._generation = 0
        # (kind, content, when) of the last clipboard item skipped as a repeat.
        self._last_skipped: tuple[str, object, float] | None = None
        self._last_answer_text = ""
        self._retired_pools: list[QThreadPool] = []
        self._clipboard_settle_timer = QTimer(self)
        self._clipboard_settle_timer.setSingleShot(True)
        self._clipboard_settle_timer.setInterval(_CLIPBOARD_SETTLE_MS)
        self._clipboard_settle_timer.timeout.connect(self._process_clipboard)

        self._status_reporter("[STARTUP] Checking system tray availability.")
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("System tray is not available in this desktop session.")

        self._clipboard.dataChanged.connect(self._handle_clipboard_change)
        self._hotkey_signals.toggle_requested.connect(self.toggle_overlay_visibility)
        self._hotkey_signals.cancel_requested.connect(self.cancel_current)
        self._tray.show()
        self._tray.set_enabled(False)
        self._status_reporter("[STARTUP] Tray icon is visible.")
        self._hotkey_listener.start()
        if self._hotkey_listener.is_supported:
            self._status_reporter("[STARTUP] Global hotkeys enabled (Left Shift hides/shows the overlay, H cancels the running answer).")
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
                "Copy text or take a screenshot to get an answer. Left Shift hides/shows the overlay, H cancels.",
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
        """Tray action: resend the clipboard text even if it was just answered."""
        self._status_reporter("[SEND] Manual resend of clipboard text.")
        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        if text.strip():
            self._status_reporter("[SEND] Sending clipboard text.")
            self._submit_text_if_allowed(text, force=True)
            return

        self._overlay.show_error("Khong co van ban de gui.", timeout_ms=4000)

    def send_clipboard_image_now(self) -> None:
        self._status_reporter("[SEND] Manual resend of clipboard image.")
        image = self._clipboard.image(QClipboard.Mode.Clipboard)
        if not image.isNull():
            self._status_reporter("[SEND] Sending clipboard image.")
            self._submit_image_if_allowed(image, force=True)
            return

        self._status_reporter("[SKIP] No image in clipboard; nothing to send.")
        self._overlay.show_error("Khong co anh trong clipboard de gui.", timeout_ms=4000)

    def cancel_current(self) -> None:
        """H: cancel what is running, or send the item that was just skipped.

        * Busy: drop the running batch, so the next copy or screenshot runs.
          Nothing is queued while busy: H must come first.
        * Idle, shortly after a copy was skipped as a repeat: the skip was a
          mistake, so send that item now.
        * Otherwise nothing: H is a plain letter and typing it must stay harmless.
        """
        if not self._busy:
            self._send_last_skipped()
            return

        cancelled_generation = self._generation
        self._generation += 1
        # Let the user re-send the same content right away after a cancel.
        self._recent_questions.forget(cancelled_generation)
        self._last_seen_fingerprint = None
        self._last_submitted_fingerprint = None
        self._retire_thread_pool()
        self._progress_timer.stop()
        self._preparation_worker = None
        self._active_batch = None
        self._active_workers.clear()
        self._busy = False
        self._tray.set_busy(False)
        self._tray.set_enabled(self._monitoring_enabled)
        self._status_reporter("[CANCEL] H pressed; running answer cancelled.")
        self._overlay.show_error("Đã hủy. Copy hoặc chụp câu mới.", timeout_ms=2500)

    def _remember_skip(self, kind: str, content: object) -> None:
        self._last_skipped = (kind, content, time.monotonic())
        if self._busy:
            return  # the progress lines stay on screen; the log says why
        # Show the answer already given again, with a hint, so a skip is never
        # silent and H is one key away if the match was wrong.
        hint = "(Trùng câu vừa trả lời — bấm H để gửi lại)"
        self._overlay.show_response(f"{self._last_answer_text}\n{hint}" if self._last_answer_text else hint)

    def _ignore_while_busy(self) -> None:
        """New content while a question runs is dropped, not queued.

        Queueing let a mistaken screenshot finish and then replaced its answer
        with the next one; the user decides with H instead. The content is not
        marked as seen, so copying it again after H sends it.
        """
        self._status_reporter("[SKIP] Busy; new clipboard content ignored. Press H to cancel first.")
        batch = self._active_batch
        if batch is None:
            return
        batch.footer = _BUSY_HINT
        if batch.question_count:
            self._overlay.show_batch_progress(batch.progress_text(time.monotonic()))
        else:
            self._overlay.show_running(f"{_DETECTING_TEXT}\n{_BUSY_HINT}")

    def _send_last_skipped(self) -> None:
        skipped = self._last_skipped
        self._last_skipped = None
        if skipped is None or time.monotonic() - skipped[2] > _FORCE_SKIPPED_WINDOW_S:
            return
        kind, content, _at = skipped
        self._status_reporter(f"[SEND] H pressed; sending the skipped {kind} anyway.")
        if kind == "text":
            self._submit_text_if_allowed(content, force=True)
        else:
            self._submit_image_if_allowed(content, force=True)

    def _retire_thread_pool(self) -> None:
        """Give the next batch fresh threads instead of queueing behind orphans."""
        self._thread_pool.clear()  # drops questions that had not started yet
        self._retired_pools = [pool for pool in self._retired_pools if pool.activeThreadCount() > 0]
        self._retired_pools.append(self._thread_pool)
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(max(1, self._config.max_parallel_questions))

    def toggle_overlay_visibility(self) -> None:
        visible = self._overlay.toggle_visibility()
        self._status_reporter(f"[OVERLAY] {'Shown' if visible else 'Hidden'}.")

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
        # Restarting the timer coalesces a burst of change signals into one read.
        self._clipboard_settle_timer.start()

    def _process_clipboard(self) -> None:
        if not self._monitoring_enabled:
            return
        if self._busy:
            # A late change signal for the item already running is not new content.
            busy_text = self._clipboard.text(QClipboard.Mode.Clipboard)
            if not (busy_text and _fingerprint(busy_text) == self._last_seen_fingerprint):
                self._ignore_while_busy()
            return

        # Text wins when both are present: office apps and browsers attach a
        # rendered picture to copied text, while screenshot tools put only an
        # image on the clipboard.
        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        if text.strip():
            self._submit_text_if_allowed(text, force=False)
            return

        image = self._clipboard.image(QClipboard.Mode.Clipboard)
        if not image.isNull():
            self._status_reporter("[MONITORING] Clipboard image detected; sending it automatically.")
            self._submit_image_if_allowed(image, force=False)

    def _submit_text_if_allowed(self, text: str, force: bool) -> None:
        if not text:
            return

        fingerprint = _fingerprint(text)
        if not force and fingerprint == self._last_seen_fingerprint:
            self._status_reporter("[SKIP] Clipboard text already seen; not sending again. Press H to send anyway.")
            self._remember_skip("text", text)
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
            self._status_reporter("[SKIP] Same text already submitted within dedup window. Press H to send anyway.")
            self._remember_skip("text", text)
            return
        if not force and self._recent_questions.is_repeat(payload.text):
            self._status_reporter(
                "[SKIP] Copied text matches a question answered moments ago. Press H to send anyway."
            )
            self._remember_skip("text", text)
            return

        if self._busy:
            self._ignore_while_busy()
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
            self._status_reporter("[SKIP] Same image already submitted within dedup window. Press H to send anyway.")
            self._remember_skip("image", image)
            return

        if self._busy:
            self._ignore_while_busy()
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
        self._last_skipped = None
        self._last_submitted_fingerprint = fingerprint
        self._last_submitted_at = time.monotonic()
        self._active_batch = AnswerBatch()
        self._progress_timer.start()
        self._tray.set_busy(True)
        self._overlay.show_running(_DETECTING_TEXT)
        self._app.processEvents()

        kind = "image" if isinstance(payload, PreparedClipboardImage) else "text"
        self._status_reporter(f"[DISPATCH] Preparing {kind} question(s) for the AI service.")
        worker = BatchPreparationWorker(self._client, payload, self._generation)
        self._preparation_worker = worker
        worker.signals.detected.connect(self._handle_questions_detected)
        worker.signals.finished.connect(self._handle_batch_prepared)
        worker.signals.failed.connect(self._handle_preparation_error)
        self._thread_pool.start(worker)

    def _handle_questions_detected(self, generation: int, questions_object: object) -> None:
        if generation != self._generation:
            return
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
        self._recent_questions.remember(
            (question.text for question in batch.detected_questions),
            key=generation,
        )
        self._status_reporter(f"[PREPARE] Detected {batch.question_count} question(s).")
        self._overlay.show_batch_progress(batch.progress_text())

    def _handle_batch_prepared(self, generation: int, questions_object: object) -> None:
        if generation != self._generation:
            return
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
            worker = ResponseWorker(self._client, index, question, generation)
            self._active_workers[index] = worker
            worker.signals.finished.connect(self._handle_question_result)
            worker.signals.failed.connect(self._handle_question_error)
            worker.signals.progress.connect(self._handle_question_progress)
            self._thread_pool.start(worker)

    def _handle_question_progress(self, generation: int, index: int, message: str) -> None:
        if generation != self._generation:
            return
        batch = self._active_batch
        if batch is None or index < 0 or index >= batch.question_count or index in batch.lines_by_index:
            return
        note = _short_progress_note(message)
        if note and batch.notes_by_index.get(index) != note:
            batch.notes_by_index[index] = note
            self._refresh_progress()

    def _refresh_progress(self) -> None:
        """Redraw RUNNING lines with the live clock; no-op until questions exist."""
        batch = self._active_batch
        if batch is None or batch.question_count == 0 or batch.is_complete:
            return
        self._overlay.show_batch_progress(batch.progress_text(time.monotonic()))

    def _handle_preparation_error(self, generation: int, error_text: str) -> None:
        if generation != self._generation:
            return
        self._preparation_worker = None
        self._finish_batch_with_error(error_text)

    def _handle_question_result(self, generation: int, index: int, text: str, elapsed_s: float) -> None:
        if generation != self._generation:
            return
        batch = self._active_batch
        if batch is None or index < 0 or index >= batch.question_count:
            return

        self._active_workers.pop(index, None)
        result = _clip_response(text, self._config.max_response_chars)
        if not batch.is_multi_question and not batch.display_questions[index].label:
            result = _answer_per_line(result)
        line = batch.result_line(index, result)
        status_label = batch.display_questions[index].label or f"Câu {index + 1}"
        self._status_reporter(f"[RESULT] {status_label} completed ({elapsed_s:.1f}s)")
        self._record_question_completion(batch, index, line)

    def _handle_question_error(self, generation: int, index: int, error_text: str, elapsed_s: float) -> None:
        if generation != self._generation:
            return
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
        self._last_answer_text = batch.progress_text()
        self._overlay.show_response(self._last_answer_text)
        self._finish_batch()

    def _finish_batch_with_error(self, error_text: str) -> None:
        self._status_reporter("[ERROR] Batch preparation failed.")
        self._overlay.show_error(f"AI error: {error_text}", timeout_ms=20000)
        self._finish_batch()

    def _finish_batch(self) -> None:
        self._progress_timer.stop()
        self._preparation_worker = None
        self._active_batch = None
        self._active_workers.clear()
        self._busy = False
        self._tray.set_busy(False)
        self._tray.set_enabled(self._monitoring_enabled)

    def _quit(self) -> None:
        self._clipboard_settle_timer.stop()
        self._hotkey_listener.stop()
        self._overlay.clear()
        self._app.quit()
