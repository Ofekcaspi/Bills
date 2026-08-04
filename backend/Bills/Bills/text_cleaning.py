"""Generic (non-Hebrew-specific) text cleanup shared across extraction/matching code."""
from __future__ import annotations

import re

# Bidi/embedding/isolate direction-control marks plus BOM. These are invisible
# but interleave with real characters in text copied from Gmail or PDFs, and
# will silently break regex matches (e.g. a label + amount that "look" adjacent
# but have a direction-control mark sitting between them) if left in.
CONTROL_MARKS_PATTERN = re.compile(r"[‎‏‪-‮⁦-⁩﻿]")


def clean_text(text: str) -> str:
    """Strips invisible direction-control marks and normalizes non-breaking spaces."""
    if not text:
        return ""
    cleaned = CONTROL_MARKS_PATTERN.sub("", text)
    cleaned = cleaned.replace(" ", " ")
    return cleaned
