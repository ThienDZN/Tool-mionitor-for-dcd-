from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_SYSTEM_PROMPT = (
    "Reply in Vietnamese in exactly one plain-text line, with no markdown and no explanation. "
    "Infer the question type automatically. "
    "Single-choice: 'Đáp án đúng: <option letter>. <full answer text>'. "
    "Multiple-choice with several correct answers: "
    "'Đáp án đúng: <letters separated by commas>. <full answer text for each correct option>'. "
    "Short answer or fill-in: 'Đáp án đúng: <full answer>'. "
    "Matching/order/card-click or dropdown questions: "
    "'Đáp án đúng: <concept> → <correct option>; <concept> → <correct option>'."
)

SUPPORTED_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})


@dataclass(slots=True)
class AppConfig:
    api_key: str | None
    model: str | None
    base_url: str | None
    system_prompt: str
    overlay_duration_ms: int
    overlay_font_point_size: int
    max_clipboard_chars: int
    max_response_chars: int
    request_timeout_s: float
    resources_dir: Path
    session_context_path: Path
    enable_web_fallback: bool
    web_search_context_size: str
    reasoning_effort: str | None = None
    auto_start_monitoring: bool = True

    def readiness_issues(self) -> list[str]:
        issues: list[str] = []
        if _is_missing_value(self.api_key):
            issues.append("Missing OPENAI_API_KEY")
        if _is_missing_value(self.model):
            issues.append("Missing OPENAI_MODEL")
        if self.reasoning_effort is not None and self.reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
            issues.append("Invalid OPENAI_REASONING_EFFORT")
        return issues


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _get_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and not _is_missing_value(value):
            return value
    return None


def _is_missing_value(value: str | None) -> bool:
    if value is None:
        return True

    normalized = value.strip()
    if not normalized:
        return True

    lowered = normalized.lower()
    placeholder_prefixes = (
        "replace_with_",
        "your_",
        "example",
    )
    return lowered.startswith(placeholder_prefixes)


def load_config() -> AppConfig:
    project_root = _project_root()
    load_dotenv(project_root / ".env", override=False)
    reasoning_effort = _get_env("OPENAI_REASONING_EFFORT", "ANTHROPIC_REASONING_EFFORT")

    return AppConfig(
        api_key=_get_env("OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        model=_get_env(
            "OPENAI_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        ),
        base_url=_get_env("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL") or None,
        system_prompt=os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        overlay_duration_ms=int(os.getenv("OVERLAY_DURATION_MS", "14000")),
        overlay_font_point_size=int(os.getenv("OVERLAY_FONT_POINT_SIZE", "8")),
        max_clipboard_chars=int(os.getenv("MAX_CLIPBOARD_CHARS", "4000")),
        max_response_chars=int(os.getenv("MAX_RESPONSE_CHARS", "480")),
        request_timeout_s=float(os.getenv("REQUEST_TIMEOUT_S", "40")),
        resources_dir=project_root / os.getenv("RESOURCES_DIR", "resources"),
        session_context_path=project_root / os.getenv("SESSION_CONTEXT_PATH", "state/session_context.json"),
        enable_web_fallback=os.getenv("ENABLE_WEB_FALLBACK", "1").strip().lower() not in {"0", "false", "no"},
        web_search_context_size=os.getenv("WEB_SEARCH_CONTEXT_SIZE", "medium").strip().lower() or "medium",
        reasoning_effort=reasoning_effort.strip().lower() if reasoning_effort else None,
        auto_start_monitoring=os.getenv("AUTO_START_MONITORING", "1").strip().lower() not in {"0", "false", "no"},
    )
