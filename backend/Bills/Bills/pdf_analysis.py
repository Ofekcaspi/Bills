from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pdfplumber

HEBREW_WORD_PATTERN = re.compile(r"[\u0590-\u05FF]+")
HAS_HEBREW_PATTERN = re.compile(r"[\u0590-\u05FF]")
CONTROL_MARKS_PATTERN = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
NUMBER_PATTERN_TEXT = r"\(?-?\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{1,2})\)?|\(?-?\d+(?:[.,]\d{1,2})\)?"
NUMBER_PATTERN = re.compile(NUMBER_PATTERN_TEXT)
DATE_PATTERN_TEXT = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}"
EXPLICIT_NUMBER_PATTERN_TEXT = r"\(?-?\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{1,2})?\)?|\(?-?\d+(?:[.,]\d{1,2})?\)?"

HEB_LETASHLUM = "\u05DC\u05EA\u05E9\u05DC\u05D5\u05DD"
HEB_SAHAK = "\u05E1\u05D4\"\u05DB"
HEB_SAHAK_NOQUOTE = "\u05E1\u05D4\u05DB"
HEB_KSAH = "\u05DB\"\u05E1\u05D4"
HEB_SAK_HAKOL = "\u05E1\u05DA \u05D4\u05DB\u05DC"
HEB_KOLEL = "\u05DB\u05D5\u05DC\u05DC"
HEB_SUM_PAID = "\u05E1\u05DB\u05D5\u05DD \u05E9\u05E9\u05D5\u05DC\u05DD"
HEB_KOTSH = "\u05E7\u05D5\u05D8\"\u05E9"
HEB_KOTSH_NOQUOTE = "\u05E7\u05D5\u05D8\u05E9"
HEB_YAMIM = "\u05D9\u05DE\u05D9\u05DD"
HEB_SHAOT = "\u05E9\u05E2\u05D5\u05EA"

PAYMENT_KEYWORDS = (
    HEB_SUM_PAID,
    HEB_LETASHLUM,
    f"{HEB_SAHAK} {HEB_LETASHLUM}",
    f"{HEB_SAHAK_NOQUOTE} {HEB_LETASHLUM}",
    f"{HEB_KSAH} {HEB_LETASHLUM}",
    "amount paid",
    "total paid",
    "amount due",
    "payment due",
    "total due",
    "balance due",
)
TOTAL_KEYWORDS = (
    HEB_SUM_PAID,
    HEB_SAHAK,
    HEB_SAHAK_NOQUOTE,
    HEB_KSAH,
    HEB_SAK_HAKOL,
    "total",
    "grand total",
    HEB_KOLEL,
)
NOISE_KEYWORDS = (
    HEB_KOTSH,
    HEB_KOTSH_NOQUOTE,
    "kwh",
    "kva",
    "kw ",
    HEB_YAMIM,
    HEB_SHAOT,
)

CURRENCY_PATTERNS = {
    "ILS": re.compile(
        r"(\u20AA|¤|\u05E9\"?\u05D7|\u05D7\"?\u05E9|\u05E9\u05D7|\u05D7\u05E9|nis|ils)",
        re.IGNORECASE,
    ),
    "USD": re.compile(r"(\$|usd)", re.IGNORECASE),
    "EUR": re.compile(r"(\u20AC|eur)", re.IGNORECASE),
}

EXPLICIT_TOTAL_LABEL_PATTERN = (
    "(?:"
    "\u05E1\u05DB\u05D5\u05DD\\s+\u05E9\u05E9\u05D5\u05DC\u05DD"  # סכום ששולם
    "|"
    "\u05E1\u05D4\"?\u05DB\\s+\u05DC\u05EA\u05E9\u05DC\u05D5\u05DD"  # סה"כ לתשלום
    "|amount\\s*paid"
    "|total\\s*paid"
    "|paid\\s*amount"
    "|total\\s*due"
    "|payment\\s*due"
    "|balance\\s*due"
    ")"
)
EXPLICIT_TOTAL_PATTERNS = (
    re.compile(
        rf"{EXPLICIT_TOTAL_LABEL_PATTERN}[^\d\r\n]{{0,80}}(?P<amount>{EXPLICIT_NUMBER_PATTERN_TEXT})",
        re.IGNORECASE,
    ),
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


def _reverse_text_for_print(text: str) -> str:
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


def _normalize_text_for_parsing(text: str) -> str:
    normalized = _reverse_text_for_print(text)
    return _clean_text(normalized)


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = CONTROL_MARKS_PATTERN.sub("", text)
    cleaned = cleaned.replace("\u00a0", " ")
    return cleaned


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

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        comma_parts = s.split(",")
        if len(comma_parts[-1]) in (1, 2):
            s = "".join(comma_parts[:-1]) + "." + comma_parts[-1]
        else:
            s = s.replace(",", "")

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


def _extract_explicit_total_amount(text: str) -> tuple[float | None, str | None]:
    candidates: list[tuple[float, str | None]] = []
    for pattern in EXPLICIT_TOTAL_PATTERNS:
        for match in pattern.finditer(text):
            raw_amount = match.group("amount")
            value = _parse_amount_number(raw_amount)
            if value is None or value <= 0:
                continue
            if value > 200_000:
                continue

            start, end = match.span("amount")
            if end < len(text) and text[end].isdigit():
                continue
            tail = text[end: end + 4]
            if tail[:1] in {"/", "-", "."} and re.match(r"\d{1,2}", tail[1:]):
                continue
            if "." not in raw_amount and "," not in raw_amount and 1900 <= value <= 2100:
                continue

            context = text[max(0, start - 30): min(len(text), end + 30)]
            currency = _detect_currency(context)
            candidates.append((value, currency))

    if not candidates:
        return None, None

    best_value, best_currency = max(candidates, key=lambda item: item[0])
    return round(best_value, 2), best_currency


def _score_amount_candidate(context: str, value: float) -> int:
    ctx = context.lower()
    score = 0

    if any(keyword in ctx for keyword in PAYMENT_KEYWORDS):
        score += 12
    if any(keyword in ctx for keyword in TOTAL_KEYWORDS):
        score += 5
    if _detect_currency(context):
        score += 3

    if any(keyword in ctx for keyword in NOISE_KEYWORDS):
        score -= 5
    if "%" in ctx:
        score -= 2
    if value <= 0:
        score -= 6
    if value > 200_000:
        score -= 3

    return score


def _extract_amount_and_currency_with_meta(text: str) -> tuple[float | None, str | None, bool]:
    explicit_amount, explicit_currency = _extract_explicit_total_amount(text)
    if explicit_amount is not None:
        return explicit_amount, explicit_currency or _detect_currency(text), True

    best: tuple[int, float, str | None] | None = None

    for match in NUMBER_PATTERN.finditer(text):
        value = _parse_amount_number(match.group(0))
        if value is None:
            continue

        start, end = match.span()
        context = text[max(0, start - 80): min(len(text), end + 80)]
        score = _score_amount_candidate(context, value)
        currency = _detect_currency(context)

        candidate = (score, value, currency)
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate

    if best is None:
        return None, None, False

    amount_value = round(best[1], 2)
    amount_currency = best[2] or _detect_currency(text)
    return amount_value, amount_currency, False


def _extract_amount_and_currency(text: str) -> tuple[float | None, str | None]:
    amount_value, amount_currency, _ = _extract_amount_and_currency_with_meta(text)
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


def _analyze_fields(text: str) -> dict:
    amount_value, amount_currency, amount_is_explicit = _extract_amount_and_currency_with_meta(text)
    due_date_iso = _extract_due_date(text)
    return {
        "amount_value": amount_value,
        "amount_currency": amount_currency,
        "due_date_iso": due_date_iso,
        "amount_is_explicit": amount_is_explicit,
    }


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
        print(f"[PDF_ANALYSIS] failed to extract text from {pdf_path}: {exc}")
        return ""

    text = "\n".join(t for t in page_texts if t).strip()
    printable_text = _reverse_text_for_print(text) if text else ""

    print()
    print("=" * 80)
    print(f"[PDF_ANALYSIS] extracted text from {pdf_path.name}:")
    if text:
        print(printable_text)
    else:
        print("[PDF_ANALYSIS] no extractable text found (non-OCR mode)")
    print("=" * 80)
    print()

    return text


def analyze_text(text: str, *, source_label: str = "text") -> dict:
    cleaned_text = _clean_text(text or "").strip()
    if not cleaned_text:
        return {
            "text": "",
            "amount_value": None,
            "amount_currency": None,
            "due_date_iso": None,
        }

    raw_fields = _analyze_fields(cleaned_text)
    normalized_text = _normalize_text_for_parsing(cleaned_text)
    normalized_fields = _analyze_fields(normalized_text)

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

    print(
        f"[TEXT_ANALYSIS] parsed fields from {source_label}: "
        f"amount_value={amount_value}, amount_currency={amount_currency}, due_date_iso={due_date_iso}"
    )

    return {
        "text": cleaned_text,
        "amount_value": amount_value,
        "amount_currency": amount_currency,
        "due_date_iso": due_date_iso,
    }


def analyze_pdf(path: str | Path) -> dict:
    text = extract_text_from_pdf(path)
    return analyze_text(text, source_label=f"PDF {Path(path).name}")
