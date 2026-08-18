"""Helpers for cleaning up file names and making sure two files don't
 end up with the same name."""
from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')


def safe_filename(name: str | None, fallback: str = "file") -> str:
    """
    Cleans up a name so it's safe to save as a file: swaps out characters
    that aren't allowed in file names for "_", and uses a fallback name if
    nothing usable is left (e.g. the name was empty or was all bad characters).
    """
    raw = (name or "").strip()
    if raw:
        raw = raw.replace("\\", "/").split("/")[-1]
    else:
        raw = fallback

    safe = _UNSAFE_CHARS_PATTERN.sub("_", raw).strip().strip(".")
    return safe or fallback


def make_unique_path(path: Path) -> Path:
    """If a file with this name already exists, keeps adding _2, _3, and so on until the name is free."""
    if not path.exists():
        return path

    stem = path.stem
    suf = path.suffix
    i = 2
    while True:
        candidate = path.parent / f"{stem}_{i}{suf}"
        if not candidate.exists():
            return candidate
        i += 1


def dedupe_filename(base_name: str, used_counts: dict[str, int]) -> str:
    """
    Does the same _2, _3, ... renaming as make_unique_path, but for names that
    aren't real files yet — like when building a zip file — so it just keeps
    a running count instead of checking the disk.
    """
    next_index = used_counts.get(base_name, 0) + 1
    used_counts[base_name] = next_index

    if next_index == 1:
        return base_name

    stem = Path(base_name).stem
    suffix = Path(base_name).suffix
    return f"{stem}_{next_index}{suffix}"
