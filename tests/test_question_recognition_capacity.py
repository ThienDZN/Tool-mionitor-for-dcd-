from __future__ import annotations

from io import BytesIO
import os
from unittest import TestCase
from unittest.mock import patch

from PIL import Image

from clip_overlay_ai.ai_client import (
    GatewayRequestError,
    OpenAIResponsesClient,
    _ask_until_usable,
    _looks_like_usable_answer,
    _parse_retry_after_seconds,
    detect_question_type,
    normalize_answer_output,
)
from clip_overlay_ai.config import load_config
from clip_overlay_ai.ocr import prepare_image_for_ocr
from clip_overlay_ai.question_splitter import split_numbered_questions
from clip_overlay_ai.safety import PreparedClipboardText


class QuestionRecognitionCapacityTests(TestCase):
    def test_accepts_common_ocr_heading_variants(self) -> None:
        questions = split_numbered_questions(
            "Câu31: Chọn đáp án đúng.\n"
            "Câu hỏi 32: Tìm x.\n"
            "Question No. 33: Which option is correct?\n"
            "Q34: Solve the equation."
        )

        self.assertEqual([question.label for question in questions], ["Câu 31", "Câu 32", "Câu 33", "Câu 34"])

    def test_accepts_vietnamese_so_labels_and_common_ocr_digit_confusion(self) -> None:
        questions = split_numbered_questions(
            "Câu hỏi số 3l: Chọn đáp án đúng.\n"
            "Câu số 32: Chọn đáp án đúng."
        )

        self.assertEqual([question.label for question in questions], ["Câu 31", "Câu 32"])

    def test_ocr_digit_repair_does_not_split_regular_words(self) -> None:
        questions = split_numbered_questions(
            "Câu lỗi này không phải là nhãn số.\n"
            "Câu 2: Tìm đáp án đúng?"
        )

        self.assertEqual(len(questions), 1)
        self.assertIsNone(questions[0].number)

    def test_splits_flattened_copied_named_questions(self) -> None:
        questions = split_numbered_questions(
            "Câu 31: Chọn đáp án đúng? Câu 32: Chọn đáp án đúng?"
        )

        self.assertEqual([question.label for question in questions], ["Câu 31", "Câu 32"])

    def test_accepts_non_consecutive_bare_questions_when_cues_are_clear(self) -> None:
        questions = split_numbered_questions(
            "31: Tìm nghiệm của phương trình.\n"
            "33: Giải bất phương trình sau."
        )

        self.assertEqual([question.label for question in questions], ["Câu 31", "Câu 33"])

    def test_does_not_treat_numbered_options_as_questions(self) -> None:
        text = "Chọn đáp án đúng:\n1. A. Phương án một\n2. B. Phương án hai"

        questions = split_numbered_questions(text)

        self.assertEqual(len(questions), 1)
        self.assertIsNone(questions[0].number)

    def test_matching_answers_are_accepted_when_choices_are_lettered(self) -> None:
        question = (
            "Nối các thẻ với đáp án đúng.\n"
            "1. GPIO\n2. ADC\n"
            "A. Input/output\nB. Bộ nhớ Flash\nC. Chuyển analog sang số"
        )

        self.assertTrue(_looks_like_usable_answer("Đáp án đúng: 1-A, 2-C", question))

    def test_matching_answer_must_cover_each_numbered_card(self) -> None:
        question = (
            "Nối các thẻ với đáp án đúng.\n"
            "1. GPIO\n2. ADC\n"
            "A. Input/output\nB. Bộ nhớ Flash\nC. Chuyển analog sang số"
        )

        self.assertFalse(_looks_like_usable_answer("Đáp án đúng: 1-A", question))
        self.assertTrue(_looks_like_usable_answer("Đáp án đúng: GPIO → A; ADC → C", question))

    def test_multi_answer_connectors_are_normalized_and_accepted(self) -> None:
        question = (
            "Chọn các đáp án đúng, có thể chọn nhiều.\n"
            "A. I2C có SDA\nB. UART dùng SCL\nC. I2C có SCL\nD. PWM là bộ nhớ"
        )

        self.assertTrue(_looks_like_usable_answer("Đáp án đúng: A và C", question))
        self.assertEqual(normalize_answer_output("A và C. I2C dùng SDA và SCL"), "Đáp án đúng: A, C")

    def test_answer_text_is_kept_when_no_choice_letters_are_returned(self) -> None:
        self.assertEqual(
            normalize_answer_output("Đáp án đúng: I2C và SPI đều dùng truyền thông nối tiếp."),
            "Đáp án đúng: I2C và SPI đều dùng truyền thông nối tiếp",
        )

    def test_card_matching_and_multiple_select_prompts_keep_all_answers(self) -> None:
        matching = "Kéo thả các thẻ cho đúng.\nA. GPIO\nB. ADC"
        multi_select = "Chọn một hoặc nhiều đáp án đúng.\nA. SDA\nB. TX\nC. SCL"

        self.assertEqual(detect_question_type(matching), "matching")
        self.assertEqual(detect_question_type(multi_select), "multi_select")
        self.assertEqual(normalize_answer_output("1 → A; 2 → C"), "Đáp án đúng: 1 → A; 2 → C")

    def test_small_images_are_upscaled_to_preserve_question_numbers(self) -> None:
        image = Image.new("L", (80, 40), color=255)
        buffer = BytesIO()
        image.save(buffer, format="PNG")

        prepared = prepare_image_for_ocr(buffer.getvalue())

        self.assertEqual(max(prepared.shape), 2400)

    def test_rate_limit_retry_honors_server_delay(self) -> None:
        calls = iter(
            [
                GatewayRequestError("HTTP 429", status_code=429, retry_after_s=3.0),
                "Đáp án đúng: B",
            ]
        )
        delays: list[float] = []

        def attempt_call() -> str:
            outcome = next(calls)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with patch("clip_overlay_ai.ai_client.random.uniform", return_value=0.0):
            result = _ask_until_usable(attempt_call, sleep=delays.append)

        self.assertEqual(result, "Đáp án đúng: B")
        self.assertEqual(delays, [3.0])

    def test_retry_status_does_not_echo_gateway_error_details(self) -> None:
        calls = iter(
            [
                GatewayRequestError("untrusted provider detail", status_code=429),
                "Đáp án đúng: B",
            ]
        )
        reports: list[str] = []

        def attempt_call() -> str:
            outcome = next(calls)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with patch("clip_overlay_ai.ai_client.random.uniform", return_value=0.0):
            _ask_until_usable(attempt_call, report=reports.append, sleep=lambda _delay: None)

        self.assertEqual(reports, ["[RETRY] Attempt 1/4 failed; retrying."])

    def test_invalid_retry_after_is_ignored(self) -> None:
        self.assertEqual(_parse_retry_after_seconds("2.5"), 2.5)
        self.assertIsNone(_parse_retry_after_seconds("not-a-delay"))
        self.assertIsNone(_parse_retry_after_seconds("-1"))

    def test_invalid_clipboard_limit_falls_back_to_the_safe_default(self) -> None:
        with (
            patch.dict(os.environ, {"MAX_CLIPBOARD_CHARS": "not-a-number"}, clear=True),
            patch("clip_overlay_ai.config.load_dotenv") as load_dotenv,
        ):
            config = load_config()

        self.assertEqual(config.max_clipboard_chars, 12000)
        self.assertTrue(load_dotenv.call_args.kwargs["override"])

    def test_rate_limited_chat_request_does_not_try_a_second_endpoint(self) -> None:
        class ClientDouble:
            _ask_once = OpenAIResponsesClient._ask_once

            def __init__(self) -> None:
                self.responses_called = False

            def _ask_via_chat_completions(self, *args, **kwargs) -> str:
                del args, kwargs
                raise GatewayRequestError("HTTP 429", status_code=429, retry_after_s=1.0)

            def _ask_via_responses(self, *args, **kwargs) -> str:
                del args, kwargs
                self.responses_called = True
                return "should not be called"

        client = ClientDouble()

        with self.assertRaises(GatewayRequestError):
            client._ask_once(PreparedClipboardText("test", False), "test", allow_web_search=False)

        self.assertFalse(client.responses_called)

    def test_rate_limited_fallback_preserves_the_retryable_error(self) -> None:
        class ClientDouble:
            _ask_once = OpenAIResponsesClient._ask_once

            def _ask_via_chat_completions(self, *args, **kwargs) -> str:
                del args, kwargs
                raise GatewayRequestError("Chat route is unavailable", status_code=404)

            def _ask_via_responses(self, *args, **kwargs) -> str:
                del args, kwargs
                raise GatewayRequestError("HTTP 429", status_code=429, retry_after_s=2.0)

        client = ClientDouble()

        with self.assertRaises(GatewayRequestError) as captured:
            client._ask_once(PreparedClipboardText("test", False), "test", allow_web_search=False)

        self.assertEqual(captured.exception.status_code, 429)
        self.assertEqual(captured.exception.retry_after_s, 2.0)
