from clip_overlay_ai import main


class _Config:
    model = "gpt-5.6-terra"
    reasoning_effort = "xhigh"
    auto_start_monitoring = True

    def readiness_issues(self) -> list[str]:
        return []


def test_run_reports_terminal_startup_stages(monkeypatch, capsys) -> None:
    class _Application:
        def __init__(self, _argv: list[str]) -> None:
            pass

        def setApplicationName(self, _name: str) -> None:
            pass

        def setQuitOnLastWindowClosed(self, _enabled: bool) -> None:
            pass

        def exec(self) -> int:
            return 0

    class _Controller:
        def __init__(self, _app: _Application, _config: _Config, status_reporter=None) -> None:
            self.monitoring_enabled = True
            if status_reporter is not None:
                status_reporter("[STARTUP] Tray icon is visible.")

    monkeypatch.setattr(main, "QApplication", _Application)
    monkeypatch.setattr(main, "ClipboardOverlayController", _Controller)
    monkeypatch.setattr(main, "load_config", lambda: _Config())

    assert main.run() == 0

    output = capsys.readouterr().out
    assert "[STARTUP] Loading configuration." in output
    assert "[CONFIG] Model: gpt-5.6-terra; reasoning: xhigh." in output
    assert "[CONFIG] Image verification: 2 independent passes for A." in output
    assert "[STARTUP] Tray icon is visible." in output
    assert "[READY] Monitoring is ON. New clipboard content will be sent automatically." in output


def test_run_reports_startup_errors(monkeypatch, capsys) -> None:
    class _Application:
        def __init__(self, _argv: list[str]) -> None:
            pass

        def setApplicationName(self, _name: str) -> None:
            pass

        def setQuitOnLastWindowClosed(self, _enabled: bool) -> None:
            pass

    class _Controller:
        def __init__(self, _app: _Application, _config: _Config, status_reporter=None) -> None:
            raise RuntimeError("System tray is not available in this desktop session.")

    monkeypatch.setattr(main, "QApplication", _Application)
    monkeypatch.setattr(main, "ClipboardOverlayController", _Controller)
    monkeypatch.setattr(main, "load_config", lambda: _Config())

    assert main.run() == 1

    assert "[ERROR] Startup failed: System tray is not available" in capsys.readouterr().out
