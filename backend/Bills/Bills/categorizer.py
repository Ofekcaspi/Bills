from __future__ import annotations

import re
from typing import Optional


# סדר חשוב: הראשון שתופס ינצח
CATEGORY_RULES = [
    ("חשמל", [
        r"\biec\b", r"\bישראל\s*אלקטריק\b", r"\bחברת\s*החשמל\b",
        r"electric", r"electricity", r"חשמל",
    ]),
    ("מים", [
        r"\bמים\b",
        r"\bמי\b",                 # "מי" כמילה שלמה
        r"\bmey7\b",
        r"\bמי[-\s]*שתייה\b",      # "מי שתייה" / "מי-שתייה"
        r"water",
        r"מקורות",
        r"תאגיד\s*מים",
        r"מב\s*י",
        r"מב״י",
    ])
,
    ("ארנונה", [
        r"ארנונה", r"עיריי?ה", r"municipal", r"property\s*tax", r"גביה",
    ]),
    ("גז", [
        r"גז", r"\bampal\b", r"פזגז", r"סופרגז", r"gas",
    ]),
    ("אינטרנט", [
        r"אינטרנט", r"fiber", r"סיבים", r"hot", r"yes", r"partner",
        r"cellcom", r"סלקום", r"פרטנר", r"בזק", r"bezeq",
    ]),
    ("סלולר", [
        r"סלולר", r"mobile", r"cellular", r"\bpartner\b", r"\bpelephone\b",
        r"\bhot\s*mobile\b", r"\bgolan\b", r"גולן", r"פלאפון",
    ]),
    ("ביטוח", [
        r"ביטוח", r"insurance", r"מגדל", r"הראל", r"כלל", r"מנורה",
        r"איילון", r"פניקס", r"כלל\s*ביטוח", r"migdal", r"harel",
    ]),
    ("בנק", [
        r"בנק", r"bank", r"לאומי", r"הפועלים", r"דיסקונט",
        r"פאגי", r"מרכנתיל", r"mizrah", r"mizrahi", r"tefachot",
    ]),
    ("שכירות", [
        r"שכירות", r"rent", r"דמי\s*שכירות", r"חוזה\s*שכירות",
    ]),
    ("ועד בית", [
        r"ועד\s*בית", r"בית\s*משותף", r"hoa",
    ]),
    ("מנוי", [
        r"מנוי", r"subscription", r"charge", r"חיוב\s*חודשי",
        r"netflix", r"spotify", r"apple", r"google",
    ]),
]


def _norm(s: str) -> str:
    s = s or ""
    s = s.lower()
    # ניקוי בסיסי
    s = s.replace("\u200f", " ").replace("\u200e", " ")
    return s

HEBREW_RE = re.compile(r"[א-ת]+(?:[״׳'][א-ת]+)?")

def _reverse_hebrew_words(text: str | None) -> str:
    """
    הופך רק מילים בעברית.
    מילים באנגלית, מספרים וסימנים נשארים כמו שהם.
    """
    if not text:
        return ""

    return HEBREW_RE.sub(lambda m: m.group(0)[::-1], text)

CATEGORY_RULES=[(x[0],[_reverse_hebrew_words(y) for y in x[1]])for x in CATEGORY_RULES]
def classify_category(
        subject: str | None,
        sender: str | None,
        filename: str | None
) -> Optional[str]:
    """
    מחזיר שם קטגוריה בעברית או None.
    אם יש מילים בעברית שהגיעו הפוכות/בכיוון בעייתי,
    הפונקציה הופכת רק את המילים בעברית לפני הסיווג.
    """

    text = " ".join([
        _reverse_hebrew_words(subject),
        _reverse_hebrew_words(sender),
        _reverse_hebrew_words(filename),
    ])

    hay = _norm(text)

    print(hay)

    for cat, patterns in CATEGORY_RULES:
        for p in patterns:
            if re.search(p, hay, flags=re.IGNORECASE) or re.search(p, hay, flags=re.IGNORECASE):
                return cat

    return None