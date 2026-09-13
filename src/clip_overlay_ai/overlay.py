from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .config import AppConfig


_MIN_CONTENT_WIDTH = 182
_MAX_CONTENT_WIDTH = 520


class OverlayWindow(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__(None)
        self._config = config
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._handle_timeout)
        self._cached_message = ""
        self._idle_visible = False
        self._manually_hidden = False
        self._custom_position: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._visual_state = "idle"

        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        container = QFrame(self)
        container.setObjectName("bubble")

        self._content_label = QLabel("")
        self._content_label.setObjectName("content")
        self._content_label.setWordWrap(True)
        self._content_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._content_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)
        layout.addWidget(self._content_label)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(container)

        self._apply_visual_state("idle")

        self.setMinimumSize(206, 34)
        self.setMaximumWidth(_MAX_CONTENT_WIDTH + 24)
        self.resize(206, 34)
        self.hide()

    def set_idle_visible(self, visible: bool) -> None:
        self._idle_visible = visible
        if not visible:
            self._hide_timer.stop()
            self.hide()
            return

        if self._manually_hidden:
            return
        self._present_blank()

    def show_running(self, text: str = "RUNNING") -> None:
        self._cached_message = text
        self._content_label.setText(text)
        self._apply_visual_state("running")
        self._present(timeout_ms=None)

    def show_response(self, text: str) -> None:
        self._cached_message = text
        self._content_label.setText(text)
        self._apply_visual_state("message")
        if self._manually_hidden:
            self._hide_timer.stop()
            return
        self._present(timeout_ms=self._config.overlay_duration_ms)

    def show_error(self, text: str, timeout_ms: int | None = None) -> None:
        self._cached_message = text
        self._content_label.setText(text)
        self._apply_visual_state("error")
        if self._manually_hidden:
            self._hide_timer.stop()
            return
        self._present(timeout_ms=timeout_ms or self._config.overlay_duration_ms)

    def clear(self) -> None:
        self._cached_message = ""
        self._hide_timer.stop()
        if self._idle_visible and not self._manually_hidden:
            self._present_blank()
            return
        self.hide()

    def toggle_visibility(self) -> bool:
        if self.isVisible():
            self._manually_hidden = True
            self._hide_timer.stop()
            self.hide()
            return False

        self._manually_hidden = False
        if self._cached_message:
            self._content_label.setText(self._cached_message)
            self._present(timeout_ms=None)
            return True

        if self._idle_visible:
            self._present_blank()
            return True

        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._custom_position = self.pos()
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _handle_timeout(self) -> None:
        if self._idle_visible and not self._manually_hidden:
            self._cached_message = ""
            self._present_blank()
            return
        self.hide()

    def _present_blank(self) -> None:
        self._content_label.setText("")
        self._apply_visual_state("idle")
        self._present(timeout_ms=None)

    def _present(self, timeout_ms: int | None) -> None:
        if self._manually_hidden:
            return
        self._resize_for_content(self._content_label.text())
        self.adjustSize()
        self.resize(max(self.width(), 206), max(self.height(), 34))
        self._reposition()
        self.show()
        self.raise_()
        if timeout_ms is None or timeout_ms <= 0:
            self._hide_timer.stop()
            return
        self._hide_timer.start(timeout_ms)

    def _resize_for_content(self, text: str) -> None:
        metrics = QFontMetrics(self._content_label.font())
        longest_line = max((metrics.horizontalAdvance(line) for line in text.splitlines()), default=0)
        width = min(_MAX_CONTENT_WIDTH, max(_MIN_CONTENT_WIDTH, longest_line + 4))
        self._content_label.setFixedWidth(width)

    def _reposition(self) -> None:
        if self._custom_position is not None:
            self.move(self._custom_position)
            return

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        geometry = screen.availableGeometry()
        margin = 18
        x = geometry.left() + margin
        y = geometry.bottom() - self.height() - margin
        self.move(QPoint(x, y))

    def _apply_visual_state(self, state: str) -> None:
        self._visual_state = state
        palette = self._palette_for_state(state)
        self.setStyleSheet(
            f"""
            #bubble {{
                background-color: {palette["background"]};
                border: 1px solid {palette["border"]};
                border-radius: 10px;
            }}
            QLabel#content {{
                color: {palette["text"]};
                font-size: {self._config.overlay_font_point_size}pt;
                font-weight: 400;
                line-height: 1.15em;
            }}
            """
        )

    def _palette_for_state(self, state: str) -> dict[str, str]:
        if state == "running":
            return {
                "background": "rgba(255, 255, 255, 28)",
                "border": "rgba(178, 178, 178, 10)",
                "text": "rgba(98, 98, 98, 88)",
            }
        if state == "message":
            return {
                "background": "rgba(255, 255, 255, 38)",
                "border": "rgba(176, 176, 176, 12)",
                "text": "rgba(76, 76, 76, 112)",
            }
        if state == "error":
            return {
                "background": "rgba(255, 251, 251, 42)",
                "border": "rgba(188, 164, 164, 14)",
                "text": "rgba(112, 88, 88, 116)",
            }
        return {
            "background": "rgba(255, 255, 255, 10)",
            "border": "rgba(186, 186, 186, 8)",
            "text": "rgba(255, 255, 255, 0)",
        }
