# Project Resources

## Core docs

- [Architecture Brief](./ARCHITECTURE.md)
  Current app structure, trust boundaries, and the main design choices.

- [Runtime Resource Folder](../resources/README.md)
  Folder where you drop study materials so the app can search local files before using web fallback.

## Related implementation areas

- Overlay UI
  `src/clip_overlay_ai/overlay.py`
  Small translucent on-screen answer bar, visibility toggle, drag behavior, and visual states.

- Clipboard + hotkeys
  `src/clip_overlay_ai/app.py`
  `src/clip_overlay_ai/hotkey.py`
  Clipboard monitoring, `R` trigger flow, and `Left Shift` hide/show behavior.

- AI transport + answer formatting
  `src/clip_overlay_ai/ai_client.py`
  Prompt shaping, answer normalization, question-type hints, and image/text request payloads.

- OCR support for screenshots
  `src/clip_overlay_ai/ocr.py`
  Local OCR pre-processing used to improve screenshot accuracy before the image is sent to the model.

- Clipboard safety checks
  `src/clip_overlay_ai/safety.py`
  Secret filtering, text truncation, and image preparation before requests leave the machine.

## Test references

- `tests/test_ai_client.py`
  Covers answer formatting, question-type detection, and image payload construction.

- `tests/test_ocr.py`
  Covers OCR text normalization and failure handling.

- `tests/test_overlay.py`
  Covers overlay visibility and blank-idle behavior.
