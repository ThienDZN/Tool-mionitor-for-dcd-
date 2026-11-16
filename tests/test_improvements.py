from __future__ import annotations

from unittest import TestCase

from clip_overlay_ai.ai_client import (
    GatewayRequestError,
    RequestLimiter,
    _question_type_instruction,
    normalize_answer_output,
)
from clip_overlay_ai.app import AnswerBatch, _short_progress_note
from clip_overlay_ai.question_splitter import DetectedQuestion

CARDS = (
    "Ghép cặp hệ thống với chức năng:\n1. WIDS\n2. WIPS\n3. RADIUS\n"
    "A. Phát hiện và tự động chặn\nB. Phát hiện và cảnh báo\nC. Máy chủ xác thực AAA"
)


class MatchingCompactionTests(TestCase):
    def test_named_pairs_become_numbered(self) -> None:
        raw = "Đáp án đúng: WIDS → B. Phát hiện và cảnh báo; WIPS → A. Phát hiện và tự động chặn; RADIUS → C. Máy chủ xác thực AAA"
        self.assertEqual(normalize_answer_output(raw, CARDS), "Đáp án đúng: 1-B, 2-A, 3-C")

    def test_leading_numbers_are_used(self) -> None:
        raw = "Đáp án đúng: 3. RADIUS → C. x; 1. WIDS → B. y; 2. WIPS → A. z"
        self.assertEqual(normalize_answer_output(raw, CARDS), "Đáp án đúng: 1-B, 2-A, 3-C")

    def test_digit_in_card_name_is_not_a_number(self) -> None:
        cards = "Ghép cặp:\n1. WEP\n2. WPA2\n3. WPA3\nA. SAE\nB. AES-CCMP\nC. RC4"
        raw = "Đáp án đúng: WEP → C; WPA2 → B; WPA3 → A"
        self.assertEqual(normalize_answer_output(raw, cards), "Đáp án đúng: 1-C, 2-B, 3-A")

    def test_unknown_card_keeps_original_wording(self) -> None:
        raw = "Đáp án đúng: Foo → B; Bar → A"
        self.assertEqual(normalize_answer_output(raw, CARDS), "Đáp án đúng: Foo → B; Bar → A")

    def test_without_question_text_nothing_changes(self) -> None:
        self.assertEqual(normalize_answer_output("1 → A; 2 → C"), "Đáp án đúng: 1 → A; 2 → C")


class FillInPromptTests(TestCase):
    def test_asks_for_missing_part_only(self) -> None:
        self.assertIn("phần còn thiếu", _question_type_instruction("fill_in"))


class RequestLimiterTests(TestCase):
    def test_blocks_after_quota_then_releases(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        limiter = RequestLimiter(2, clock=lambda: now[0], sleep=sleep)
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(sleeps, [])
        limiter.acquire()  # third request must wait for the window to slide
        self.assertTrue(sleeps)
        self.assertGreaterEqual(now[0], 60.0)

    def test_penalty_after_429_delays_next_request(self) -> None:
        now = [0.0]
        limiter = RequestLimiter(0, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
        limiter.penalize(3.0)
        limiter.acquire()
        self.assertGreaterEqual(now[0], 3.0)

    def test_wait_beyond_deadline_fails_fast(self) -> None:
        now = [0.0]
        limiter = RequestLimiter(1, clock=lambda: now[0], sleep=lambda s: None)
        limiter.acquire()
        with self.assertRaises(GatewayRequestError):
            limiter.acquire(deadline=-1.0 + 0.0)  # already expired deadline

    def test_zero_means_unlimited(self) -> None:
        limiter = RequestLimiter(0, clock=lambda: 0.0, sleep=lambda s: self.fail("should not sleep"))
        for _ in range(500):
            limiter.acquire()


class ProgressClockTests(TestCase):
    def _batch(self) -> AnswerBatch:
        batch = AnswerBatch(started_at=100.0)
        batch.detected_questions = [DetectedQuestion(1, "Câu 1", "a"), DetectedQuestion(2, "Câu 2", "b")]
        return batch

    def test_default_text_is_unchanged(self) -> None:
        self.assertEqual(self._batch().progress_text(), "Câu 1: RUNNING\nCâu 2: RUNNING")

    def test_fast_questions_show_no_clock(self) -> None:
        self.assertEqual(self._batch().progress_text(now=102.0), "Câu 1: RUNNING\nCâu 2: RUNNING")

    def test_slow_question_shows_elapsed_and_note(self) -> None:
        batch = self._batch()
        batch.notes_by_index[1] = "thử lại 2/4"
        self.assertEqual(
            batch.progress_text(now=112.9),
            "Câu 1: RUNNING 12s\nCâu 2: RUNNING 12s (thử lại 2/4)",
        )

    def test_notes_from_client_messages(self) -> None:
        self.assertEqual(_short_progress_note("[RETRY] Attempt 1/4 failed; retrying."), "thử lại 2/4")
        self.assertEqual(_short_progress_note("[VERIFY] Re-checking the original image."), "kiểm tra lại ảnh")
        self.assertIsNone(_short_progress_note("[PREPARE] anything"))


class AnswerPerLineTests(TestCase):
    def test_unlabeled_parts_are_numbered_per_line(self) -> None:
        from clip_overlay_ai.app import _answer_per_line

        self.assertEqual(
            _answer_per_line("Đáp án đúng: C. 172.16.5.1; 1-B, 2-C, 3-A"),
            "1) C. 172.16.5.1\n2) 1-B, 2-C, 3-A",
        )

    def test_pairs_are_not_numbered(self) -> None:
        from clip_overlay_ai.app import _answer_per_line

        self.assertEqual(_answer_per_line("Đáp án đúng: WEP → C; WPA2 → B"), "WEP → C\nWPA2 → B")

    def test_single_answer_is_unchanged(self) -> None:
        from clip_overlay_ai.app import _answer_per_line

        self.assertEqual(_answer_per_line("Đáp án đúng: B. SYN, ACK"), "Đáp án đúng: B. SYN, ACK")

    def test_mixed_plain_and_pairs_are_not_numbered(self) -> None:
        from clip_overlay_ai.app import _answer_per_line

        self.assertEqual(
            _answer_per_line("Đáp án đúng: C. 172.16.5.1; 1 → B. Segment; 2 → C. Packet"),
            "C. 172.16.5.1\n1 → B. Segment\n2 → C. Packet",
        )


class MultiQuestionHintTests(TestCase):
    def test_counts_option_blocks(self) -> None:
        from clip_overlay_ai.ai_client import count_option_blocks

        text = "q1\nA. x\nB. y\nq2\nA.SYN\nB. z\nq3\nA. 1\nB. 2"
        self.assertEqual(count_option_blocks(text), 3)
        self.assertEqual(count_option_blocks("q\nA. x\nB. y"), 1)
        self.assertEqual(count_option_blocks(""), 0)

    def test_prompt_states_the_count(self) -> None:
        from clip_overlay_ai.ai_client import build_user_message
        from clip_overlay_ai.safety import PreparedClipboardText

        text = "q1\nA. x\nB. y\nq2\nA. x\nB. y"
        self.assertIn("có 2 câu hỏi", build_user_message(PreparedClipboardText(text=text, truncated=False)))
        single = build_user_message(PreparedClipboardText(text="q\nA. x\nB. y", truncated=False))
        self.assertNotIn("câu hỏi (mỗi câu", single)
