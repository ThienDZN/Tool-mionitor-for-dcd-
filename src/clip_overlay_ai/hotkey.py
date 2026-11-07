from __future__ import annotations

import os
import selectors
import sys
import threading
from collections.abc import Callable, Iterable
from types import ModuleType

# Logical key names shared by every backend.
_LEFT_SHIFT = "shift_l"
_KEY_R = "r"
_KEY_A = "a"


class _EvdevListener:
    """Read key events straight from /dev/input so hotkeys work on Wayland.

    Wayland does not let normal clients see global key presses, so the X11
    (pynput) backend cannot work there. Reading evdev devices needs the user to
    be allowed to read ``/dev/input/event*`` (for example, the ``input`` group).
    """

    EV_KEY = 1
    CODE_LEFTSHIFT = 42
    CODE_R = 19
    CODE_A = 30
    _NAMES = {CODE_LEFTSHIFT: _LEFT_SHIFT, CODE_R: _KEY_R, CODE_A: _KEY_A}

    def __init__(
        self,
        devices: Iterable[object],
        on_press: Callable[[str], None],
        on_release: Callable[[str], None],
    ) -> None:
        self._devices = list(devices)
        self._on_press = on_press
        self._on_release = on_release
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="evdev-hotkeys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        for device in self._devices:
            try:
                device.close()
            except Exception:
                pass

    def _run(self) -> None:
        selector = selectors.DefaultSelector()
        for device in self._devices:
            selector.register(device, selectors.EVENT_READ)
        try:
            while not self._stop.is_set():
                for key, _mask in selector.select(timeout=0.5):
                    try:
                        events = list(key.fileobj.read())
                    except BlockingIOError:
                        continue
                    except OSError:
                        # Device unplugged; stop watching it.
                        selector.unregister(key.fileobj)
                        continue
                    for event in events:
                        self.dispatch(event.type, event.code, event.value)
        finally:
            selector.close()

    def dispatch(self, event_type: int, code: int, value: int) -> None:
        if event_type != self.EV_KEY:
            return
        name = self._NAMES.get(code)
        if name is None:
            return
        if value == 1:
            self._on_press(name)
        elif value == 0:
            self._on_release(name)
        # value == 2 is auto-repeat; ignore it.


def _open_evdev_keyboards(evdev_module: ModuleType) -> tuple[list[object], str | None]:
    paths = evdev_module.list_devices()
    if not paths:
        return [], "cannot read /dev/input; add your user to the 'input' group and log in again"

    keyboards: list[object] = []
    for path in paths:
        try:
            device = evdev_module.InputDevice(path)
        except OSError:
            continue
        keys = device.capabilities().get(_EvdevListener.EV_KEY, [])
        if _EvdevListener.CODE_LEFTSHIFT in keys and _EvdevListener.CODE_A in keys:
            keyboards.append(device)
        else:
            device.close()

    if not keyboards:
        return [], "no readable keyboard in /dev/input; add your user to the 'input' group and log in again"
    return keyboards, None


class GlobalHotkeyListener:
    def __init__(
        self,
        on_toggle_overlay: Callable[[], None],
        on_send_text: Callable[[], None],
        on_send_image: Callable[[], None],
        session_type: str | None = None,
        keyboard_backend: ModuleType | None = None,
        evdev_backend: ModuleType | None = None,
    ) -> None:
        self._on_toggle_overlay = on_toggle_overlay
        self._on_send_text = on_send_text
        self._on_send_image = on_send_image
        self._session_type = (session_type or os.getenv("XDG_SESSION_TYPE", "")).strip().lower()
        self._keyboard_backend = keyboard_backend
        self._listener = None
        self._down: set[str] = set()
        self._reason: str | None = None

        if sys.platform.startswith("linux") and self._session_type == "wayland":
            self._init_evdev(evdev_backend)
            return

        if not self._supports_x11_session():
            return

        if self._keyboard_backend is None:
            try:
                from pynput import keyboard as pynput_keyboard
            except Exception as exc:  # pragma: no cover - import depends on runtime platform
                self._reason = f"global hotkeys unavailable ({exc})"
                return
            self._keyboard_backend = pynput_keyboard

        self._listener = self._keyboard_backend.Listener(
            on_press=self._handle_pynput_press,
            on_release=self._handle_pynput_release,
        )

    @property
    def is_supported(self) -> bool:
        return self._listener is not None

    @property
    def reason(self) -> str | None:
        return self._reason

    def start(self) -> None:
        if self._listener is not None:
            self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    def _init_evdev(self, evdev_backend: ModuleType | None) -> None:
        if evdev_backend is None:
            try:
                import evdev as evdev_backend
            except Exception as exc:  # pragma: no cover - import depends on runtime platform
                self._reason = f"global hotkeys on Wayland need python 'evdev' ({exc})"
                return
        devices, reason = _open_evdev_keyboards(evdev_backend)
        if reason:
            self._reason = reason
            return
        self._listener = _EvdevListener(devices, self._handle_key_press, self._handle_key_release)

    def _supports_x11_session(self) -> bool:
        if sys.platform.startswith("linux"):
            if self._session_type and self._session_type != "x11":
                self._reason = (
                    "global hotkeys need X11 or Wayland; "
                    f"current session is {self._session_type}"
                )
                return False

            if not os.getenv("DISPLAY"):
                self._reason = "global hotkeys need an X11 DISPLAY"
                return False

        return True

    def _pynput_name(self, key: object) -> str | None:
        if self._keyboard_backend is None:
            return None
        if key == self._keyboard_backend.Key.shift_l:
            return _LEFT_SHIFT
        char = getattr(key, "char", None)
        if isinstance(char, str) and char.lower() in {_KEY_R, _KEY_A}:
            return char.lower()
        return None

    def _handle_pynput_press(self, key: object) -> None:
        name = self._pynput_name(key)
        if name is not None:
            self._handle_key_press(name)

    def _handle_pynput_release(self, key: object) -> None:
        name = self._pynput_name(key)
        if name is not None:
            self._handle_key_release(name)

    def _handle_key_press(self, name: str) -> None:
        if name in self._down:
            return
        self._down.add(name)
        if name == _LEFT_SHIFT:
            self._on_toggle_overlay()
        elif name == _KEY_R:
            self._on_send_text()
        elif name == _KEY_A:
            self._on_send_image()

    def _handle_key_release(self, name: str) -> None:
        self._down.discard(name)
