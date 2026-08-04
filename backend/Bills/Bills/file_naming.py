"""Shared filesystem/archive naming helpers: making a name safe to write, and
making sure it doesn't collide with a name that's already been used."""
from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')


def safe_filename(name: str | None, fallback: str = "file") -> str:
    """
    Strips path separators and any character the filesystem/zip format can't
    store, collapses them to a single "_", and drops a trailing ".". Falls back
    to `fallback` if nothing usable is left (e.g. name was empty or all unsafe
    characters).
    """
    raw = (name or "").strip()
    if raw:
        raw = raw.replace("\\", "/").split("/")[-1]
    else:
        raw = fallback

    safe = _UNSAFE_CHARS_PATTERN.sub("_", raw).strip().strip(".")
    return safe or fallback


def make_unique_path(path: Path) -> Path:
    """Appends _2, _3, ... to the filename until it doesn't collide with an existing file on disk."""
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
    Same _2, _3, ... collision avoidance as make_unique_path, but against an
    in-memory tally (used_counts, mutated in place) instead of the filesystem —
    for building a zip archive, where there's no on-disk file to check.
    """
    next_index = used_counts.get(base_name, 0) + 1
    used_counts[base_name] = next_index

    if next_index == 1:
        return base_name

    stem = Path(base_name).stem
    suffix = Path(base_name).suffix
    return f"{stem}_{next_index}{suffix}"
