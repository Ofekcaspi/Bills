"""Generic (non-Hebrew-specific) text cleanup shared across extraction/matching code."""
from __future__ import annotations

import re

CONTROL_MARKS_PATTERN = re.compile(r"[‎‏‪-‮⁦-⁩﻿]")


def clean_text(text: str) -> str:
    """Strips invisible direction-control marks and normalizes non-breaking spaces."""
    if not text:
        return ""
    cleaned = CONTROL_MARKS_PATTERN.sub("", text)
    cleaned = cleaned.replace(" ", " ")
    return cleaned
