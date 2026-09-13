from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any

import numpy as np
from PIL import Image, ImageOps

try:  # pragma: no cover - dependency availability is environment-specific
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover - dependency availability is environment-specific
    RapidOCR = None


_MIN_OCR_CONFIDENCE = 0.58
_MAX_OCR_CHARS = 5000
_TARGET_OCR_EDGE = 1800


@dataclass(slots=True)
class OCRTextResult:
    text: str
    confidence: float
    line_count: int


@dataclass(slots=True)
class _OCRFragment:
    top: float
    left: float
    height: float
    text: str
    score: float


class ImageOCREngine:
    def __init__(
        self,
        engine: Any | None = None,
        min_confidence: float = _MIN_OCR_CONFIDENCE,
        max_chars: int = _MAX_OCR_CHARS,
    ) -> None:
        self._engine = engine
        self._min_confidence = min_confidence
        self._max_chars = max_chars

    @property
    def is_available(self) -> bool:
        return self._engine is not None or RapidOCR is not None

    def extract_text(self, png_bytes: bytes) -> OCRTextResult | None:
        if not self.is_available:
            return None

        if self._engine is None:
            self._engine = RapidOCR()

        try:
            image = prepare_image_for_ocr(png_bytes)
            raw_result, _ = self._engine(image)
        except Exception:
            return None

        return normalize_ocr_result(
            raw_result,
            min_confidence=self._min_confidence,
            max_chars=self._max_chars,
        )


def prepare_image_for_ocr(png_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(png_bytes)).convert("L")
    image = ImageOps.autocontrast(image)

    max_edge = max(image.width, image.height)
    if 0 < max_edge < _TARGET_OCR_EDGE:
        scale = _TARGET_OCR_EDGE / max_edge
        new_size = (
            max(1, int(image.width * scale)),
            max(1, int(image.height * scale)),
        )
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    return np.array(image)


def normalize_ocr_result(
    raw_result: list[list[Any]] | None,
    min_confidence: float = _MIN_OCR_CONFIDENCE,
    max_chars: int = _MAX_OCR_CHARS,
) -> OCRTextResult | None:
    fragments = _collect_fragments(raw_result, min_confidence=min_confidence)
    if not fragments:
        return None

    lines = _group_fragments_into_lines(fragments)
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return None

    if len(text) > max_chars:
        text = text[:max_chars].rstrip()

    avg_confidence = sum(fragment.score for fragment in fragments) / len(fragments)
    return OCRTextResult(text=text, confidence=avg_confidence, line_count=len(lines))


def _collect_fragments(
    raw_result: list[list[Any]] | None,
    min_confidence: float,
) -> list[_OCRFragment]:
    fragments: list[_OCRFragment] = []
    if not raw_result:
        return fragments

    for entry in raw_result:
        if len(entry) < 3:
            continue
        box, text, score = entry[0], entry[1], entry[2]
        if not isinstance(text, str):
            continue
        normalized_text = re.sub(r"\s+", " ", text).strip()
        if not normalized_text:
            continue
        if not isinstance(score, (int, float)) or score < min_confidence:
            continue
        left, top, height = _box_metrics(box)
        fragments.append(
            _OCRFragment(
                top=top,
                left=left,
                height=height,
                text=normalized_text,
                score=float(score),
            )
        )
    return fragments


def _group_fragments_into_lines(fragments: list[_OCRFragment]) -> list[str]:
    sorted_fragments = sorted(fragments, key=lambda item: (item.top, item.left))
    lines: list[list[_OCRFragment]] = []

    for fragment in sorted_fragments:
        if not lines:
            lines.append([fragment])
            continue

        previous_line = lines[-1]
        baseline = sum(item.top for item in previous_line) / len(previous_line)
        threshold = max(14.0, min(fragment.height, _average_height(previous_line)) * 0.75)
        if abs(fragment.top - baseline) <= threshold:
            previous_line.append(fragment)
            continue
        lines.append([fragment])

    normalized_lines: list[str] = []
    for line in lines:
        line_text = " ".join(item.text for item in sorted(line, key=lambda item: item.left)).strip()
        if not line_text:
            continue
        if normalized_lines and normalized_lines[-1] == line_text:
            continue
        normalized_lines.append(line_text)
    return normalized_lines


def _average_height(fragments: list[_OCRFragment]) -> float:
    return sum(item.height for item in fragments) / len(fragments)


def _box_metrics(box: Any) -> tuple[float, float, float]:
    if not isinstance(box, list) or len(box) < 4:
        return 0.0, 0.0, 0.0

    xs: list[float] = []
    ys: list[float] = []
    for point in box:
        if not isinstance(point, list) or len(point) < 2:
            continue
        xs.append(float(point[0]))
        ys.append(float(point[1]))

    if not xs or not ys:
        return 0.0, 0.0, 0.0

    return min(xs), min(ys), max(ys) - min(ys)
