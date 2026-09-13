from __future__ import annotations

import os
import sys
from collections.abc import Callable
from types import ModuleType


class GlobalHotkeyListener:
    def __init__(
        self,
        on_toggle_overlay: Callable[[], None],
        on_send_text: Callable[[], None],
        on_send_image: Callable[[], None],
        session_type: str | None = None,
        keyboard_backend: ModuleType | None = None,
    ) -> None:
        self._on_toggle_overlay = on_toggle_overlay
        self._on_send_text = on_send_text
        self._on_send_image = on_send_image
        self._session_type = (session_type or os.getenv("XDG_SESSION_TYPE", "")).strip().lower()
        self._keyboard_backend = keyboard_backend
        self._listener = None
        self._left_shift_down = False
        self._r_down = False
        self._a_down = False
        self._reason: str | None = None

        if not self._supports_current_session():
            return

        if self._keyboard_backend is None:
            try:
                from pynput import keyboard as pynput_keyboard
            except Exception as exc:  # pragma: no cover - import depends on runtime platform
                self._reason = f"global hotkeys unavailable ({exc})"
                return
            self._keyboard_backend = pynput_keyboard

        self._listener = self._keyboard_backend.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
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

    def _supports_current_session(self) -> bool:
        if sys.platform.startswith("linux"):
            if self._session_type and self._session_type != "x11":
                self._reason = (
                    "global hotkeys are only enabled on X11; "
                    f"current session is {self._session_type}"
                )
                return False

            if not os.getenv("DISPLAY"):
                self._reason = "global hotkeys need an X11 DISPLAY"
                return False

        return True

    def _handle_press(self, key: object) -> None:
        if self._keyboard_backend is None:
            return

        if key == self._keyboard_backend.Key.shift_l and not self._left_shift_down:
            self._left_shift_down = True
            self._on_toggle_overlay()
            return

        char = getattr(key, "char", None)
        if isinstance(char, str) and char.lower() == "r" and not self._r_down:
            self._r_down = True
            self._on_send_text()
            return

        if isinstance(char, str) and char.lower() == "a" and not self._a_down:
            self._a_down = True
            self._on_send_image()

    def _handle_release(self, key: object) -> None:
        if self._keyboard_backend is None:
            return

        if key == self._keyboard_backend.Key.shift_l:
            self._left_shift_down = False
            return

        char = getattr(key, "char", None)
        if isinstance(char, str) and char.lower() == "r":
            self._r_down = False
            return

        if isinstance(char, str) and char.lower() == "a":
            self._a_down = False
