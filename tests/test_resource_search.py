from pathlib import Path

from clip_overlay_ai.resource_search import ResourceLibrary
from clip_overlay_ai.session_context import SessionContext


def test_resource_library_prioritizes_local_matching_content(tmp_path: Path) -> None:
    resources_dir = tmp_path / "resources"
    resources_dir.mkdir()
    (resources_dir / "network.md").write_text(
        "# Dia chi MAC\n\nA. Router\nB. Destination MAC address\nC. Hub\n",
        encoding="utf-8",
    )
    (resources_dir / "english.md").write_text(
        "# TOEIC\n\nThis file is about grammar only.\n",
        encoding="utf-8",
    )

    library = ResourceLibrary(resources_dir)
    hits = library.search(
        query="Mang may tinh dia chi MAC cau hoi destination MAC address",
        context=SessionContext(subject="Mang may tinh", description="MAC address"),
    )

    assert hits
    assert hits[0].source_label == "network.md"
    assert "Destination MAC address" in hits[0].excerpt


def test_resource_library_refresh_detects_new_files(tmp_path: Path) -> None:
    resources_dir = tmp_path / "resources"
    resources_dir.mkdir()
    library = ResourceLibrary(resources_dir)

    assert library.resource_count() == 0

    (resources_dir / "new.txt").write_text("Switch la thiet bi mang.", encoding="utf-8")

    hits = library.search(
        query="thiet bi mang switch",
        context=SessionContext(subject="Mang may tinh", description=""),
    )

    assert library.resource_count() == 1
    assert hits
