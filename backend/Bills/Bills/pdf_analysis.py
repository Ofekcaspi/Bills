from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Iterable

import pdfplumber

from .hebrew_text import fix_hebrew_word_order
from .text_cleaning import clean_text

logger = logging.getLogger(__name__)

DATE_PATTERN_TEXT = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}"
DATE_PATTERN = re.compile(DATE_PATTERN_TEXT)

# Number forms accepted as money candidates:
#   12
#   12.5
#   12.50
#   1,234.56
#   1.234,56
#   1 234,56
#   (123.45)
# We still validate context before accepting them as amounts.
# Important: do not allow newline as a thousands separator, otherwise tokens from
# adjacent lines can merge (e.g. "088\\n663.50"), breaking amount parsing.
AMOUNT_NUMBER_TEXT = r"\(?-?\d{1,3}(?:[,\.\u00a0 ]\d{3})+(?:[,.]\d{1,2})?\)?|\(?-?\d+(?:[,.]\d{1,2})?\)?"
AMOUNT_NUMBER_PATTERN = re.compile(AMOUNT_NUMBER_TEXT)

HEB_LETASHLUM = "\u05DC\u05EA\u05E9\u05DC\u05D5\u05DD"  # לתשלום
HEB_SAHAK = "\u05E1\u05D4\"\u05DB"  # סה"כ
HEB_SAHAK_NOQUOTE = "\u05E1\u05D4\u05DB"  # סהכ
HEB_KSAH = "\u05DB\"\u05E1\u05D4"  # כ"סה
HEB_SAK_HAKOL = "\u05E1\u05DA \u05D4\u05DB\u05DC"  # סך הכל
HEB_KOLEL = "\u05DB\u05D5\u05DC\u05DC"  # כולל
HEB_SUM_PAID = "\u05E1\u05DB\u05D5\u05DD \u05E9\u05E9\u05D5\u05DC\u05DD"  # סכום ששולם
HEB_MECHIR = "\u05DE\u05D7\u05D9\u05E8"  # מחיר
HEB_YITRA = "\u05D9\u05EA\u05E8\u05D4"  # יתרה
HEB_LCHIYUV = "\u05DC\u05D7\u05D9\u05D5\u05D1"  # לחיוב
HEB_TASHLUM = "\u05EA\u05E9\u05DC\u05D5\u05DD"  # תשלום
HEB_HASHBONIT = "\u05D7\u05E9\u05D1\u05D5\u05E0\u05D9\u05EA"  # חשבונית
HEB_KABALA = "\u05E7\u05D1\u05DC\u05D4"  # קבלה
HEB_KOTSH = "\u05E7\u05D5\u05D8\"\u05E9"  # קוט"ש
HEB_KOTSH_NOQUOTE = "\u05E7\u05D5\u05D8\u05E9"  # קוטש
HEB_YAMIM = "\u05D9\u05DE\u05D9\u05DD"  # ימים
HEB_SHAOT = "\u05E9\u05E2\u05D5\u05EA"  # שעות

POSITIVE_STRONG_LABEL_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("לתשלום", re.compile(r"\u05DC\u05EA\u05E9\u05DC\u05D5[\u05DD\u05E1]")),
    (
        'סה"כ לתשלום',
        re.compile(
            r"(?:\u05E1\u05D4[\"'`\u05F3\u05F4]?\u05DB|\u05DB[\"'`\u05F3\u05F4]?\u05E1\u05D4|\u05E1\u05DA\s*\u05D4\u05DB\u05DC)\s*\u05DC\u05EA\u05E9\u05DC\u05D5[\u05DD\u05E1]"
        ),
    ),
    ("סכום לתשלום", re.compile(r"\u05E1\u05DB\u05D5\u05DD\s*\u05DC\u05EA\u05E9\u05DC\u05D5[\u05DD\u05E1]")),
    ("יתרה לתשלום", re.compile(r"\u05D9\u05EA\u05E8\u05D4\s*\u05DC\u05EA\u05E9\u05DC\u05D5[\u05DD\u05E1]")),
    ("amount due", re.compile(r"\bamount\s*due\b", re.IGNORECASE)),
    ("total due", re.compile(r"\btotal\s*due\b", re.IGNORECASE)),
    ("balance due", re.compile(r"\bbalance\s*due\b", re.IGNORECASE)),
    ("payment due", re.compile(r"\bpayment\s*due\b", re.IGNORECASE)),
    (
        "החשבון ישולם",
        re.compile(
            r"(?:\u05d4)?\u05d7\u05e9\u05d1\u05d5\u05df(?:\s*\u05d6\u05d4)?\s*\u05d9\u05e9\u05d5\u05dc\u05dd",
            re.IGNORECASE,
        ),
    ),
    (
        "שולם סכום",
        re.compile(
            r"\u05E9\u05D5\u05DC\u05DD\s*\u05E1\u05DB\u05D5\u05DD(?:\s*\u05E9\u05DC)?"
        ),
    ),
    ("grand total", re.compile(r"\bgrand\s*total\b", re.IGNORECASE)),
    ("to pay", re.compile(r"\bto\s*pay\b", re.IGNORECASE)),
)

POSITIVE_MEDIUM_LABEL_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (HEB_SAHAK, re.compile(r"\u05E1\u05D4[\"'`\u05F3\u05F4]?\u05DB")),
    (HEB_KSAH, re.compile(r"\u05DB[\"'`\u05F3\u05F4]?\u05E1\u05D4")),
    (HEB_SAK_HAKOL, re.compile(r"\u05E1\u05DA\s*\u05D4\u05DB\u05DC")),
    ("סכום כולל", re.compile(r"\u05E1\u05DB\u05D5\u05DD\s*\u05DB\u05D5\u05DC\u05DC")),
    (HEB_SUM_PAID, re.compile(r"\u05E1\u05DB\u05D5\u05DD\s*\u05E9\u05E9\u05D5\u05DC\u05DD")),
    ("total paid", re.compile(r"\btotal\s*paid\b", re.IGNORECASE)),
    ("amount paid", re.compile(r"\bamount\s*paid\b", re.IGNORECASE)),
    ("paid amount", re.compile(r"\bpaid\s*amount\b", re.IGNORECASE)),
    ("total", re.compile(r"(?<!sub)\btotal\b", re.IGNORECASE)),
)

NEGATIVE_AMOUNT_LABEL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bsubtotal\b", re.IGNORECASE),
    re.compile(r"\bsub\s*total\b", re.IGNORECASE),
    re.compile(r"\bvat\b", re.IGNORECASE),
    re.compile(r"\btax\b", re.IGNORECASE),
    re.compile(r"\bdiscount\b", re.IGNORECASE),
    re.compile(r"\btip\b", re.IGNORECASE),
    re.compile(r"\bshipping\b", re.IGNORECASE),
    re.compile(r"\bdeposit\b", re.IGNORECASE),
    re.compile(r"\bchange\b", re.IGNORECASE),
    re.compile(r"\bcredit\b", re.IGNORECASE),
    re.compile(r"\bbefore\s*vat\b", re.IGNORECASE),
    re.compile(r"\u05DC\u05E4\u05E0\u05D9\s*\u05DE\u05E2[\"'\u05F3\u05F4]?\u05DE"),
    re.compile(r"\u05DE\u05E2[\"'\u05F3\u05F4]?\u05DE"),
    re.compile(r"\u05D4\u05E0\u05D7\u05D4"),  # הנחה
    re.compile(r"\u05DE\u05E9\u05DC\u05D5\u05D7"),  # משלוח
    re.compile(r"\u05D6\u05D9\u05DB\u05D5\u05D9"),  # זיכוי
)

NOISE_KEYWORDS = (
    HEB_KOTSH,
    HEB_KOTSH_NOQUOTE,
    HEB_YAMIM,
    HEB_SHAOT,
    "kwh",
    "kva",
    " kw",
    "kw ",
    "meter",
    "reading",
    "account number",
    "invoice number",
    "order number",
    "customer number",
    "order id",
    "transaction id",
    "reference",
    "ref no",
    "item no",
    "sku",
    "מספר",
    "מונה",
    "קריאה",
)

IDENTIFIER_KEYWORDS = (
    "order",
    "order number",
    "order id",
    "invoice number",
    "customer number",
    "reference",
    "transaction id",
    "approval code",
    "sku",
    "item no",
    "item #",
    "מספר",
    "הזמנה",
    "מקט",
    "מק\"ט",
    "אסמכתא",
)

# Currency can appear before or after the amount.
CURRENCY_PATTERNS = {
    "ILS": re.compile(
        r"(₪|\bnis\b|\bils\b|\bils\.\b|\bshakel\b|\bshekel\b|\bshekels\b|\u05E9\"?\u05D7|\u05D7\"?\u05E9|\u05E9\u05D7|\u05D7\u05E9)",
        re.IGNORECASE,
    ),
    "USD": re.compile(r"(\$|\busd\b|\bus\$\b|\bdollar\b|\bdollars\b)", re.IGNORECASE),
    "EUR": re.compile(r"(€|\beur\b|\beuro\b|\beuros\b)", re.IGNORECASE),
    "GBP": re.compile(r"(£|\bgbp\b|\bpound\b|\bpounds\b)", re.IGNORECASE),
}

CURRENCY_TOKEN_PATTERN = re.compile(
    r"₪|\$|€|£|\b(?:nis|ils|usd|eur|gbp|shekel|shekels|dollar|dollars|euro|euros|pound|pounds)\b|\u05E9\"?\u05D7|\u05D7\"?\u05E9|\u05E9\u05D7|\u05D7\u05E9",
    re.IGNORECASE,
)

DUE_LABEL_PATTERN = (
    "(?:"
    "\u05DC\u05EA\u05E9\u05DC\u05D5\u05DD\\s*\u05E2\u05D3"  # לתשלום עד
    "|"
    "\u05EA\u05E9\u05DC\u05D5\u05DD\\s*\u05E2\u05D3"  # תשלום עד
    "|"
    "\u05E2\u05D3\\s*\u05DC\u05EA\u05E9\u05DC\u05D5\u05DD"  # עד לתשלום
    "|"
    "\u05DE\u05D5\u05E2\u05D3\\s*\u05EA\u05E9\u05DC\u05D5\u05DD"  # מועד תשלום
    "|"
    "\u05EA\u05D0\u05E8\u05D9\u05DA\\s*\u05D9\u05E2\u05D3"  # תאריך יעד
    "|due\\s*date"
    "|payment\\s*due"
    "|pay\\s*by"
    ")"
)


def _normalize_text_for_parsing(text: str) -> str:
    normalized = fix_hebrew_word_order(text)
    return clean_text(normalized)


def _parse_amount_number(token: str) -> float | None:
    s = token.strip()
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")

    if s.startswith("-"):
        negative = True
        s = s[1:]

    s = s.replace(" ", "")
    if not s:
        return None

    # 1,234.56 or 1.234,56
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) in (1, 2):
            s = "".join(parts[:-1]) + "." + parts[-1]
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1:
        # 1.234.567 -> thousands separators
        s = s.replace(".", "")

    try:
        value = float(s)
    except ValueError:
        return None

    return -value if negative else value


def _detect_currency(text: str) -> str | None:
    for currency, pattern in CURRENCY_PATTERNS.items():
        if pattern.search(text):
            return currency
    return None


def _find_pattern_positions(pattern: re.Pattern, text: str) -> list[tuple[int, int]]:
    return [m.span() for m in pattern.finditer(text)]


def _inside_any_span(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start >= span_start and end <= span_end for span_start, span_end in spans)


def _looks_like_year(value: float, raw: str) -> bool:
    return "." not in raw and "," not in raw and 1900 <= value <= 2100


def _looks_like_identifier(context: str) -> bool:
    ctx = context.lower()
    return any(keyword in ctx for keyword in NOISE_KEYWORDS)


def _normalize_label_line(line: str) -> str:
    normalized = clean_text(line).lower()
    normalized = normalized.replace("\u05F4", '"').replace("\u05F3", "'").replace("`", "'")

    # Common OCR confusions for English total labels.
    replacements = {
        "totai": "total",
        "am0unt": "amount",
        "duee": "due",
        "te pay": "to pay",
    }
    for wrong, fixed in replacements.items():
        normalized = normalized.replace(wrong, fixed)

    return normalized


def _best_positive_label_for_line(line: str) -> tuple[int, str | None]:
    best_score = 0
    best_label: str | None = None

    for label, pattern in POSITIVE_STRONG_LABEL_PATTERNS:
        if pattern.search(line):
            return 100, label

    for label, pattern in POSITIVE_MEDIUM_LABEL_PATTERNS:
        if pattern.search(line):
            if 60 > best_score:
                best_score = 60
                best_label = label

    return best_score, best_label


def _line_has_negative_amount_context(line: str) -> bool:
    return any(pattern.search(line) for pattern in NEGATIVE_AMOUNT_LABEL_PATTERNS)


def _label_matches_for_line(line: str) -> list[dict[str, int | str]]:
    matches: list[dict[str, int | str]] = []

    for label, pattern in POSITIVE_STRONG_LABEL_PATTERNS:
        for m in pattern.finditer(line):
            matches.append({"label": label, "score": 100, "start": m.start(), "end": m.end()})

    for label, pattern in POSITIVE_MEDIUM_LABEL_PATTERNS:
        for m in pattern.finditer(line):
            matches.append({"label": label, "score": 60, "start": m.start(), "end": m.end()})

    return matches


# Gap in characters between two spans on the same line; 0 if they overlap.
# Used to rank how close a number is to a "total"-style label — closer wins.
def _span_distance(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _same_line_proximity_score(distance: int) -> int:
    if distance <= 40:
        return 30
    if distance <= 80:
        return 20
    if distance <= 140:
        return 10
    return 0


def _is_plain_large_integer(raw: str, value: float) -> bool:
    s = raw.strip().strip("()")
    if s.startswith("-"):
        s = s[1:]
    if not s.isdigit():
        return False
    return value >= 1000 and value.is_integer()


def _contains_identifier_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in IDENTIFIER_KEYWORDS)


def _extract_surrounding_token(text: str, start: int, end: int) -> str:
    left = start
    right = end
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    while right < len(text) and not text[right].isspace():
        right += 1
    return text[left:right]


# True when the number is stuck to letters/slashes (order #, tracking code, URL)
# rather than standing alone — those shouldn't be picked up as a money amount.
def _is_number_id_tag(text: str, start: int, end: int) -> bool:
    token = _extract_surrounding_token(text, start, end)
    token_lower = token.lower()

    # Valid compact currency-prefix token examples: usd120, nis99
    if token_lower.startswith(("usd", "eur", "gbp", "ils", "nis", "$", "€", "£", "₪")):
        return False

    has_letter = any(ch.isalpha() for ch in token)
    has_digit = any(ch.isdigit() for ch in token)

    if "http://" in token_lower or "https://" in token_lower or "www." in token_lower:
        return True

    if "/" in token or "@" in token:
        return True

    return has_letter and has_digit and len(token) >= 6


def _split_lines_with_offsets(text: str) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        start = offset
        end = start + len(line)
        rows.append((line, start, end))
        offset += len(raw_line)

    if not rows:
        rows.append(("", 0, len(text)))

    return rows


def _line_index_for_position(line_rows: list[tuple[str, int, int]], position: int) -> int:
    for idx, (_, start, end) in enumerate(line_rows):
        if start <= position <= end:
            return idx
    return max(0, len(line_rows) - 1)


def _nearby_indexes(index: int, total: int) -> Iterable[int]:
    for i in (index - 1, index, index + 1):
        if 0 <= i < total:
            yield i


def _score_candidate(
        match: re.Match,
        text: str,
        *,
        date_spans: list[tuple[int, int]],
        line_rows: list[tuple[str, int, int]],
        normalized_lines: list[str],
        line_label_scores: list[tuple[int, str | None]],
        line_label_matches: list[list[dict[str, int | str]]],
        total_lines: int,
) -> dict | None:
    """Scores one AMOUNT_NUMBER_PATTERN match as a money candidate, or returns None to reject it."""
    raw = match.group(0)
    start, end = match.span()

    if _inside_any_span(start, end, date_spans):
        return None

    value = _parse_amount_number(raw)
    if value is None:
        return None

    if value > 200_000:
        return None

    if _looks_like_year(value, raw):
        return None

    # Avoid fragments in dates like 10/05/2026 even if the regex saw just "10".
    before = text[max(0, start - 1):start]
    after = text[end:end + 1]
    if before in {"/", "-"} or after in {"/", "-"}:
        return None
    if _is_number_id_tag(text, start, end):
        return None

    line_index = _line_index_for_position(line_rows, start)
    _, line_start, _ = line_rows[line_index]
    candidate_start_in_line = start - line_start
    candidate_end_in_line = end - line_start
    same_line_matches = line_label_matches[line_index]
    prev_line_score, prev_line_label = line_label_scores[line_index - 1] if line_index > 0 else (0, None)
    next_line_score, next_line_label = (
        line_label_scores[line_index + 1] if line_index + 1 < total_lines else (0, None)
    )

    label_score = 0
    matched_label: str | None = None
    proximity_score = 0

    best_same_line_rank: tuple[int, int, int] | None = None
    for match_info in same_line_matches:
        match_start = int(match_info["start"])
        match_end = int(match_info["end"])
        match_score = int(match_info["score"])
        distance = _span_distance(candidate_start_in_line, candidate_end_in_line, match_start, match_end)
        match_proximity = _same_line_proximity_score(distance)
        if match_proximity <= 0:
            continue

        # Prefer stronger label and closer distance.
        rank = (match_score, match_proximity, -distance)
        if best_same_line_rank is None or rank > best_same_line_rank:
            best_same_line_rank = rank
            label_score = match_score
            proximity_score = match_proximity
            matched_label = str(match_info["label"])

    if best_same_line_rank is not None:
        pass
    elif prev_line_score > 0:
        label_score = prev_line_score
        matched_label = prev_line_label
        proximity_score = 20
    elif next_line_score > 0:
        label_score = next_line_score
        matched_label = next_line_label
        proximity_score = 10
    else:
        # Candidate is too far from a total label.
        return None

    context = text[max(0, start - 80): min(len(text), end + 80)]
    tight_context = text[max(0, start - 15): min(len(text), end + 15)]

    if "%" in tight_context:
        return None

    if _is_plain_large_integer(raw, value):
        identifier_context = f"{normalized_lines[line_index]} {context.lower()}"
        if _contains_identifier_keyword(identifier_context):
            return None

    currency = _detect_currency(tight_context) or _detect_currency(context)
    has_currency_nearby = currency is not None

    score = 0
    score += label_score
    score += proximity_score
    if has_currency_nearby:
        score += 10

    if line_index >= int(total_lines * 0.75):
        score += 15

    if any(_line_has_negative_amount_context(normalized_lines[i]) for i in _nearby_indexes(line_index, total_lines)):
        score -= 80

    if _looks_like_identifier(context):
        score -= 8
    if DATE_PATTERN.search(context):
        score -= 4

    return {
        "score": score,
        "value": round(value, 2),
        "currency": currency,
        "raw": raw,
        "context": context,
        "position": start,
        "line_index": line_index,
        "matched_label": matched_label,
        "label_score": label_score,
    }


def _money_candidates(text: str):
    """
    Yield money-like candidates with strong preference for final payable totals.
    """
    date_spans = _find_pattern_positions(DATE_PATTERN, text)
    line_rows = _split_lines_with_offsets(text)
    normalized_lines = [_normalize_label_line(line) for line, _, _ in line_rows]
    line_label_scores = [_best_positive_label_for_line(line) for line in normalized_lines]
    line_label_matches = [_label_matches_for_line(line) for line in normalized_lines]
    has_any_positive_label = any(bool(matches) for matches in line_label_matches)

    # If no total-like label exists, treat this text as non-receipt/non-invoice for amount extraction.
    if not has_any_positive_label:
        return

    total_lines = max(1, len(line_rows))

    for match in AMOUNT_NUMBER_PATTERN.finditer(text):
        candidate = _score_candidate(
            match,
            text,
            date_spans=date_spans,
            line_rows=line_rows,
            normalized_lines=normalized_lines,
            line_label_scores=line_label_scores,
            line_label_matches=line_label_matches,
            total_lines=total_lines,
        )
        if candidate is not None:
            yield candidate


# The bool return is "confidence": True means a strong total-style label (e.g.
# "לתשלום", "amount due") was actually matched next to the number, not just guessed.
def _extract_amount_currency_and_confidence(text: str) -> tuple[float | None, str | None, bool]:
    candidates = list(_money_candidates(text))

    if not candidates:
        return None, _detect_currency(text), False

    # Prefer strongest score. If tied, prefer the latest occurrence in the document.
    # If still tied, prefer larger value.
    best = max(candidates, key=lambda c: (c["score"], c["position"], c["value"]))
    return best["value"], best["currency"] or _detect_currency(text), best["label_score"] > 0


def _extract_amount_and_currency(text: str) -> tuple[float | None, str | None]:
    amount_value, amount_currency, _ = _extract_amount_currency_and_confidence(text)
    return amount_value, amount_currency


def _parse_date_to_iso(date_text: str) -> str | None:
    cleaned = date_text.replace(".", "/").replace("-", "/")
    parts = cleaned.split("/")
    if len(parts) != 3:
        return None

    try:
        if len(parts[0]) == 4:
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
        else:
            day = int(parts[0])
            month = int(parts[1])
            year = int(parts[2])
            if year < 100:
                year += 2000
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_due_date(text: str) -> str | None:
    compact = re.sub(r"\s+", " ", text)
    patterns = [
        re.compile(
            rf"{DUE_LABEL_PATTERN}\D{{0,20}}(?P<date>{DATE_PATTERN_TEXT})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<date>{DATE_PATTERN_TEXT})\D{{0,20}}{DUE_LABEL_PATTERN}",
            re.IGNORECASE,
        ),
    ]

    for pattern in patterns:
        for match in pattern.finditer(compact):
            iso = _parse_date_to_iso(match.group("date"))
            if iso:
                return iso
    return None


def _extract_amount_and_due_date(text: str) -> dict:
    amount_value, amount_currency, amount_is_explicit = _extract_amount_currency_and_confidence(text)
    due_date_iso = _extract_due_date(text)
    return {
        "amount_value": amount_value,
        "amount_currency": amount_currency,
        "due_date_iso": due_date_iso,
        "amount_is_explicit": amount_is_explicit,
    }


# Ranks how "complete" an extraction looks. analyze_text() runs extraction twice
# (once on the raw text, once with Hebrew word order fixed) and keeps the
# higher-scoring result, since either pass can win depending on the document.
def _analysis_score(fields: dict) -> int:
    score = 0
    if fields.get("amount_value") is not None:
        score += 2
    if fields.get("amount_is_explicit"):
        score += 5
    if fields.get("amount_currency"):
        score += 1
    if fields.get("due_date_iso"):
        score += 2
    return score


def extract_text_from_pdf(path: str | Path) -> str:
    pdf_path = Path(path)

    try:
        page_texts: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_texts.append(page.extract_text() or "")
    except Exception as exc:
        logger.warning("Failed to extract text from %s: %s", pdf_path, exc)
        return ""

    return "\n".join(t for t in page_texts if t).strip()


def analyze_text(text: str, *, source_label: str = "text") -> dict:
    cleaned_text = clean_text(text or "").strip()
    if not cleaned_text:
        return {
            "text": "",
            "amount_value": None,
            "amount_currency": None,
            "due_date_iso": None,
        }

    raw_fields = _extract_amount_and_due_date(cleaned_text)
    normalized_text = _normalize_text_for_parsing(cleaned_text)
    normalized_fields = _extract_amount_and_due_date(normalized_text)

    primary = raw_fields
    secondary = normalized_fields
    if _analysis_score(normalized_fields) > _analysis_score(raw_fields):
        primary = normalized_fields
        secondary = raw_fields

    amount_value = (
        primary.get("amount_value")
        if primary.get("amount_value") is not None
        else secondary.get("amount_value")
    )
    amount_currency = primary.get("amount_currency") or secondary.get("amount_currency")
    due_date_iso = primary.get("due_date_iso") or secondary.get("due_date_iso")

    return {
        "text": cleaned_text,
        "amount_value": amount_value,
        "amount_currency": amount_currency,
        "due_date_iso": due_date_iso,
    }


def analyze_pdf(path: str | Path) -> dict:
    text = extract_text_from_pdf(path)
    return analyze_text(text, source_label=f"PDF {Path(path).name}")
