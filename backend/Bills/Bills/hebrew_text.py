"""
this module normalizes hebrew text,
to make sure that txt from different sources TXT/PDF
is uniform after this text, (instead of reverse)
"""
from __future__ import annotations

import re

HEBREW_WORD_PATTERN = re.compile(r"[֐-׿]+")
HAS_HEBREW_PATTERN = re.compile(r"[֐-׿]")
HEBREW_ACRONYM_WORD_PATTERN = re.compile(r"[א-ת]+(?:[״׳'][א-ת]+)?")


def fix_hebrew_word_order(text: str) -> str:
    """
    Flips each run of Hebrew words back to normal reading order, character order
    and word order both. PDF extractors hand back Hebrew visually reversed, so
    without this, labels like "לתשלום" never match their regex patterns.
    """
    fixed_lines: list[str] = []
    for line in text.splitlines():
        words = line.split()
        if not words:
            fixed_lines.append("")
            continue

        output_words: list[str] = []
        i = 0
        while i < len(words):
            if HAS_HEBREW_PATTERN.search(words[i]):
                hebrew_run: list[str] = []
                while i < len(words) and HAS_HEBREW_PATTERN.search(words[i]):
                    fixed_token = HEBREW_WORD_PATTERN.sub(
                        lambda m: m.group(0)[::-1],
                        words[i],
                    )
                    hebrew_run.append(fixed_token)
                    i += 1
                output_words.extend(reversed(hebrew_run))
                continue

            output_words.append(words[i])
            i += 1

        fixed_lines.append(" ".join(output_words))

    return "\n".join(fixed_lines)


def reverse_hebrew_words(text: str | None) -> str:
    """
    Reverses the characters within each Hebrew word, leaving word order and any
    English/numbers/punctuation untouched. Used to fix Hebrew subject/sender
    text that arrives character-reversed but with word order intact.
    """
    if not text:
        return ""

    return HEBREW_ACRONYM_WORD_PATTERN.sub(lambda m: m.group(0)[::-1], text)


def reverse_words_char_by_char(text: str) -> list[str]:
    """
    Reverses every word's characters, regardless of script — no Hebrew check.
    This exists because the .txt training samples for the bill/receipt
    classifier were saved with every word pre-reversed; it undoes that encoding,
    not general-purpose Hebrew handling.
    """
    return [w[::-1] for w in text.split()]
