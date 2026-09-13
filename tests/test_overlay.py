import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from clip_overlay_ai.config import AppConfig
from clip_overlay_ai.overlay import OverlayWindow


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _build_app() -> QApplication:
    app = QApplication.instance()
    if app is not None:
        return app
    return QApplication(sys.argv)


def _build_config() -> AppConfig:
    return AppConfig(
        api_key=None,
        model=None,
        base_url=None,
        system_prompt="x",
        overlay_duration_ms=50,
        overlay_font_point_size=8,
        max_clipboard_chars=4000,
        max_response_chars=700,
        request_timeout_s=40.0,
        resources_dir=Path("/tmp/resources"),
        session_context_path=Path("/tmp/state/session_context.json"),
        enable_web_fallback=True,
        web_search_context_size="medium",
    )


def test_overlay_can_toggle_latest_cached_message() -> None:
    _build_app()
    overlay = OverlayWindow(_build_config())
    overlay.show_running()
    overlay.hide()

    assert overlay.toggle_visibility() is True
    assert overlay.isVisible() is True
    assert overlay._content_label.text() == "RUNNING"
    assert overlay.toggle_visibility() is False
    assert overlay.isVisible() is False


def test_overlay_clear_removes_cached_message() -> None:
    _build_app()
    overlay = OverlayWindow(_build_config())
    overlay.show_response("hello")
    overlay.clear()

    assert overlay.toggle_visibility() is False


def test_overlay_shows_blank_frame_when_idle_visible() -> None:
    _build_app()
    overlay = OverlayWindow(_build_config())
    overlay.set_idle_visible(True)

    assert overlay.isVisible() is True
    assert overlay._content_label.text() == ""


def test_overlay_palette_stays_low_contrast_for_privacy() -> None:
    _build_app()
    overlay = OverlayWindow(_build_config())

    message_palette = overlay._palette_for_state("message")
    idle_palette = overlay._palette_for_state("idle")

    assert message_palette["background"] == "rgba(255, 255, 255, 38)"
    assert message_palette["text"] == "rgba(76, 76, 76, 112)"
    assert idle_palette["background"] == "rgba(255, 255, 255, 10)"


def test_overlay_resizes_for_response_length_without_becoming_too_wide() -> None:
    _build_app()
    overlay = OverlayWindow(_build_config())
    overlay.show_response("Đáp án đúng: A. Router")
    short_size = overlay.size()

    overlay.show_response("Đáp án đúng: " + "Architecture → Concrete system structure; " * 12)
    long_size = overlay.size()

    assert long_size.width() > short_size.width()
    assert long_size.width() <= 544
    assert long_size.height() > short_size.height()
