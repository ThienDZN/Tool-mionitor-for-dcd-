"""Decide whether new clipboard content repeats something just answered.

With auto-send for both screenshots and copied text, a common sequence is:
take a screenshot of a question (answered from the image), then copy the same
question's text. Byte fingerprints cannot catch that, because the image and
the text never share bytes. This module compares the copied text against the
question texts recognised recently (including OCR text from screenshots).
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

_TOKEN_PATTERN = re.compile(r"\w+")
# Below this many distinct tokens a text is too short to compare reliably
# ("A", "True", "2023"), so it is never treated as a repeat.
_MIN_TOKENS = 4


def _fold(text: str) -> str:
    """Lowercase and drop Vietnamese diacritics so OCR slips still match."""
    decomposed = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def tokens(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_PATTERN.findall(_fold(text)))


@dataclass(slots=True)
class RecentQuestions:
    """Question texts answered recently, forgotten after ``window_s`` seconds.

    The window is short and the threshold high on purpose: skipping a genuinely
    new question (a quiz series often repeats most words of a stem) is worse
    than answering one question twice.
    """

    window_s: float = 45.0
    threshold: float = 0.9
    clock: Callable[[], float] = time.monotonic
    _entries: list[tuple[float, frozenset[str], object]] = field(default_factory=list)

    def remember(self, texts: Iterable[str], key: object = None) -> None:
        """Record one batch: each question, plus the batch as a whole.

        The whole-batch entry lets a copy spanning two questions of one
        screenshot match, without mixing words from unrelated batches.
        """
        now = self.clock()
        self._prune(now)
        batch = [item for item in (tokens(text) for text in texts) if item]
        for item in batch:
            self._entries.append((now, item, key))
        if len(batch) > 1:
            self._entries.append((now, frozenset().union(*batch), key))

    def forget(self, key: object) -> None:
        """Drop a batch the user cancelled, so copying it again is sent."""
        self._entries = [entry for entry in self._entries if entry[2] != key]

    def is_repeat(self, text: str) -> bool:
        new_tokens = tokens(text)
        if len(new_tokens) < _MIN_TOKENS:
            return False
        self._prune(self.clock())
        return any(
            len(new_tokens & recent) / len(new_tokens) >= self.threshold
            for _at, recent, _key in self._entries
        )

    def clear(self) -> None:
        self._entries.clear()

    def _prune(self, now: float) -> None:
        self._entries = [entry for entry in self._entries if now - entry[0] < self.window_s]
