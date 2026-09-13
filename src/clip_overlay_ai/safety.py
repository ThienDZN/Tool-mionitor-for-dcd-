from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key material"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), "AWS temporary access key"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*\b"), "bearer token"),
    (
        re.compile(r"(?im)^\s*(password|passwd|pwd|secret|token|api[-_ ]?key)\s*[:=]\s*\S+"),
        "password-like line",
    ),
)
_MAX_IMAGE_EDGE = 1800


class ClipboardRejectedError(ValueError):
    """Raised when clipboard text should not be sent."""


@dataclass(slots=True)
class PreparedClipboardText:
    text: str
    truncated: bool


@dataclass(slots=True)
class PreparedClipboardImage:
    data_url: str
    png_bytes: bytes
    width: int
    height: int


PreparedClipboardPayload = PreparedClipboardText | PreparedClipboardImage


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def detect_sensitive_reason(text: str) -> str | None:
    for pattern, reason in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            return reason
    return None


def prepare_clipboard_text(text: str, max_chars: int) -> PreparedClipboardText:
    normalized = normalize_text(text)
    if not normalized:
        raise ClipboardRejectedError("Clipboard is empty.")

    reason = detect_sensitive_reason(normalized)
    if reason:
        raise ClipboardRejectedError(f"Clipboard looks sensitive ({reason}). Skipped.")

    if len(normalized) <= max_chars:
        return PreparedClipboardText(text=normalized, truncated=False)

    return PreparedClipboardText(text=normalized[:max_chars], truncated=True)


def prepare_clipboard_image(image: QImage) -> PreparedClipboardImage:
    if image.isNull():
        raise ClipboardRejectedError("Clipboard image is empty.")

    normalized = _downscale_image(image)
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ClipboardRejectedError("Could not prepare clipboard image.")

    if not normalized.save(buffer, "PNG"):
        raise ClipboardRejectedError("Could not encode clipboard image.")

    encoded = base64.b64encode(bytes(buffer.data())).decode("ascii")
    png_bytes = bytes(buffer.data())
    data_url = f"data:image/png;base64,{encoded}"
    return PreparedClipboardImage(
        data_url=data_url,
        png_bytes=png_bytes,
        width=normalized.width(),
        height=normalized.height(),
    )


def _downscale_image(image: QImage) -> QImage:
    longest_edge = max(image.width(), image.height())
    if longest_edge <= _MAX_IMAGE_EDGE:
        return image

    scale = _MAX_IMAGE_EDGE / longest_edge
    width = max(1, int(image.width() * scale))
    height = max(1, int(image.height() * scale))
    return image.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
