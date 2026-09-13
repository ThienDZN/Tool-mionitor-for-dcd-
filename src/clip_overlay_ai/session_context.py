from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtWidgets import QInputDialog, QWidget


@dataclass(slots=True)
class SessionContext:
    subject: str = ""
    description: str = ""

    def normalized(self) -> SessionContext:
        return SessionContext(
            subject=" ".join(self.subject.split()).strip(),
            description=" ".join(self.description.split()).strip(),
        )

    def is_empty(self) -> bool:
        normalized = self.normalized()
        return not normalized.subject and not normalized.description

    def to_query_prefix(self) -> str:
        normalized = self.normalized()
        parts = []
        if normalized.subject:
            parts.append(f"Mon hoc: {normalized.subject}")
        if normalized.description:
            parts.append(f"Mo ta: {normalized.description}")
        return "\n".join(parts)

    def summary(self) -> str:
        normalized = self.normalized()
        if normalized.subject:
            return normalized.subject
        if normalized.description:
            return normalized.description[:48]
        return "chua dat"


class SessionContextStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> SessionContext:
        if not self._path.exists():
            return SessionContext()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return SessionContext()
        if not isinstance(data, dict):
            return SessionContext()
        return SessionContext(
            subject=str(data.get("subject", "")),
            description=str(data.get("description", "")),
        ).normalized()

    def save(self, context: SessionContext) -> SessionContext:
        normalized = context.normalized()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(asdict(normalized), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalized


def prompt_for_session_context(
    parent: QWidget | None,
    initial: SessionContext,
) -> SessionContext:
    initial = initial.normalized()

    subject, subject_ok = QInputDialog.getText(
        parent,
        "Mon hoc / Context",
        "Nhap ten mon hoc hoac chu de lien quan:",
        text=initial.subject,
    )
    if not subject_ok:
        return initial

    description, description_ok = QInputDialog.getMultiLineText(
        parent,
        "Mo ta bo sung",
        "Nhap mo ta, de cuong, pham vi can uu tien tim tai lieu va research:",
        initial.description,
    )
    if not description_ok:
        return initial

    return SessionContext(subject=subject, description=description).normalized()
