from types import SimpleNamespace

from clip_overlay_ai.hotkey import GlobalHotkeyListener


class _FakeListener:
    def __init__(self, on_press, on_release) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _FakeKeyboardModule:
    class Key:
        shift_l = "shift_l"

    def __init__(self) -> None:
        self.instances: list[_FakeListener] = []

    def Listener(self, on_press, on_release):
        listener = _FakeListener(on_press, on_release)
        self.instances.append(listener)
        return listener


def test_global_hotkey_listener_triggers_shift_r_and_a_once_per_press(monkeypatch) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    backend = _FakeKeyboardModule()
    toggles: list[str] = []
    text_sends: list[str] = []
    image_sends: list[str] = []

    listener = GlobalHotkeyListener(
        lambda: toggles.append("toggle"),
        lambda: text_sends.append("text"),
        lambda: image_sends.append("image"),
        session_type="x11",
        keyboard_backend=backend,
    )

    assert listener.is_supported is True
    listener.start()
    backend.instances[0].on_press(backend.Key.shift_l)
    backend.instances[0].on_press(backend.Key.shift_l)
    backend.instances[0].on_release(backend.Key.shift_l)
    backend.instances[0].on_press(backend.Key.shift_l)
    backend.instances[0].on_release(backend.Key.shift_l)
    backend.instances[0].on_press(SimpleNamespace(char="r"))
    backend.instances[0].on_press(SimpleNamespace(char="r"))
    backend.instances[0].on_release(SimpleNamespace(char="r"))
    backend.instances[0].on_press(SimpleNamespace(char="R"))
    backend.instances[0].on_release(SimpleNamespace(char="R"))
    backend.instances[0].on_press(SimpleNamespace(char="a"))
    backend.instances[0].on_press(SimpleNamespace(char="a"))
    backend.instances[0].on_release(SimpleNamespace(char="a"))
    backend.instances[0].on_press(SimpleNamespace(char="A"))
    listener.stop()

    assert toggles == ["toggle", "toggle"]
    assert text_sends == ["text", "text"]
    assert image_sends == ["image", "image"]
    assert backend.instances[0].started is True
    assert backend.instances[0].stopped is True


def test_global_hotkey_listener_rejects_non_x11_linux_session(monkeypatch) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    backend = _FakeKeyboardModule()

    listener = GlobalHotkeyListener(
        lambda: None,
        lambda: None,
        lambda: None,
        session_type="wayland",
        keyboard_backend=backend,
    )

    assert listener.is_supported is False
    assert "only enabled on X11" in (listener.reason or "")
