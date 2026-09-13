from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET
import zipfile

from pypdf import PdfReader

from .session_context import SessionContext


_SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-zÀ-ỹ]{2,}", re.UNICODE)
_MAX_CHUNK_CHARS = 900
_CHUNK_OVERLAP_CHARS = 140
_MIN_RELEVANCE_SCORE = 1.6


@dataclass(slots=True)
class ResourceChunk:
    source_path: Path
    label: str
    text: str
    normalized_text: str
    tokens: set[str]


@dataclass(slots=True)
class ResourceHit:
    source_label: str
    excerpt: str
    score: float


class ResourceLibrary:
    def __init__(self, resources_dir: Path) -> None:
        self._resources_dir = resources_dir
        self._snapshot: tuple[tuple[str, float, int], ...] = ()
        self._chunks: list[ResourceChunk] = []
        self._resources_dir.mkdir(parents=True, exist_ok=True)

    def refresh(self) -> None:
        self._chunks = self._load_chunks()
        self._snapshot = self._build_snapshot()

    def search(self, query: str, context: SessionContext, limit: int = 3) -> list[ResourceHit]:
        self._ensure_fresh()
        normalized_query = normalize_text(query)
        if not normalized_query:
            return []

        query_tokens = tokenize(normalized_query)
        if not query_tokens:
            return []

        context_tokens = tokenize(f"{context.subject} {context.description}")
        scored_hits: list[tuple[float, ResourceChunk]] = []

        for chunk in self._chunks:
            score = _score_chunk(chunk, query_tokens, context_tokens, normalized_query)
            if score < _MIN_RELEVANCE_SCORE:
                continue
            scored_hits.append((score, chunk))

        scored_hits.sort(key=lambda item: item[0], reverse=True)
        deduped: list[ResourceHit] = []
        seen_labels: set[str] = set()
        for score, chunk in scored_hits:
            if chunk.label in seen_labels:
                continue
            seen_labels.add(chunk.label)
            deduped.append(
                ResourceHit(
                    source_label=chunk.label,
                    excerpt=_trim_excerpt(chunk.text, 460),
                    score=round(score, 3),
                )
            )
            if len(deduped) >= limit:
                break
        return deduped

    def resource_count(self) -> int:
        self._ensure_fresh()
        return len({chunk.label for chunk in self._chunks})

    def _ensure_fresh(self) -> None:
        current_snapshot = self._build_snapshot()
        if current_snapshot != self._snapshot:
            self.refresh()

    def _build_snapshot(self) -> tuple[tuple[str, float, int], ...]:
        snapshot: list[tuple[str, float, int]] = []
        for path in self._iter_supported_files():
            stat = path.stat()
            snapshot.append((str(path), stat.st_mtime, stat.st_size))
        snapshot.sort()
        return tuple(snapshot)

    def _load_chunks(self) -> list[ResourceChunk]:
        chunks: list[ResourceChunk] = []
        for path in self._iter_supported_files():
            text = self._read_resource_text(path)
            if not text:
                continue
            label = str(path.relative_to(self._resources_dir))
            for chunk_text in chunk_text_blocks(text):
                normalized_chunk = normalize_text(chunk_text)
                tokens = tokenize(normalized_chunk)
                if not tokens:
                    continue
                chunks.append(
                    ResourceChunk(
                        source_path=path,
                        label=label,
                        text=chunk_text.strip(),
                        normalized_text=normalized_chunk,
                        tokens=tokens,
                    )
                )
        return chunks

    def _iter_supported_files(self) -> Iterable[Path]:
        if not self._resources_dir.exists():
            return []
        return sorted(
            path
            for path in self._resources_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES
        )

    def _read_resource_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        try:
            if suffix in {".txt", ".md"}:
                return path.read_text(encoding="utf-8", errors="ignore")
            if suffix == ".pdf":
                return _read_pdf_text(path)
            if suffix == ".docx":
                return _read_docx_text(path)
        except Exception:
            return ""
        return ""


def chunk_text_blocks(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= _MAX_CHUNK_CHARS:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)

    if not chunks:
        return []

    with_overlap: list[str] = [chunks[0]]
    for index in range(1, len(chunks)):
        previous_tail = chunks[index - 1][-_CHUNK_OVERLAP_CHARS :].strip()
        merged = f"{previous_tail}\n{chunks[index]}".strip() if previous_tail else chunks[index]
        with_overlap.append(merged)
    return with_overlap


def normalize_text(text: str) -> str:
    lowered = " ".join(text.split()).strip().lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_PATTERN.findall(normalize_text(text)) if len(token) >= 2}


def _score_chunk(
    chunk: ResourceChunk,
    query_tokens: set[str],
    context_tokens: set[str],
    normalized_query: str,
) -> float:
    if not chunk.tokens:
        return 0.0

    direct_overlap = len(query_tokens & chunk.tokens)
    if direct_overlap == 0:
        return 0.0

    query_density = direct_overlap / max(1, len(query_tokens))
    context_overlap = len(context_tokens & chunk.tokens)
    phrase_boost = 0.8 if normalized_query and normalized_query in chunk.normalized_text else 0.0
    return direct_overlap * 0.9 + query_density * 2.0 + context_overlap * 0.25 + phrase_boost


def _trim_excerpt(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        extracted = page.extract_text() or ""
        if extracted.strip():
            parts.append(extracted)
    return "\n\n".join(parts)


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_data = archive.read("word/document.xml")
    root = ET.fromstring(xml_data)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text_parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(text_parts).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)
