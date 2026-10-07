"""Conservative recognition of separately numbered quiz questions.

The clipboard often contains an option list whose items are also numbered.  A
false split is worse than a missed opportunity to parallelise, so this module
only returns multiple questions when the headings make that structure clear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DetectedQuestion:
    """One question recognised in a clipboard payload."""

    number: int | None
    label: str | None
    text: str


_OCR_DIGIT_TRANSLATION = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})
_HEADING_NUMBER_PATTERN = r"[0-9OolI|]{1,4}"
_EXPLICIT_HEADING_PATTERN = re.compile(
    rf"""(?im)^[ \t]*(?:
        (?:câu|cau)(?:[ \t]+(?:hỏi|hoi))?(?:[ \t]+(?:số|so))?[ \t]*
        |question(?:[ \t]*(?:no\.?|number|\#))?[ \t]*
        |q[ \t.\#]*
    )(?P<number>{_HEADING_NUMBER_PATTERN})(?=$|[ \t:.)\-–—])[ \t]*(?:[:.)\-–—][ \t]*)?""",
    re.VERBOSE,
)
# Some web pages flatten copied text into one paragraph.  Unlike the regular
# line-heading pattern, this fallback requires a colon after every heading and
# a question cue in every section before it is allowed to split anything.
_INLINE_EXPLICIT_HEADING_PATTERN = re.compile(
    rf"""(?i)(?<!\w)(?:
        (?:câu|cau)(?:[ \t]+(?:hỏi|hoi))?(?:[ \t]+(?:số|so))?[ \t]*
        |question(?:[ \t]*(?:no\.?|number|\#))?[ \t]*
        |q[ \t.\#]*
    )(?P<number>{_HEADING_NUMBER_PATTERN})(?=$|[ \t:.)\-–—])[ \t]*:[ \t]*""",
    re.VERBOSE,
)
_BARE_HEADING_PATTERN = re.compile(r"(?im)^[ \t]*(?P<number>\d{1,4})[.):][ \t]+")
_OPTION_AFTER_BARE_HEADING_PATTERN = re.compile(r"(?i)^[ \t]*[a-h][.)][ \t]+")
_NAMED_HEADING_WORD_PATTERN = re.compile(r"(?i)\b(?:câu|cau|question|q)\b")
_QUESTION_CUE_PATTERN = re.compile(
    r"(?i)(\?|\b(?:what|which|when|where|who|why|how|select|choose|complete|fill)\b|"
    r"(?:hãy|hay|chọn|chon|điền|dien|tính|tìm|tim|giải|giai|viết|viet|nêu|neu|"
    r"xác định|xac dinh|cho biết|phát biểu|phat bieu|chứng minh|chung minh|"
    r"so sánh|so sanh)\b)"
)
_OPTION_LINE_PATTERN = re.compile(r"(?im)^[ \t]*[a-h][.)][ \t]+\S+")


def split_numbered_questions(text: str) -> list[DetectedQuestion]:
    """Split only unambiguous numbered question headings.

    Named Vietnamese/English headings (``Câu 2``, ``Câu số 2``, ``Question
    2``, ``Q2``) are accepted in an increasing sequence, or as one clear
    question after an unambiguous document title. OCR variants such as
    ``Câu31`` and ``Câu 3l`` are repaired only inside a named heading. Bare
    ``1.`` / ``2.`` headings are intentionally stricter: non-consecutive
    labels need a clear question cue so a numbered answer choice is not
    mistaken for a question.
    """
    normalized = text.strip()
    if not normalized:
        return [_whole_question("")]

    explicit_matches = list(_EXPLICIT_HEADING_PATTERN.finditer(normalized))
    explicit_questions: list[DetectedQuestion] = []
    if explicit_matches:
        explicit_questions = _questions_from_matches(normalized, explicit_matches)
        if _has_distinct_increasing_numbers(explicit_questions):
            return explicit_questions

    inline_matches = list(_INLINE_EXPLICIT_HEADING_PATTERN.finditer(normalized))
    if inline_matches:
        questions = _questions_from_matches(normalized, inline_matches)
        if _is_safe_inline_question_sequence(questions):
            return questions

    if _is_safe_single_explicit_question(normalized, explicit_matches, explicit_questions):
        return explicit_questions

    bare_matches = list(_BARE_HEADING_PATTERN.finditer(normalized))
    questions = _questions_from_matches(normalized, bare_matches)
    if _is_safe_bare_question_sequence(questions):
        return questions
    return [_whole_question(normalized)]


def _whole_question(text: str) -> DetectedQuestion:
    return DetectedQuestion(number=None, label=None, text=text)


def _questions_from_matches(text: str, matches: list[re.Match[str]]) -> list[DetectedQuestion]:
    questions: list[DetectedQuestion] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        question_text = text[match.end() : end].strip()
        number = _parse_heading_number(match.group("number"))
        if question_text:
            questions.append(DetectedQuestion(number=number, label=f"Câu {number}", text=question_text))
    return questions


def _parse_heading_number(value: str) -> int:
    """Repair only OCR lookalikes that appear inside a named question label."""
    return int(value.translate(_OCR_DIGIT_TRANSLATION))


def _is_safe_single_explicit_question(
    text: str,
    matches: list[re.Match[str]],
    questions: list[DetectedQuestion],
) -> bool:
    """Keep one named heading without mistaking a nearby phrase for a label."""
    if len(matches) != 1 or len(questions) != 1 or questions[0].number is None:
        return False

    # A title before the question is harmless. A preceding phrase that itself
    # uses a heading word (for example ``Câu lỗi này...``) is ambiguous, so
    # leave the complete payload intact rather than assigning a false label.
    prefix = text[: matches[0].start()].strip()
    return not _NAMED_HEADING_WORD_PATTERN.search(prefix)


def _has_distinct_increasing_numbers(questions: list[DetectedQuestion]) -> bool:
    if len(questions) < 2:
        return False
    numbers = [question.number for question in questions]
    return all(
        current is not None and previous is not None and current > previous
        for previous, current in zip(numbers, numbers[1:])
    )


def _is_safe_bare_question_sequence(questions: list[DetectedQuestion]) -> bool:
    if len(questions) < 2 or not _has_distinct_increasing_numbers(questions):
        return False

    numbers = [question.number for question in questions]
    if all(_has_question_cue(question.text) for question in questions):
        return True

    if any(current != previous + 1 for previous, current in zip(numbers, numbers[1:])):
        return False

    return all(_looks_like_bare_question(question.text) for question in questions)


def _is_safe_inline_question_sequence(questions: list[DetectedQuestion]) -> bool:
    return _has_distinct_increasing_numbers(questions) and all(
        _has_question_cue(question.text) for question in questions
    )


def _looks_like_bare_question(text: str) -> bool:
    first_line = text.splitlines()[0] if text.splitlines() else text
    if _OPTION_AFTER_BARE_HEADING_PATTERN.match(first_line):
        return False
    if _has_question_cue(text):
        return True
    # A section with conventional A-D choices is sufficiently distinct from a
    # plain numbered list, even when the question writer omitted a question
    # mark.  Requiring two choices avoids treating one sub-item as a question.
    return len(_OPTION_LINE_PATTERN.findall(text)) >= 2


def _has_question_cue(text: str) -> bool:
    return bool(_QUESTION_CUE_PATTERN.search(text))
