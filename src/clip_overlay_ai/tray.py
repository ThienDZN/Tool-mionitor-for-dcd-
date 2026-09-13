from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon


class TrayController(QObject):
    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_send_text: Callable[[], None],
        on_send_image: Callable[[], None],
        on_toggle_overlay: Callable[[], None],
        on_update_context: Callable[[], None],
        on_refresh_resources: Callable[[], None],
        on_clear: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__()
        self._on_toggle = on_toggle
        self._on_send_text = on_send_text
        self._on_send_image = on_send_image
        self._on_toggle_overlay = on_toggle_overlay
        self._on_update_context = on_update_context
        self._on_refresh_resources = on_refresh_resources
        self._on_clear = on_clear
        self._on_quit = on_quit

        style = QApplication.style()
        icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        self._tray = QSystemTrayIcon(QIcon(icon), self)
        self._tray.setToolTip("Clipboard AI Overlay")

        self._menu = QMenu()
        self._state_action = QAction("Monitoring: OFF", self)
        self._state_action.setEnabled(False)
        self._toggle_action = QAction("Enable monitoring", self)
        self._send_text_action = QAction("Send text (R)", self)
        self._send_image_action = QAction("Send clipboard image (A)", self)
        self._toggle_overlay_action = QAction("Toggle overlay (Left Shift)", self)
        self._update_context_action = QAction("Update subject/context", self)
        self._refresh_resources_action = QAction("Refresh resources", self)
        self._clear_action = QAction("Clear overlay", self)
        self._quit_action = QAction("Quit", self)

        self._toggle_action.triggered.connect(self._on_toggle)
        self._send_text_action.triggered.connect(self._on_send_text)
        self._send_image_action.triggered.connect(self._on_send_image)
        self._toggle_overlay_action.triggered.connect(self._on_toggle_overlay)
        self._update_context_action.triggered.connect(self._on_update_context)
        self._refresh_resources_action.triggered.connect(self._on_refresh_resources)
        self._clear_action.triggered.connect(self._on_clear)
        self._quit_action.triggered.connect(self._on_quit)
        self._tray.activated.connect(self._handle_activation)

        self._menu.addAction(self._state_action)
        self._menu.addSeparator()
        self._menu.addAction(self._toggle_action)
        self._menu.addAction(self._send_text_action)
        self._menu.addAction(self._send_image_action)
        self._menu.addAction(self._toggle_overlay_action)
        self._menu.addAction(self._update_context_action)
        self._menu.addAction(self._refresh_resources_action)
        self._menu.addAction(self._clear_action)
        self._menu.addSeparator()
        self._menu.addAction(self._quit_action)
        self._tray.setContextMenu(self._menu)

    def show(self) -> None:
        self._tray.show()

    def notify(self, title: str, text: str) -> None:
        self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 4000)

    def set_enabled(self, enabled: bool) -> None:
        state_text = "Monitoring: ON" if enabled else "Monitoring: OFF"
        toggle_text = "Disable monitoring" if enabled else "Enable monitoring"
        self._state_action.setText(state_text)
        self._toggle_action.setText(toggle_text)
        self._tray.setToolTip(f"Clipboard AI Overlay ({state_text})")

    def set_busy(self, busy: bool) -> None:
        self._send_text_action.setEnabled(not busy)
        self._send_image_action.setEnabled(not busy)
        self._toggle_action.setEnabled(not busy)
        self._toggle_overlay_action.setEnabled(True)
        self._update_context_action.setEnabled(not busy)
        self._refresh_resources_action.setEnabled(not busy)
        if busy:
            self._state_action.setText("Monitoring: RUNNING")
            self._tray.setToolTip("Clipboard AI Overlay (Monitoring: RUNNING)")

    def _handle_activation(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._on_toggle()
