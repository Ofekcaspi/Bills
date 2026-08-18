from __future__ import annotations

import re
from typing import Optional

from .hebrew_text import reverse_hebrew_words


#this module determines the category of the invoice
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


def _normalize_text(s: str) -> str:
    s = s or ""
    s = s.lower()
    s = s.replace("‏", " ").replace("‎", " ")
    return s

CATEGORY_RULES=[(x[0],[reverse_hebrew_words(y) for y in x[1]])for x in CATEGORY_RULES]


class BillCategorizer:
    """Matches a bill's subject/sender/filename against CATEGORY_RULES."""

    def __init__(self, rules=CATEGORY_RULES):
        self.rules = rules

    def classify(
            self,
            subject: str | None,
            sender: str | None,
            filename: str | None,
    ) -> Optional[str]:
        
        haystack = self._build_haystack(subject, sender, filename)

        for category, patterns in self.rules:
            if self._any_pattern_matches(patterns, haystack):
                return category

        return None

    def _build_haystack(
            self,
            subject: str | None,
            sender: str | None,
            filename: str | None,
    ) -> str:
        text = " ".join([
            reverse_hebrew_words(subject),
            reverse_hebrew_words(sender),
            reverse_hebrew_words(filename),
        ])
        return _normalize_text(text)

    @staticmethod
    def _any_pattern_matches(patterns, haystack: str) -> bool:
        return any(
            re.search(pattern, haystack, flags=re.IGNORECASE)
            for pattern in patterns
        )


_default_categorizer = BillCategorizer()


def classify_category(
        subject: str | None,
        sender: str | None,
        filename: str | None,
) -> Optional[str]:
    return _default_categorizer.classify(subject, sender, filename)
