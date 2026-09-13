from clip_overlay_ai.ocr import ImageOCREngine, normalize_ocr_result


def test_normalize_ocr_result_groups_lines_and_filters_low_confidence() -> None:
    raw_result = [
        [[ [10, 10], [50, 10], [50, 24], [10, 24] ], "A.", 0.96],
        [[ [60, 11], [140, 11], [140, 24], [60, 24] ], "Router", 0.94],
        [[ [10, 40], [50, 40], [50, 54], [10, 54] ], "B.", 0.97],
        [[ [60, 41], [150, 41], [150, 54], [60, 54] ], "Switch", 0.95],
        [[ [10, 75], [80, 75], [80, 88], [10, 88] ], "noise", 0.20],
    ]

    result = normalize_ocr_result(raw_result, min_confidence=0.5, max_chars=200)

    assert result is not None
    assert result.text == "A. Router\nB. Switch"
    assert result.line_count == 2


def test_image_ocr_engine_returns_none_when_engine_fails() -> None:
    class _BrokenEngine:
        def __call__(self, _image):
            raise RuntimeError("boom")

    engine = ImageOCREngine(engine=_BrokenEngine())

    assert engine.extract_text(b"not-an-image") is None
