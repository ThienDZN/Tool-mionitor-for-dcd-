from __future__ import annotations

from clip_overlay_ai.clipboard_gate import RecentQuestions


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


OCR_QUESTION = (
    "Câu 3: Khoa chinh (primary key) trong SQL dung de lam gi?\n"
    "A. Dinh danh duy nhat moi dong  B. Lien ket bang  C. Tang toc  D. Sap xep"
)
COPIED_QUESTION = (
    "Câu 3: Khóa chính (primary key) trong SQL dùng để làm gì?\n"
    "A. Định danh duy nhất mỗi dòng B. Liên kết bảng C. Tăng tốc D. Sắp xếp"
)


def make_gate() -> tuple[RecentQuestions, FakeClock]:
    clock = FakeClock()
    return RecentQuestions(clock=clock), clock


def test_text_copied_after_screenshot_of_same_question_is_a_repeat() -> None:
    gate, _ = make_gate()
    gate.remember([OCR_QUESTION])

    assert gate.is_repeat(COPIED_QUESTION)


def test_copying_one_question_out_of_a_multi_question_screenshot_is_a_repeat() -> None:
    gate, _ = make_gate()
    gate.remember([OCR_QUESTION, "Câu 4: Khóa ngoại dùng để làm gì? A. X B. Y"])

    assert gate.is_repeat(COPIED_QUESTION)


def test_next_question_in_a_series_is_not_a_repeat() -> None:
    gate, _ = make_gate()
    gate.remember([COPIED_QUESTION])

    next_question = (
        "Câu 4: Khóa ngoại (foreign key) trong SQL dùng để làm gì?\n"
        "A. Tham chiếu tới bảng khác B. Xóa dữ liệu C. Tạo chỉ mục D. Phân quyền"
    )
    assert not gate.is_repeat(next_question)


def test_words_from_separate_batches_are_not_combined() -> None:
    gate, _ = make_gate()
    gate.remember(["alpha beta gamma delta"])
    gate.remember(["epsilon zeta eta theta"])

    assert not gate.is_repeat("alpha beta epsilon zeta")


def test_repeat_window_expires() -> None:
    gate, clock = make_gate()
    gate.remember([OCR_QUESTION])
    clock.now += gate.window_s + 1

    assert not gate.is_repeat(COPIED_QUESTION)


def test_short_text_is_never_treated_as_repeat() -> None:
    gate, _ = make_gate()
    gate.remember(["Đáp án A đúng"])

    assert not gate.is_repeat("A đúng")


def test_forgetting_a_cancelled_batch_lets_it_be_sent_again() -> None:
    gate, _ = make_gate()
    gate.remember(["Câu 1: một câu khác hoàn toàn về mạng máy tính"], key=1)
    gate.remember([OCR_QUESTION], key=2)
    gate.forget(2)

    assert not gate.is_repeat(COPIED_QUESTION)
    assert gate.is_repeat("Câu 1: một câu khác hoàn toàn về mạng máy tính")
