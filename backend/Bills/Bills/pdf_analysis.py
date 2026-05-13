from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pdfplumber

HEBREW_WORD_PATTERN = re.compile(r"[\u0590-\u05FF]+")
HAS_HEBREW_PATTERN = re.compile(r"[\u0590-\u05FF]")
CONTROL_MARKS_PATTERN = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")

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
AMOUNT_NUMBER_TEXT = r"\(?-?\d{1,3}(?:[,\.\s]\d{3})+(?:[,.]\d{1,2})?\)?|\(?-?\d+(?:[,.]\d{1,2})?\)?"
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

TOTAL_KEYWORDS = (
    HEB_SUM_PAID,
    HEB_LETASHLUM,
    f"{HEB_SAHAK} {HEB_LETASHLUM}",
    f"{HEB_SAHAK_NOQUOTE} {HEB_LETASHLUM}",
    f"{HEB_KSAH} {HEB_LETASHLUM}",
    HEB_SAHAK,
    HEB_SAHAK_NOQUOTE,
    HEB_KSAH,
    HEB_SAK_HAKOL,
    HEB_KOLEL,
    HEB_MECHIR,
    HEB_YITRA,
    HEB_LCHIYUV,
    HEB_TASHLUM,
    "amount paid",
    "total paid",
    "paid amount",
    "amount due",
    "payment due",
    "total due",
    "balance due",
    "grand total",
    "total",
    "subtotal",
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
    "מספר",
    "מונה",
    "קריאה",
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


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = CONTROL_MARKS_PATTERN.sub("", text)
    cleaned = cleaned.replace("\u00a0", " ")
    return cleaned


def _normalize_text_for_parsing(text: str) -> str:
    normalized = _reverse_text_for_print(text)
    return _clean_text(normalized)


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


def _spans_for(pattern: re.Pattern, text: str) -> list[tuple[int, int]]:
    return [m.span() for m in pattern.finditer(text)]


def _inside_any_span(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start >= span_start and end <= span_end for span_start, span_end in spans)


def _looks_like_year(value: float, raw: str) -> bool:
    return "." not in raw and "," not in raw and 1900 <= value <= 2100


def _looks_like_identifier(context: str) -> bool:
    ctx = context.lower()
    return any(keyword in ctx for keyword in NOISE_KEYWORDS)


def _money_candidates(text: str):
    """
    Yield money-like candidates only. A number is accepted when either:
      1. it has a currency token close to it, or
      2. it has a strong total/payment label close to it.

    This intentionally avoids treating arbitrary dates, IDs, quantities, and counts as amounts.
    """
    date_spans = _spans_for(DATE_PATTERN, text)

    for match in AMOUNT_NUMBER_PATTERN.finditer(text):
        raw = match.group(0)
        start, end = match.span()

        if _inside_any_span(start, end, date_spans):
            continue

        value = _parse_amount_number(raw)
        if value is None or value <= 0:
            continue

        if value > 200_000:
            continue

        if _looks_like_year(value, raw):
            continue

        # Avoid fragments in dates like 10/05/2026 even if the regex saw just "10".
        before = text[max(0, start - 1):start]
        after = text[end:end + 1]
        if before in {"/", "-"} or after in {"/", "-"}:
            continue

        context = text[max(0, start - 80): min(len(text), end + 80)]
        tight_context = text[max(0, start - 15): min(len(text), end + 15)]

        if "%" in tight_context:
            continue

        currency = _detect_currency(tight_context) or _detect_currency(context)
        has_currency_nearby = currency is not None
        has_total_label_nearby = any(keyword in context.lower() for keyword in TOTAL_KEYWORDS)

        if not has_currency_nearby and not has_total_label_nearby:
            continue

        score = 0
        if has_currency_nearby:
            score += 10
        if has_total_label_nearby:
            score += 8
        if any(keyword in context.lower() for keyword in ("grand total", "total due", "balance due", HEB_LETASHLUM, HEB_SAHAK, HEB_SAHAK_NOQUOTE)):
            score += 5
        if _looks_like_identifier(context):
            score -= 8
        if DATE_PATTERN.search(context):
            score -= 4

        yield {
            "score": score,
            "value": round(value, 2),
            "currency": currency,
            "raw": raw,
            "context": context,
        }


def _extract_amount_and_currency_with_meta(text: str) -> tuple[float | None, str | None, bool]:
    candidates = list(_money_candidates(text))

    if not candidates:
        return None, _detect_currency(text), False

    # Prefer stronger context; if tied, prefer the larger money value because totals are
    # usually larger than tax, line items, discounts, or fees.
    best = max(candidates, key=lambda c: (c["score"], c["value"]))
    return best["value"], best["currency"] or _detect_currency(text), best["score"] >= 15


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

    return "\n".join(t for t in page_texts if t).strip()


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

    return {
        "text": cleaned_text,
        "amount_value": amount_value,
        "amount_currency": amount_currency,
        "due_date_iso": due_date_iso,
    }


def analyze_pdf(path: str | Path) -> dict:
    text = extract_text_from_pdf(path)
    return analyze_text(text, source_label=f"PDF {Path(path).name}")
