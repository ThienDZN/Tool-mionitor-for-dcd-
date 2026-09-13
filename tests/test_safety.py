import pytest
from PySide6.QtGui import QImage

from clip_overlay_ai.safety import (
    ClipboardRejectedError,
    detect_sensitive_reason,
    prepare_clipboard_image,
    prepare_clipboard_text,
)


def test_detects_private_key_material() -> None:
    reason = detect_sensitive_reason("-----BEGIN PRIVATE KEY-----\nABC")
    assert reason == "private key material"


def test_detects_password_like_line() -> None:
    reason = detect_sensitive_reason("password=supersecret")
    assert reason == "password-like line"


def test_prepare_clipboard_rejects_sensitive_text() -> None:
    with pytest.raises(ClipboardRejectedError):
        prepare_clipboard_text("Bearer abcdefghijklmnop", max_chars=100)


def test_prepare_clipboard_truncates_long_text() -> None:
    prepared = prepare_clipboard_text("x" * 20, max_chars=10)
    assert prepared.truncated is True
    assert prepared.text == "x" * 10


def test_prepare_clipboard_accepts_normal_text() -> None:
    prepared = prepare_clipboard_text("  fix this stack trace  ", max_chars=100)
    assert prepared.truncated is False
    assert prepared.text == "fix this stack trace"


def test_prepare_clipboard_image_accepts_normal_image() -> None:
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    image.fill(0xFF00FF)

    prepared = prepare_clipboard_image(image)

    assert prepared.width == 20
    assert prepared.height == 10
    assert prepared.png_bytes.startswith(b"\x89PNG")
    assert prepared.data_url.startswith("data:image/png;base64,")


def test_prepare_clipboard_image_rejects_empty_image() -> None:
    with pytest.raises(ClipboardRejectedError):
        prepare_clipboard_image(QImage())
