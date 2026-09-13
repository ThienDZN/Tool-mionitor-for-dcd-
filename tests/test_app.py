from PySide6.QtGui import QClipboard

from clip_overlay_ai.app import ClipboardOverlayController, _clip_response


class _ClipboardWithSelectionAndImage:
    def text(self, mode: QClipboard.Mode) -> str:
        if mode == QClipboard.Mode.Selection:
            return "stale selected text"
        return "clipboard text"

    def image(self, _mode: QClipboard.Mode):
        return _NonNullImage()


class _NonNullImage:
    def isNull(self) -> bool:
        return False


class _ClipboardWithImageAndStaleText:
    def text(self, _mode: QClipboard.Mode) -> str:
        return "New clipboard content will be sent automatically."

    def image(self, _mode: QClipboard.Mode):
        return _NonNullImage()


def test_monitoring_skips_stale_text_when_clipboard_contains_an_image(monkeypatch) -> None:
    controller = ClipboardOverlayController.__new__(ClipboardOverlayController)
    controller._monitoring_enabled = True
    controller._clipboard = _ClipboardWithImageAndStaleText()
    controller._status_reporter = lambda _message: None
    submitted: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        ClipboardOverlayController,
        "_submit_text_if_allowed",
        lambda _self, text, force: submitted.append((text, force)),
    )

    controller._handle_clipboard_change()

    assert submitted == []


def test_clip_response_keeps_a_bounded_full_mapping() -> None:
    mapping = "Architecture → Concrete system structure; " * 30

    response = _clip_response(mapping, max_chars=700)

    assert len(response) <= 480
    assert response.endswith("...")


def test_r_hotkey_sends_selected_text_without_considering_clipboard_image(monkeypatch) -> None:
    controller = ClipboardOverlayController.__new__(ClipboardOverlayController)
    controller._clipboard = _ClipboardWithSelectionAndImage()
    controller._status_reporter = lambda _message: None
    submitted: list[str] = []

    monkeypatch.setattr(
        ClipboardOverlayController,
        "_submit_image_if_allowed",
        lambda _self, _image, force: submitted.append(f"image:{force}"),
    )
    monkeypatch.setattr(
        ClipboardOverlayController,
        "_submit_text_if_allowed",
        lambda _self, text, force: submitted.append(f"text:{text}:{force}"),
    )

    controller.send_selected_text_now()

    assert submitted == ["text:stale selected text:True"]


def test_a_hotkey_sends_clipboard_image_without_considering_selected_text(monkeypatch) -> None:
    controller = ClipboardOverlayController.__new__(ClipboardOverlayController)
    controller._clipboard = _ClipboardWithSelectionAndImage()
    controller._status_reporter = lambda _message: None
    submitted: list[str] = []

    monkeypatch.setattr(
        ClipboardOverlayController,
        "_submit_image_if_allowed",
        lambda _self, _image, force: submitted.append(f"image:{force}"),
    )
    monkeypatch.setattr(
        ClipboardOverlayController,
        "_submit_text_if_allowed",
        lambda _self, text, force: submitted.append(f"text:{text}:{force}"),
    )

    controller.send_clipboard_image_now()

    assert submitted == ["image:True"]
