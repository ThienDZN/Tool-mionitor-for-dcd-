from pathlib import Path

from clip_overlay_ai.session_context import SessionContext, SessionContextStore


def test_session_context_store_round_trips_json(tmp_path: Path) -> None:
    store = SessionContextStore(tmp_path / "state" / "session_context.json")

    saved = store.save(SessionContext(subject=" Mang may tinh ", description=" MAC address basics "))
    loaded = store.load()

    assert saved.subject == "Mang may tinh"
    assert saved.description == "MAC address basics"
    assert loaded == saved


def test_session_context_summary_prefers_subject() -> None:
    context = SessionContext(subject="TOEIC", description="Part 5 grammar")

    assert context.summary() == "TOEIC"
