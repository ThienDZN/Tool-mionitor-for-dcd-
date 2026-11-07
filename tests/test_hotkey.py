from __future__ import annotations

from types import SimpleNamespace

import pytest

from clip_overlay_ai import hotkey
from clip_overlay_ai.hotkey import GlobalHotkeyListener, _EvdevListener

pytestmark = pytest.mark.skipif(not hotkey.sys.platform.startswith("linux"), reason="Linux only")

EV_KEY, KEY_LEFTSHIFT, KEY_R, KEY_A = 1, 42, 19, 30


class FakeDevice:
    def __init__(self, keys: list[int]) -> None:
        self._keys = keys
        self.closed = False

    def capabilities(self) -> dict[int, list[int]]:
        return {EV_KEY: self._keys}

    def close(self) -> None:
        self.closed = True


def fake_evdev(devices: dict[str, FakeDevice | Exception]) -> SimpleNamespace:
    def input_device(path: str) -> FakeDevice:
        item = devices[path]
        if isinstance(item, Exception):
            raise item
        return item

    return SimpleNamespace(list_devices=lambda: list(devices), InputDevice=input_device)


def make_listener(evdev_backend: SimpleNamespace) -> tuple[GlobalHotkeyListener, list[str]]:
    calls: list[str] = []
    listener = GlobalHotkeyListener(
        on_toggle_overlay=lambda: calls.append("toggle"),
        on_send_text=lambda: calls.append("text"),
        on_send_image=lambda: calls.append("image"),
        session_type="wayland",
        evdev_backend=evdev_backend,
    )
    return listener, calls


def test_wayland_uses_evdev_keyboard_and_skips_other_devices() -> None:
    keyboard = FakeDevice([KEY_LEFTSHIFT, KEY_A, KEY_R])
    mouse = FakeDevice([272])
    listener, _ = make_listener(
        fake_evdev({"/dev/input/event0": mouse, "/dev/input/event1": keyboard})
    )

    assert listener.is_supported
    assert listener.reason is None
    assert mouse.closed
    assert not keyboard.closed


def test_wayland_without_input_permission_reports_reason() -> None:
    listener, _ = make_listener(
        fake_evdev({"/dev/input/event0": PermissionError("denied")})
    )

    assert not listener.is_supported
    assert "input" in (listener.reason or "")


def test_wayland_with_no_devices_reports_reason() -> None:
    listener, _ = make_listener(fake_evdev({}))

    assert not listener.is_supported
    assert "input" in (listener.reason or "")


def test_left_shift_toggles_once_per_press_and_ignores_repeat() -> None:
    listener, calls = make_listener(
        fake_evdev({"/dev/input/event0": FakeDevice([KEY_LEFTSHIFT, KEY_A])})
    )
    evdev_listener = listener._listener
    assert isinstance(evdev_listener, _EvdevListener)

    evdev_listener.dispatch(EV_KEY, KEY_LEFTSHIFT, 1)  # press
    evdev_listener.dispatch(EV_KEY, KEY_LEFTSHIFT, 2)  # auto-repeat
    evdev_listener.dispatch(EV_KEY, KEY_LEFTSHIFT, 0)  # release
    evdev_listener.dispatch(EV_KEY, KEY_LEFTSHIFT, 1)  # press again

    assert calls == ["toggle", "toggle"]


def test_r_and_a_send_text_and_image_and_other_keys_are_ignored() -> None:
    listener, calls = make_listener(
        fake_evdev({"/dev/input/event0": FakeDevice([KEY_LEFTSHIFT, KEY_A])})
    )
    evdev_listener = listener._listener

    evdev_listener.dispatch(EV_KEY, KEY_R, 1)
    evdev_listener.dispatch(EV_KEY, KEY_A, 1)
    evdev_listener.dispatch(EV_KEY, 57, 1)  # space
    evdev_listener.dispatch(2, 0, 5)  # relative mouse motion

    assert calls == ["text", "image"]


def test_x11_still_uses_pynput_backend() -> None:
    class Key:
        shift_l = object()

    class Listener:
        def __init__(self, on_press, on_release) -> None:
            self.on_press = on_press
            self.on_release = on_release

    backend = SimpleNamespace(Key=Key, Listener=Listener)
    calls: list[str] = []
    listener = GlobalHotkeyListener(
        on_toggle_overlay=lambda: calls.append("toggle"),
        on_send_text=lambda: calls.append("text"),
        on_send_image=lambda: calls.append("image"),
        session_type="x11",
        keyboard_backend=backend,
    )
    if not listener.is_supported:
        pytest.skip(listener.reason or "no DISPLAY")

    pynput_listener = listener._listener
    pynput_listener.on_press(Key.shift_l)
    pynput_listener.on_press(SimpleNamespace(char="R"))
    pynput_listener.on_release(Key.shift_l)
    pynput_listener.on_press(Key.shift_l)

    assert calls == ["toggle", "text", "toggle"]
