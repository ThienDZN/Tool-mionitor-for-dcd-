from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from clip_overlay_ai.ai_client import OpenAIResponsesClient
from clip_overlay_ai.app import AnswerBatch, _safe_question_error_message
from clip_overlay_ai.config import AppConfig
from clip_overlay_ai.question_splitter import DetectedQuestion, split_numbered_questions
from clip_overlay_ai.safety import PreparedClipboardImage, PreparedClipboardText
from clip_overlay_ai.session_context import SessionContext


class _RecordingContextStore:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def load(self) -> SessionContext:
        self._events.append("context-loaded")
        return SessionContext()


class _PreparationOrderClient(OpenAIResponsesClient):
    def __init__(self, config: AppConfig, events: list[str]) -> None:
        super().__init__(
            config,
            session_context_store=_RecordingContextStore(events),
            resource_library=object(),  # type: ignore[arg-type]
        )
        self._events = events

    def _prepare_text_questions(  # type: ignore[override]
        self,
        payload: PreparedClipboardText,
        session_context: SessionContext,
        resource_library: object,
        questions: list[DetectedQuestion],
    ) -> list[object]:
        del payload, session_context, resource_library
        self._events.append(f"prepared-{len(questions)}")
        return []


class _ImagePreparationOrderClient(OpenAIResponsesClient):
    def __init__(self, config: AppConfig, events: list[str]) -> None:
        super().__init__(
            config,
            session_context_store=_RecordingContextStore(events),
            resource_library=object(),  # type: ignore[arg-type]
        )
        self._events = events

    def _extract_ocr_result(self, payload: PreparedClipboardImage) -> object:
        del payload
        self._events.append("ocr-complete")
        return type(
            "OCRResult",
            (),
            {
                "text": "Câu 31: A\nCâu 32: B\nCâu 33: C\nCâu 34: D",
                "confidence": 0.99,
                "line_count": 4,
            },
        )()

    def _prepare_ocr_questions(  # type: ignore[override]
        self,
        questions: list[DetectedQuestion],
        session_context: SessionContext,
        resource_library: object,
    ) -> list[object]:
        del session_context, resource_library
        self._events.append(f"prepared-{len(questions)}")
        return []


def _config() -> AppConfig:
    return AppConfig(
        api_key="test-key",
        model="test-model",
        base_url=None,
        system_prompt="test",
        overlay_duration_ms=1,
        overlay_font_point_size=8,
        max_clipboard_chars=12000,
        max_response_chars=480,
        request_timeout_s=40,
        resources_dir=Path("resources"),
        session_context_path=Path("state/session_context.json"),
        enable_web_fallback=False,
        web_search_context_size="medium",
    )


class MultiQuestionProgressTests(TestCase):
    def test_default_limits_allow_eight_parallel_one_minute_questions(self) -> None:
        config = _config()

        self.assertEqual(config.max_parallel_questions, 8)
        self.assertEqual(config.per_question_time_budget_s, 60.0)

    def test_finished_answers_are_first_in_completion_order(self) -> None:
        batch = AnswerBatch(
            detected_questions=[
                DetectedQuestion(number=31, label="Câu 31", text="Q31"),
                DetectedQuestion(number=32, label="Câu 32", text="Q32"),
                DetectedQuestion(number=33, label="Câu 33", text="Q33"),
                DetectedQuestion(number=34, label="Câu 34", text="Q34"),
            ]
        )

        self.assertEqual(
            batch.progress_text(),
            "Câu 31: RUNNING\nCâu 32: RUNNING\nCâu 33: RUNNING\nCâu 34: RUNNING",
        )

        batch.record_completion(2, batch.result_line(2, "Đáp án đúng: B. ví dụ"))
        self.assertEqual(
            batch.progress_text(),
            "Câu 33: B. ví dụ\n"
            "Câu 31: RUNNING\nCâu 32: RUNNING\nCâu 34: RUNNING",
        )

        batch.record_completion(0, batch.result_line(0, "Đáp án đúng: A. ví dụ"))
        self.assertEqual(
            batch.progress_text(),
            "Câu 33: B. ví dụ\n"
            "Câu 31: A. ví dụ\n"
            "Câu 32: RUNNING\nCâu 34: RUNNING",
        )

    def test_one_unlabelled_question_keeps_the_simple_running_line(self) -> None:
        batch = AnswerBatch(
            detected_questions=[DetectedQuestion(number=None, label=None, text="What is 2 + 2?")]
        )

        self.assertEqual(batch.progress_text(), "RUNNING")
        batch.record_completion(0, batch.result_line(0, "Đáp án đúng: 4"))
        self.assertTrue(batch.is_complete)
        self.assertEqual(batch.progress_text(), "Đáp án đúng: 4")

    def test_unnumbered_questions_never_receive_an_invented_label(self) -> None:
        batch = AnswerBatch(
            detected_questions=[
                DetectedQuestion(number=None, label=None, text="First"),
                DetectedQuestion(number=None, label=None, text="Second"),
            ]
        )

        self.assertEqual(batch.result_line(0, "Đáp án đúng: A"), "Đáp án đúng: A")

    def test_single_named_question_keeps_its_detected_number_in_the_overlay(self) -> None:
        questions = split_numbered_questions("Câu 31: Chọn đáp án đúng?\nA. Một\nB. Hai")
        batch = AnswerBatch(detected_questions=questions)

        self.assertEqual(batch.progress_text(), "Câu 31: RUNNING")
        self.assertEqual(
            batch.result_line(0, "Đáp án đúng: B. Hai"),
            "Câu 31: B. Hai",
        )

    def test_provider_error_details_are_not_shown_in_the_overlay(self) -> None:
        provider_detail = "gateway echoed copied text: secret-like-value"

        message = _safe_question_error_message(provider_detail)

        self.assertEqual(message, "AI error: Không thể lấy đáp án. Kiểm tra mạng hoặc cấu hình rồi thử lại.")
        self.assertNotIn(provider_detail, message)

    def test_detection_callback_precedes_context_and_prompt_preparation(self) -> None:
        events: list[str] = []
        client = _PreparationOrderClient(_config(), events)
        payload = PreparedClipboardText(text="Câu 31: A\nCâu 32: B", truncated=False)

        client.prepare_batch(
            payload,
            on_questions_detected=lambda questions: events.append(f"detected-{len(questions)}"),
        )

        self.assertEqual(events, ["detected-2", "context-loaded", "prepared-2"])

    def test_image_detection_callback_precedes_prompt_preparation(self) -> None:
        events: list[str] = []
        client = _ImagePreparationOrderClient(_config(), events)
        payload = PreparedClipboardImage(
            data_url="data:image/png;base64,AA==",
            png_bytes=b"image",
            width=10,
            height=10,
        )

        client.prepare_batch(
            payload,
            on_questions_detected=lambda questions: events.append(f"detected-{len(questions)}"),
        )

        self.assertEqual(
            events,
            ["ocr-complete", "detected-4", "context-loaded", "prepared-4"],
        )
