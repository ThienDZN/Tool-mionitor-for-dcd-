from pathlib import Path

from clip_overlay_ai.config import AppConfig, load_config


def test_readiness_issues_treats_placeholder_values_as_missing() -> None:
    config = AppConfig(
        api_key="replace_with_your_api_key",
        model="replace_with_model_available_to_your_account",
        base_url=None,
        system_prompt="x",
        overlay_duration_ms=1000,
        overlay_font_point_size=8,
        max_clipboard_chars=4000,
        max_response_chars=700,
        request_timeout_s=40.0,
        resources_dir=Path("/tmp/resources"),
        session_context_path=Path("/tmp/state/session_context.json"),
        enable_web_fallback=True,
        web_search_context_size="medium",
    )

    assert config.readiness_issues() == [
        "Missing OPENAI_API_KEY",
        "Missing OPENAI_MODEL",
    ]


def test_readiness_issues_accepts_real_values() -> None:
    config = AppConfig(
        api_key="valid-test-api-key",
        model="gpt-5-codex",
        base_url=None,
        system_prompt="x",
        overlay_duration_ms=1000,
        overlay_font_point_size=8,
        max_clipboard_chars=4000,
        max_response_chars=700,
        request_timeout_s=40.0,
        resources_dir=Path("/tmp/resources"),
        session_context_path=Path("/tmp/state/session_context.json"),
        enable_web_fallback=True,
        web_search_context_size="medium",
    )

    assert config.readiness_issues() == []
    assert config.auto_start_monitoring is True


def test_readiness_issues_rejects_unknown_reasoning_effort() -> None:
    config = AppConfig(
        api_key="valid-test-api-key",
        model="gpt-5.6-terra",
        base_url=None,
        system_prompt="x",
        overlay_duration_ms=1000,
        overlay_font_point_size=8,
        max_clipboard_chars=4000,
        max_response_chars=700,
        request_timeout_s=40.0,
        resources_dir=Path("/tmp/resources"),
        session_context_path=Path("/tmp/state/session_context.json"),
        enable_web_fallback=True,
        web_search_context_size="medium",
        reasoning_effort="very-high",
    )

    assert config.readiness_issues() == ["Invalid OPENAI_REASONING_EFFORT"]


def test_load_config_accepts_anthropic_style_fallbacks(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-from-gateway")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "gpt-5.4")
    monkeypatch.setenv("ANTHROPIC_REASONING_EFFORT", "XHIGH")
    monkeypatch.setenv("AUTO_START_MONITORING", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    config = load_config()

    assert config.api_key == "token-from-gateway"
    assert config.base_url == "https://gateway.example"
    assert config.model == "gpt-5.4"
    assert config.reasoning_effort == "xhigh"
    assert config.auto_start_monitoring is False
    assert config.resources_dir.name == "resources"
    assert config.session_context_path.name == "session_context.json"
